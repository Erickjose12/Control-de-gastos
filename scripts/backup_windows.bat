@echo off
setlocal

cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo No encontre el entorno virtual. Corre primero scripts\start_windows.bat
  pause
  exit /b 1
)

echo Respaldando datos de Finanzas Local...
".venv\Scripts\python.exe" scripts\backup.py

if %ERRORLEVEL% NEQ 0 (
  echo El respaldo fallo. Revisa el mensaje de arriba.
  pause
  exit /b 1
)

pause
endlocal
