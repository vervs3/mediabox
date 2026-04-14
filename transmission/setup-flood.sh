#!/bin/sh
# Скачивает Flood UI в папку конфига Transmission
# Запускать один раз перед docker compose up

set -e

FLOOD_VERSION="v1.0.1"
DEST="./transmission/config/flood-ui"

echo "Скачиваем Flood UI $FLOOD_VERSION..."
mkdir -p "$DEST"
curl -sL "https://github.com/johman10/flood-for-transmission/releases/download/$FLOOD_VERSION/flood-for-transmission.tar.gz" \
  | tar -xz -C "$DEST" --strip-components=1

echo "Готово! Flood UI установлен в $DEST"
