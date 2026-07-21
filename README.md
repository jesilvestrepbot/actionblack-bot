# actionbot: reservas automaticas en Action Black

Bot de uso personal que reserva clases en actionblack.co en el momento exacto en que se abre el cupo. Las reservas se habilitan un numero fijo de horas antes del inicio de la clase (24 por defecto): si la clase es manana a las 6:15 am, el cupo se abre hoy a las 6:15 am y las clases populares se llenan en minutos. El bot vigila el calendario, espera la apertura con el reloj sincronizado contra el servidor y dispara la reserva con reintentos.

## Como funciona

El sitio de reservas es una app Next.js que habla con una API propia. El bot usa los mismos endpoints que usa la pagina, sin navegador:

| Paso | Endpoint | Auth |
|---|---|---|
| Catalogo de sedes | `GET https://action-cloud.com/v1/branches` | token publico del sitio |
| Calendario semanal | `GET https://prod.action-exp-api.com/api/v1/activities/generic` | ninguna |
| Login | `POST https://prod.action-exp-api.com/api/v1/auth/login` | email y password |
| Reservar | `POST https://prod.action-exp-api.com/api/v1/activities/booking` | Bearer JWT del login |
| Mis reservas | `GET https://prod.action-exp-api.com/api/v1/activities/bookings` | Bearer JWT del login |

Cuerpo de la reserva (el mismo que arma el sitio al pulsar RESERVAR):

```json
{
  "activity_id": "uuid de la clase",
  "activ_config_id": 12345,
  "activity_date": "2026-07-22",
  "token_branch": "token EVO de la sede",
  "activity_start": "06:15",
  "timezone": "America/Bogota"
}
```

Estados de una clase en el calendario: `Available`, `Finalized`, `Canceled`. Codigos de error relevantes de la API: `ACTIVITIES_OVERLAPPING` (ya tienes otra clase a esa hora), `ACTIVITIES_SCHEDULE_VALIDATION_ERROR` (la ventana aun no abre, se reintenta), `USER_BLOCKED_ERROR`, `BOOKING_ERROR`.

## Instalacion

Requiere Python 3.11 o superior.

```
cd "C:\Users\jesil\OneDrive\Documentos\Claude\Code\ActionBlack"
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edita `.env` con tu correo y contrasena de actionblack.co. Ese archivo queda fuera de git.

## Configuracion

Todo se define en `config.yaml`: la sede, las clases objetivo (SAVAGE y TONIC por defecto), los dias, la franja u horas exactas, y los parametros del disparo. El archivo esta comentado. Para ver que reservaria el bot con la configuracion actual:

```
.venv\Scripts\python -m actionbot plan
```

## Comandos

```
python -m actionbot sedes                  lista de sedes
python -m actionbot calendario             calendario de la sede, --clase SAVAGE para filtrar
python -m actionbot plan                   objetivos detectados y hora de apertura de cada uno
python -m actionbot login-test             prueba las credenciales del .env
python -m actionbot reservas               tus reservas vigentes
python -m actionbot reservar --fecha 2026-07-22 --hora 06:15 --clase SAVAGE [--esperar]
python -m actionbot vigilar [--una-vez]    proceso continuo que reserva solo
```

`reservar --esperar` espera hasta la apertura de esa clase y dispara a la hora exacta. Sin `--esperar` intenta de inmediato durante 30 segundos.

`vigilar` es el modo normal: consulta el calendario, calcula la proxima apertura, duerme hasta 2 minutos antes, inicia sesion, sincroniza el reloj contra el servidor, espera al segundo exacto y dispara la reserva con reintentos cada medio segundo. El resultado queda en `logs/actionbot.log` y en `logs/estado.json`, y si configuras `notificar_url` llega un aviso al celular.

## Dejarlo corriendo en Windows

`vigilar.bat` arranca el vigilante desde la carpeta del proyecto. Para que se inicie solo al iniciar sesion en Windows:

```
schtasks /create /tn "ActionBot" /tr "\"C:\Users\jesil\OneDrive\Documentos\Claude\Code\ActionBlack\vigilar.bat\"" /sc onlogon
```

Notas:

- El equipo tiene que estar encendido y sin suspender a la hora de la apertura. Si el PC duerme, el bot no dispara. Revisa las opciones de energia o programa la tarea con "despertar el equipo para ejecutarla" desde el Programador de tareas.
- El bot procesa una apertura a la vez. Si dos objetivos abren casi al mismo tiempo, acorta la rafaga del primero para llegar al segundo.
- SAVAGE y TONIC de la manana suelen cruzarse en horario. Si el bot logra la primera, la segunda fallara con `ACTIVITIES_OVERLAPPING`. Deja en `config.yaml` solo lo que de verdad quieras tomar cada dia.

## Limitaciones y avisos

- Uso personal: el bot reserva con tu cuenta, en tu sede, las clases que tu configuras. Los reintentos estan acotados (2 por segundo durante unos minutos) para no golpear la API.
- El endpoint de reserva se mapeo del codigo del sitio pero solo se puede validar con una cuenta real. La primera vez ejecuta un `reservar --esperar` vigilado y revisa el log.
- La cancelacion no esta implementada: cancelar desde la pagina o la app del gimnasio.
- Si el gimnasio cambia su web o su API, toca actualizar `actionbot/api.py`.
