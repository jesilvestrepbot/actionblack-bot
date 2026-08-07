@echo off
rem Caza la clase del festivo viernes 7-ago: prefiere TONIC 08:15, si no SAVAGE 07:15.
rem Ambas estan llenas; espera cupo liberado (el usuario dice que se sueltan tras las 10pm).
rem Uso puntual; se puede borrar despues del viernes.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m actionbot cazar --fecha 2026-08-07 --objetivo TONIC:08:15 --objetivo SAVAGE:07:15 --intervalo-min 3
