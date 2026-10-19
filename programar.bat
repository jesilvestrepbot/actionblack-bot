@echo off
rem Paso 2: prueba tu cuenta y deja el bot programado. Doble clic en este archivo.
rem Si cambias tu horario en config.yaml, vuelve a darle doble clic.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero da doble clic a instalar.bat
  pause
  exit /b 1
)
set "PY=.venv\Scripts\python.exe"

echo.
echo ===== 1. Probando tu cuenta de Action Black =====
%PY% -m actionbot login-test || goto :login

echo.
echo ===== 2. Clases que va a reservar el bot =====
%PY% -m actionbot plan || goto :config

echo.
echo ===== 3. Programando el bot en Windows =====
%PY% -m actionbot programar || goto :error

echo.
echo Todo listo. El bot reserva solo cada clase apenas se abre el cupo.
echo Puedes cerrar esta ventana.
pause
exit /b 0

:login
echo.
echo No pude entrar a tu cuenta. Revisa el correo y la contrasena en el archivo .env
pause
exit /b 1
:config
echo.
echo Revisa config.yaml: la sede o el horario tienen un error.
pause
exit /b 1
:error
echo.
echo No pude crear la tarea programada. Toma una foto de esta ventana y enviasela a quien te compartio el bot.
pause
exit /b 1
