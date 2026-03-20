#!/bin/bash
#
echo "Проверка наличия Python >= 3.14.3..." #
PYTHON_CMD="" #

if command -v python3 &> /dev/null && python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,14,3) else 1)" 2>/dev/null; then #
    PYTHON_CMD="python3" #
elif command -v python &> /dev/null && python -c "import sys; sys.exit(0 if sys.version_info >= (3,14,3) else 1)" 2>/dev/null; then #
    PYTHON_CMD="python" #
fi #

if [ -z "$PYTHON_CMD" ]; then #
    echo "[ОШИБКА] Требуется Python версии 3.14.3 или выше!" #
    echo "Пожалуйста, обновите Python в вашей системе." #
    exit 1 #
fi #

echo "Подходящий Python найден: $PYTHON_CMD" #

if ! dpkg -s python3-venv >/dev/null 2>&1; then #
    echo "Устанавливаем системный пакет python3-venv (требуются права sudo)..." #
    sudo apt-get update #
    sudo apt-get install -y python3-venv #
fi #

if [ ! -d "venv" ]; then #
    echo "Создание виртуального окружения..." #
    $PYTHON_CMD -m venv venv #
fi #

echo "Активация окружения и установка пакетов..." #
source venv/bin/activate #
pip install --upgrade pip #
pip install -r requirements.txt #

echo "" #
echo "=========================================" #
echo "Установка успешно завершена!" #
echo "Теперь вы можете запускать bash _run.sh" #
echo "=========================================" #