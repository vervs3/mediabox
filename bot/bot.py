import os
import asyncio
import logging
import math
from datetime import timedelta

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# --- Config ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
TRANSMISSION_URL = os.environ.get("TRANSMISSION_URL", "http://transmission:9091/transmission/rpc")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "30"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# --- Transmission RPC ---
class TransmissionClient:
    def __init__(self, url):
        self.url = url
        self._session_id = ""

    async def _request(self, method, arguments=None):
        payload = {"method": method, "arguments": arguments or {}}
        headers = {"X-Transmission-Session-Id": self._session_id}
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(self.url, json=payload, headers=headers)
            if r.status_code == 409:
                self._session_id = r.headers.get("X-Transmission-Session-Id", "")
                r = await c.post(self.url, json=payload,
                                 headers={"X-Transmission-Session-Id": self._session_id})
            r.raise_for_status()
            return r.json()

    async def get_torrents(self, fields=None):
        fields = fields or [
            "id", "name", "status", "percentDone", "rateDownload", "rateUpload",
            "eta", "totalSize", "downloadedEver", "uploadedEver", "error",
            "errorString", "peersConnected", "uploadRatio", "addedDate"
        ]
        r = await self._request("torrent-get", {"fields": fields})
        return r["arguments"]["torrents"]

    async def get_torrent(self, tid):
        r = await self._request("torrent-get", {
            "ids": [tid],
            "fields": [
                "id", "name", "status", "percentDone", "rateDownload", "rateUpload",
                "eta", "totalSize", "downloadedEver", "uploadedEver", "error",
                "errorString", "peersConnected", "uploadRatio", "addedDate"
            ]
        })
        torrents = r["arguments"]["torrents"]
        return torrents[0] if torrents else None

    async def add_torrent(self, torrent_data=None, url=None):
        args = {"paused": False}
        if torrent_data:
            import base64
            args["metainfo"] = base64.b64encode(torrent_data).decode()
        elif url:
            args["filename"] = url
        r = await self._request("torrent-add", args)
        return r["arguments"]

    async def remove_torrent(self, tid, delete_data=False):
        await self._request("torrent-remove", {"ids": [tid], "delete-local-data": delete_data})

    async def start_torrent(self, tid):
        await self._request("torrent-start", {"ids": [tid]})

    async def stop_torrent(self, tid):
        await self._request("torrent-stop", {"ids": [tid]})

    async def get_session(self):
        r = await self._request("session-get")
        return r["arguments"]

    async def get_session_stats(self):
        r = await self._request("session-stats")
        return r["arguments"]


client = TransmissionClient(TRANSMISSION_URL)
completed_ids: set = set()


# --- Formatters ---
STATUS_ICON = {0: "⏸", 1: "⏳", 2: "🔍", 3: "⬇️", 4: "⬇️", 5: "⏳", 6: "🌱"}
STATUS_TEXT = {
    0: "Остановлен", 1: "В очереди", 2: "Проверка",
    3: "Загрузка", 4: "Загрузка", 5: "Очередь раздачи", 6: "Раздача"
}

def fmt_size(b):
    if b == 0:
        return "0 Б"
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    i = min(int(math.log(b, 1024)), len(units) - 1)
    return f"{b / 1024**i:.1f} {units[i]}"

def fmt_speed(b):
    return fmt_size(b) + "/с"

def fmt_eta(s):
    if s < 0:
        return "∞"
    if s < 60:
        return f"{s}с"
    if s < 3600:
        return f"{s//60}м {s%60}с"
    h, rem = divmod(s, 3600)
    return f"{h}ч {rem//60}м"

def fmt_ratio(r):
    return f"{r:.2f}"

def progress_bar(pct, width=12):
    filled = round(pct * width)
    return "█" * filled + "░" * (width - filled)

def torrent_card(t):
    name = t["name"]
    pct = t["percentDone"]
    status = t["status"]
    icon = STATUS_ICON.get(status, "❓")
    name_display = (name[:50] + "…") if len(name) > 50 else name
    bar = progress_bar(pct)
    size = fmt_size(t["totalSize"])
    done = fmt_size(t["downloadedEver"])

    lines = [
        f"{icon} *{name_display}*",
        f"[{bar}] *{pct*100:.1f}%*",
        f"💾 {done} / {size}",
    ]

    if status == 3:
        lines.append(f"⬇️ {fmt_speed(t['rateDownload'])}  ·  ETA {fmt_eta(t['eta'])}")
        lines.append(f"👥 Пиров: {t['peersConnected']}")
    elif status == 6:
        lines.append(f"⬆️ {fmt_speed(t['rateUpload'])}  ·  Рейтинг: {fmt_ratio(t['uploadRatio'])}")
    elif status == 0:
        lines.append(f"⬆️ Загружено: {fmt_size(t['uploadedEver'])}")

    if t.get("error") and t["error"] != 0:
        lines.append(f"⚠️ {t['errorString']}")

    return "\n".join(lines)

