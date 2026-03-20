@echo off
chcp 65001 >nul

if not exist "venv\Scripts\activate.bat" (
    echo [ОШИБКА] Виртуальное окружение не найдено! Сначала запустите _setup.bat
    pause
    exit /b
)

call venv\Scripts\activate.bat
echo Запуск сервера CLEAR.node...
echo Для остановки нажмите Ctrl+C
echo -----------------------------------------

python main.py

pause