@echo off
setlocal

cd /d "%~dp0\.."

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set PY=py -3
) else (
  where python >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    set PY=python
  ) else (
    echo No encontre Python. Instala Python 3.10 o superior desde https://www.python.org/downloads/
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual...
  %PY% -m venv .venv
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt

echo Preparando base demo...
if exist "data_demo\finanzas.db" del /q "data_demo\finanzas.db"
if exist "data_demo\wedding_files" rmdir /s /q "data_demo\wedding_files"
if exist "data_demo\house_files" rmdir /s /q "data_demo\house_files"
if exist "data_demo\transaction_files" rmdir /s /q "data_demo\transaction_files"

set "FINANZAS_DEMO=1"
set "FINANZAS_DATA_DIR=%CD%\data_demo"

echo Iniciando Finanzas Local DEMO...
echo Datos demo en: %FINANZAS_DATA_DIR%
start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" server.py

endlocal
