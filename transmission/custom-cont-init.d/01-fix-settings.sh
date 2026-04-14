#!/bin/sh
# Создаём нужные папки на сетевом диске
mkdir -p /downloads/Downloads
mkdir -p /downloads/.incomplete
mkdir -p /downloads/watch

# Применяем настройки после того как контейнер создал settings.json
SETTINGS=/config/settings.json
if [ -f "$SETTINGS" ]; then
    sed -i 's|"watch-dir": ".*"|"watch-dir": "/downloads/watch"|' $SETTINGS
    sed -i 's|"watch-dir-enabled": false|"watch-dir-enabled": true|' $SETTINGS
    sed -i 's|"download-dir": ".*"|"download-dir": "/downloads/Downloads"|' $SETTINGS
    sed -i 's|"incomplete-dir": ".*"|"incomplete-dir": "/downloads/.incomplete"|' $SETTINGS
    sed -i 's|"incomplete-dir-enabled": false|"incomplete-dir-enabled": true|' $SETTINGS
fi
