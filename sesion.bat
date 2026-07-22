@echo off
rem Una sesion de reserva: reserva el proximo dia sin cubrir y se cierra sola.
rem Se lanza desde la tarea diaria a las 05:45. El limite de 200 min cubre
rem la apertura mas tardia (sabado, que abre ~08:20).
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m actionbot sesion --max-espera-min 200
