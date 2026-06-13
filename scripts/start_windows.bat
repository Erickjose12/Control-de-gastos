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

echo Iniciando Finanzas Local...
start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" server.py

endlocal