def torrent_keyboard(t):
    tid = t["id"]
    status = t["status"]
    buttons = []

    if status == 0:
        buttons.append(InlineKeyboardButton("▶️ Запустить", callback_data=f"start:{tid}"))
    elif status in (3, 4, 6):
        buttons.append(InlineKeyboardButton("⏸ Пауза", callback_data=f"stop:{tid}"))

    buttons.append(InlineKeyboardButton("🔄 Обновить", callback_data=f"info:{tid}"))
    buttons.append(InlineKeyboardButton("🗑 Удалить", callback_data=f"del_ask:{tid}"))

    return InlineKeyboardMarkup([buttons[:2], buttons[2:]])


# --- Auth ---
def auth(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ALLOWED_USER_ID:
            await update.message.reply_text("⛔ Доступ запрещён")
            return
        await func(update, ctx)
    return wrapper

def auth_callback(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ALLOWED_USER_ID:
            await update.callback_query.answer("⛔ Нет доступа", show_alert=True)
            return
        await func(update, ctx)
    return wrapper


# --- Commands ---
@auth
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🌊 *Flood Transmission Bot*\n\n"
        "Управляй торрентами прямо из Telegram\\.\n\n"
        "📋 *Команды:*\n"
        "• /list — список всех торрентов\n"
        "• /active — только активные\n"
        "• /stats — статистика сессии\n"
        "• /help — справка\n\n"
        "📎 *Добавить торрент:*\n"
        "Отправь `.torrent` файл или `magnet:` ссылку"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

@auth
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Справка*\n\n"
        "*Добавление торрентов:*\n"
        "• Отправь `.torrent` файл\n"
        "• Отправь `magnet:` ссылку текстом\n\n"
        "*Управление:*\n"
        "• Нажми на торрент в /list для управления\n"
        "• ▶️ запуск  ·  ⏸ пауза  ·  🗑 удаление\n\n"
        "*Watch\\-папка:*\n"
        "Кинь `.torrent` в папку `watch` на NAS — начнёт качать автоматически\n\n"
        "*Веб\\-интерфейс:*\n"
        "`http://localhost:9091` — Flood UI\n"
        "`http://localhost:8096` — Jellyfin"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

@auth
async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        torrents = await client.get_torrents()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка подключения: `{e}`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    if not torrents:
        await update.message.reply_text("📭 *Нет торрентов*", parse_mode=ParseMode.MARKDOWN_V2)
        return

    torrents.sort(key=lambda t: (-t["status"], t["percentDone"]))
    for t in torrents:
        await update.message.reply_text(torrent_card(t), parse_mode=ParseMode.MARKDOWN, reply_markup=torrent_keyboard(t))

@auth
async def cmd_active(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        torrents = await client.get_torrents()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: `{e}`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    active = [t for t in torrents if t["status"] in (3, 4, 6)]
    if not active:
        await update.message.reply_text("😴 *Нет активных торрентов*", parse_mode=ParseMode.MARKDOWN_V2)
        return

    for t in active:
        await update.message.reply_text(torrent_card(t), parse_mode=ParseMode.MARKDOWN, reply_markup=torrent_keyboard(t))

@auth
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        stats = await client.get_session_stats()
        torrents = await client.get_torrents(["status", "rateDownload", "rateUpload", "totalSize"])
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    dl_speed = sum(t["rateDownload"] for t in torrents)
    ul_speed = sum(t["rateUpload"] for t in torrents)
    downloading = sum(1 for t in torrents if t["status"] in (3, 4))
    seeding = sum(1 for t in torrents if t["status"] == 6)
    stopped = sum(1 for t in torrents if t["status"] == 0)
    total_size = sum(t["totalSize"] for t in torrents)
    cum = stats.get("cumulative-stats", {})

    text = (
        f"📊 *Статистика Transmission*\n\n"
        f"*Прямо сейчас:*\n"
        f"⬇️ Загрузка: `{fmt_speed(dl_speed)}`\n"
        f"⬆️ Раздача: `{fmt_speed(ul_speed)}`\n\n"
        f"*Торренты:*\n"
        f"⬇️ Загружается: `{downloading}`\n"
        f"🌱 Раздаётся: `{seeding}`\n"
        f"⏸ Остановлено: `{stopped}`\n"
        f"📦 Всего: `{len(torrents)}` · `{fmt_size(total_size)}`\n\n"
        f"*За всё время:*\n"
        f"⬇️ Скачано: `{fmt_size(cum.get('downloadedBytes', 0))}`\n"
        f"⬆️ Отдано: `{fmt_size(cum.get('uploadedBytes', 0))}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# --- Callbacks ---
@auth_callback
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("info:"):
        tid = int(data.split(":")[1])
        t = await client.get_torrent(tid)
        if not t:
            await q.edit_message_text("❌ Торрент не найден")
            return
        await q.edit_message_text(torrent_card(t), parse_mode=ParseMode.MARKDOWN, reply_markup=torrent_keyboard(t))

    elif data.startswith("start:"):
        tid = int(data.split(":")[1])
        await client.start_torrent(tid)
        t = await client.get_torrent(tid)
        await q.edit_message_text(torrent_card(t), parse_mode=ParseMode.MARKDOWN, reply_markup=torrent_keyboard(t))

    elif data.startswith("stop:"):
        tid = int(data.split(":")[1])
        await client.stop_torrent(tid)
        t = await client.get_torrent(tid)
        await q.edit_message_text(torrent_card(t), parse_mode=ParseMode.MARKDOWN, reply_markup=torrent_keyboard(t))

    elif data.startswith("del_ask:"):
        tid = int(data.split(":")[1])
        t = await client.get_torrent(tid)
        name = (t["name"][:40] + "…") if t and len(t["name"]) > 40 else (t["name"] if t else "?")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Только торрент", callback_data=f"del:{tid}:0"),
            InlineKeyboardButton("💣 С файлами", callback_data=f"del:{tid}:1"),
        ], [
            InlineKeyboardButton("❌ Отмена", callback_data=f"info:{tid}"),
        ]])
        await q.edit_message_text(
            f"⚠️ *Удалить торрент?*\n`{name}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )

    elif data.startswith("del:"):
        _, tid_str, del_data_str = data.split(":")
        tid = int(tid_str)
        delete_data = del_data_str == "1"
        t = await client.get_torrent(tid)
        name = t["name"][:40] if t else "?"
        await client.remove_torrent(tid, delete_data)
        suffix = " и файлы" if delete_data else ""
        await q.edit_message_text(f"🗑 Удалён{suffix}: `{name}`", parse_mode=ParseMode.MARKDOWN)


# --- File & magnet handlers ---
@auth
async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".torrent"):
        return
    msg = await update.message.reply_text("⏳ Добавляю торрент…")
    try:
        file = await ctx.bot.get_file(doc.file_id)
        data = await file.download_as_bytearray()
        result = await client.add_torrent(torrent_data=bytes(data))
        if "torrent-added" in result:
            name = result["torrent-added"].get("name", "?")
            await msg.edit_text(f"✅ *Добавлен!*\n📁 `{name}`", parse_mode=ParseMode.MARKDOWN)
        else:
            name = result.get("torrent-duplicate", {}).get("name", "?")
            await msg.edit_text(f"⚠️ *Уже существует*\n📁 `{name}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: `{e}`", parse_mode=ParseMode.MARKDOWN)

@auth
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("magnet:"):
        return
    msg = await update.message.reply_text("⏳ Добавляю magnet…")
    try:
        result = await client.add_torrent(url=text)
        if "torrent-added" in result:
            name = result["torrent-added"].get("name", "Получение метаданных…")
            await msg.edit_text(f"✅ *Добавлен!*\n📁 `{name}`", parse_mode=ParseMode.MARKDOWN)
        else:
            name = result.get("torrent-duplicate", {}).get("name", "?")
            await msg.edit_text(f"⚠️ *Уже существует*\n📁 `{name}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: `{e}`", parse_mode=ParseMode.MARKDOWN)


# --- Background completion checker ---
async def check_completed(app: Application):
    global completed_ids
    try:
        torrents = await client.get_torrents(["id", "percentDone"])
        completed_ids = {t["id"] for t in torrents if t["percentDone"] == 1.0}
        log.info(f"Init: {len(completed_ids)} уже завершённых")
    except Exception as e:
        log.warning(f"Init error: {e}")

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            torrents = await client.get_torrents(["id", "name", "percentDone", "totalSize"])
            for t in torrents:
                tid = t["id"]
                if t["percentDone"] == 1.0 and tid not in completed_ids:
                    completed_ids.add(tid)
                    kb = InlineKeyboardMarkup([[
                        InlineKeyboardButton("📋 Подробнее", callback_data=f"info:{tid}"),
                        InlineKeyboardButton("🗑 Удалить", callback_data=f"del_ask:{tid}"),
                    ]])
                    await app.bot.send_message(
                        ALLOWED_USER_ID,
                        f"✅ *Скачано\\!*\n\n📁 `{t['name']}`\n💾 {fmt_size(t['totalSize'])}",
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_markup=kb
                    )
        except Exception as e:
            log.warning(f"Ошибка проверки: {e}")


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("list", "📋 Список всех торрентов"),
        BotCommand("active", "⚡ Активные загрузки"),
        BotCommand("stats", "📊 Статистика сессии"),
        BotCommand("help", "📖 Справка"),
        BotCommand("start", "🌊 Главное меню"),
    ])
    await app.bot.set_my_description(
        "🌊 Flood Transmission Bot\n\n"
        "Управляй торрентами прямо из Telegram:\n"
        "• Добавляй .torrent файлы и magnet-ссылки\n"
        "• Следи за прогрессом загрузок\n"
        "• Получай уведомления о завершении\n"
        "• Управляй очередью одним касанием"
    )
    await app.bot.set_my_short_description(
        "🌊 Управление Transmission — торренты, статистика и уведомления в Telegram"
    )
    asyncio.create_task(check_completed(app))


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("active", cmd_active))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    log.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
