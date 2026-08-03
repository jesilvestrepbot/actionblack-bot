@echo off
rem Una sesion de reserva: reserva el proximo dia sin cubrir y se cierra sola.
rem La lanza la tarea programada unos 40 min antes de cada apertura; el limite
rem de 90 min cubre la espera hasta la apertura mas un margen por si el gym
rem mueve el horario unos minutos.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m actionbot sesion --max-espera-min 90
