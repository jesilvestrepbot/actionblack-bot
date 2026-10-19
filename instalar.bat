@echo off
rem Paso 1: instala el bot. Doble clic en este archivo.
cd /d "%~dp0"
echo.
echo ===== Instalando el bot de reservas Action Black =====
echo.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo No encontre Python en este computador.
  echo.
  echo 1. Entra a https://www.python.org/downloads/ y descarga Python.
  echo 2. Al instalar, MARCA la casilla "Add python.exe to PATH".
  echo 3. Vuelve a dar doble clic a este archivo.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creando el entorno de Python...
  %PY% -m venv .venv || goto :error
)
echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :error

if not exist ".env" copy /y ".env.example" ".env" >nul
if not exist "config.yaml" copy /y "config.example.yaml" "config.yaml" >nul
if not exist "logs" mkdir logs

if /i "%~1"=="/auto" exit /b 0
echo.
echo Instalacion lista. Ahora se abren dos archivos en el Bloc de notas:
echo   .env         escribe tu correo y contrasena de actionblack.co
echo   config.yaml  escribe tu sede y las clases que quieres cada dia
echo Guarda los dos (Ctrl+G o Ctrl+S) y luego da doble clic a programar.bat
echo.
pause
start notepad ".env"
start notepad "config.yaml"
exit /b 0

:error
echo.
echo Algo fallo en la instalacion. Revisa tu conexion a internet y vuelve a intentar.
pause
exit /b 1
