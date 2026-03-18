@echo off
chcp 65001 >nul
echo Проверка наличия Python...

py --version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto use_py

python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto use_python

echo [ВНИМАНИЕ] Python не найден ни как 'py', ни как 'python'!
echo Установите Python с официального сайта и добавьте его в PATH.
pause
exit /b

:use_py
set PYTHON_CMD=py
echo Найдена команда 'py'.
goto create_venv

:use_python
set PYTHON_CMD=python
echo Найдена команда 'python'.
goto create_venv

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
echo Теперь вы можете запускать run.bat
echo =========================================
pause