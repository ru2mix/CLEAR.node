@echo off
cd /d "%~dp0"

:: Убираем лишний слеш в конце пути
set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"

:: Имя службы = имя папки
for %%I in ("%ROOT_DIR%") do set "SERVICE_NAME=%%~nxI"

:: Пути
set "NSSM_EXE=%ROOT_DIR%\nssm.exe"
set "PYTHON_EXE=%ROOT_DIR%\venv\Scripts\python.exe"
set "SCRIPT_PATH=main.py"

:: Проверка наличия nssm.exe в папке
if not exist "%NSSM_EXE%" (
    echo [ERROR] nssm.exe не найден в папке проекта!
    pause
    exit /b
)

:: Установка и настройка (используем полный путь к нашему nssm.exe)
"%NSSM_EXE%" install "%SERVICE_NAME%" "%PYTHON_EXE%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppParameters "%SCRIPT_PATH%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppDirectory "%ROOT_DIR%"

:: Попытка запуска
"%NSSM_EXE%" start "%SERVICE_NAME%"

echo Служба "%SERVICE_NAME%" настроена через локальный nssm.exe.
pause