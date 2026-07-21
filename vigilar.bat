@echo off
rem Arranca el vigilante de reservas desde la carpeta del proyecto
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m actionbot vigilar
