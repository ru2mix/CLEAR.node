#!/bin/bash

echo "Проверка наличия Python 3..."
if ! command -v python3 &> /dev/null
then
    echo "Python 3 не найден. Пытаемся установить (потребуются права sudo)..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip
else
    echo "Python 3 найден!"
fi

# Проверка наличия модуля venv (иногда в Ubuntu он ставится отдельно)
if ! dpkg -s python3-venv >/dev/null 2>&1; then
    echo "Устанавливаем пакет python3-venv..."
    sudo apt-get install -y python3-venv
fi

if [ ! -d "venv" ]; then
    echo "Создание виртуального окружения..."
    python3 -m venv venv
fi

echo "Активация окружения и установка пакетов..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "========================================="
echo "Установка успешно завершена!"
echo "Теперь вы можете запускать ./run.sh"
echo "========================================="