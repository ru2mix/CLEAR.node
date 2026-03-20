@echo off
chcp 65001 >nul
echo Проверка наличия Python 3.14.3 или выше...

:: Проверяем через py
py -c "import sys; sys.exit(0 if sys.version_info >= (3,10,11) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=py
    echo Найдена подходящая версия через 'py'.
    goto create_venv
)

:: Проверяем через python
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10,11) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=python
    echo Найдена подходящая версия через 'python'.
    goto create_venv
)

echo [ВНИМАНИЕ] Python нужной версии (>= 3.14.3) не найден!
echo Пожалуйста, скачайте актуальную версию с официального сайта python.org
echo При установке не забудьте поставить галочку "Add Python to PATH".
pause
exit /b

:create_venv
if exist "venv" goto install_deps

echo Создание виртуального окружения (venv)...
%PYTHON_CMD% -m venv venv

:install_deps
echo Активация окружения и установка пакетов...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo =========================================
echo Установка успешно завершена! 
echo Теперь вы можете запускать _run.bat
echo =========================================
pause