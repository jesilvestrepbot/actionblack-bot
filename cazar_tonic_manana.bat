@echo off
rem Caza el TONIC de manana (miercoles 22) en la franja 6-7am.
rem Espera a que canceles la SAVAGE 15:15 y luego busca cupo cada 5 min.
rem Uso puntual para esta noche; se puede borrar despues.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m actionbot cazar --fecha 2026-07-22 --clase TONIC --desde 06:00 --hasta 07:00 --intervalo-min 5
