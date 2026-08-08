@echo off
rem Caza el TONIC del sabado 8-ago 07:10 (esta lleno; se sueltan cupos tras las 10pm).
rem Arranca esta noche a las 22:00 y caza hasta conseguir o hasta que empiece la clase.
rem Uso puntual; se puede borrar despues del sabado.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m actionbot cazar --fecha 2026-08-08 --objetivo TONIC:07:10 --intervalo-min 3
