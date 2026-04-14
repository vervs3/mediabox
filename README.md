# 🌊 MediaBox

> Домашний медиасервер за 5 минут: Transmission + Jellyfin + Telegram-бот + поддержка NAS/сетевого диска

![Docker](https://img.shields.io/badge/docker-compose-blue)
![Jellyfin](https://img.shields.io/badge/jellyfin-latest-purple)
![Transmission](https://img.shields.io/badge/transmission-4.x-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

## Что внутри

| Сервис | Порт | Описание |
|--------|------|----------|
| **Transmission + Flood UI** | 9091 | Торрент-клиент с современным веб-интерфейсом |
| **Jellyfin** | 8096 | Медиасервер — смотри фильмы как в Netflix |
| **Telegram-бот** | — | Управление торрентами прямо из Telegram |

## Возможности

- 📥 Загрузка торрентов через веб, Telegram-бота или watch-папку
- 📺 Стриминг на телевизор, телефон, браузер через Jellyfin
- 💾 Поддержка сетевых дисков NAS (SMB/CIFS) — роутеры Keenetic, Synology, QNAP и др.
- 🤖 Telegram-бот с прогресс-барами, уведомлениями и управлением очередью
- 🔄 Watch-папка — кинул `.torrent` файл, качается само
- 🐳 Всё в Docker, поднимается одной командой

## Быстрый старт

### Требования

- Docker Desktop (Windows/Mac) или Docker Engine (Linux)
- NAS или сетевой диск с SMB/CIFS доступом (или можно использовать локальную папку)
- Telegram-бот (создать у [@BotFather](https://t.me/BotFather))

### 1. Клонировать репозиторий

```bash
git clone https://github.com/your-username/mediabox.git
cd mediabox
```

### 2. Настроить конфигурацию

```bash
cp .env.example .env
```

Отредактировать `.env`:

```env
# Ваш сетевой диск (NAS, роутер Keenetic и т.д.)
SMB_HOST=//192.168.1.45/Transmission
SMB_USER=admin
SMB_PASSWORD=your_password

# Telegram-бот
BOT_TOKEN=123456789:AAxxxxx...
ALLOWED_USER_ID=123456789  # узнать у @userinfobot
```

> Если NAS не нужен — замените volume `downloads` в `docker-compose.yml` на обычную локальную папку.

### 3. Установить Flood UI

```bash
# Linux/Mac
bash transmission/setup-flood.sh

# Windows (PowerShell)
# Скачайте flood-for-transmission.tar.gz с GitHub и распакуйте в transmission/config/flood-ui/
```

### 4. Запустить

```bash
docker compose up -d
```

Готово! Открывай:
- **Transmission (Flood):** http://localhost:9091
- **Jellyfin:** http://localhost:8096

## Telegram-бот

### Команды

| Команда | Описание |
|---------|----------|
| `/list` | Список всех торрентов с прогресс-барами |
| `/active` | Только активные загрузки |
| `/stats` | Статистика: скорости, объёмы, история |
| `/help` | Справка |

### Добавление торрентов

- Отправить `.torrent` файл боту
- Отправить `magnet:` ссылку текстом
- Кинуть `.torrent` в папку `watch` на NAS

### Уведомления

Бот автоматически уведомит когда торрент скачается, с кнопками "Подробнее" и "Удалить".

## Jellyfin — первый запуск

1. Открыть http://localhost:8096
2. Пройти мастер настройки
3. Добавить медиатеку → путь `/media/Downloads`
4. Jellyfin автоматически подтянет постеры и описания

### Подключение с TV/телефона

Установить приложение **Jellyfin** (Android TV, Apple TV, iOS, Android) и ввести адрес:
```
http://192.168.x.x:8096
```
где `192.168.x.x` — IP вашего компьютера в локальной сети.

## Структура папок на NAS

```
NAS/
├── Downloads/      # Завершённые загрузки (читает Jellyfin)
├── .incomplete/    # Незавершённые (скрытая папка)
└── watch/          # Watch-папка — кинул .torrent → качается само
```

## FAQ

**Q: Работает ли без NAS?**  
A: Да, замените CIFS volume на обычную папку:
```yaml
volumes:
  downloads:
    driver: local
    driver_opts:
      type: none
      device: /path/to/your/folder
      o: bind
```

**Q: Можно ли добавить VPN?**  
A: Да, добавьте сервис [gluetun](https://github.com/qdm12/gluetun) и переведите transmission на его сеть.

**Q: Как обновить образы?**  
```bash
docker compose pull && docker compose up -d
```

## Лицензия

MIT
