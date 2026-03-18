#!/bin/bash

if [ ! -f "venv/bin/activate" ]; then
    echo "[ОШИБКА] Виртуальное окружение не найдено! Сначала запустите ./setup.sh"
    exit 1
fi

source venv/bin/activate
echo "Запуск сервера CLEAR.node..."
echo "Для остановки нажмите Ctrl+C"
echo "-----------------------------------------"
python3 main.py