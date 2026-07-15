@echo off
rem Arranque silencioso del servidor real (puerto 8765) para usar con el Programador
rem de tareas de Windows. No instala dependencias ni abre el navegador: se asume que
rem ya corriste start_windows.bat al menos una vez para crear el entorno virtual.

cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  exit /b 1
)

".venv\Scripts\python.exe" server.py
