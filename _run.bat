@echo off
chcp 65001 >nul

if not exist "venv\Scripts\activate.bat" (
    echo [ОШИБКА] Виртуальное окружение не найдено! Сначала запустите setup.bat
    pause
    exit /b
)

call venv\Scripts\activate.bat
echo Запуск сервера CLEAR.node...
echo Для остановки нажмите Ctrl+C
echo -----------------------------------------

:: Пробуем запустить через python (стандарт для venv)
python main.py

:: Если предыдущая команда упала с ошибкой (например, не найдена), пробуем py
IF %ERRORLEVEL% NEQ 0 (
    echo Команда python не сработала, пробуем py...
    py main.py
)

pause