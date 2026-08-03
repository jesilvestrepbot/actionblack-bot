# actionbot: reservas automaticas en Action Black

Bot de uso personal que consigue una clase por dia en actionblack.co. Las reservas se habilitan un numero fijo de horas antes del inicio de la clase (24 por defecto): si la clase es manana a las 6:25 am, el cupo se abre hoy a las 6:25 am y en sedes llenas se agota en minutos. El bot dispara a la hora exacta de apertura con el reloj sincronizado contra el servidor, y si no lo logra sigue buscando cupos liberados cada 15 minutos, de dia y de noche.

## Que hace

- Una clase por dia, los 7 dias, recorriendo las clases en orden de prioridad (por defecto SAVAGE y si no se puede TONIC) dentro de una franja horaria.
- Dos franjas: entre semana (06:00 a 07:00) y fines de semana o festivos (07:00 a 09:00), porque el gimnasio publica horarios distintos. Los festivos salen de la lista `festivos` del config y ademas se autodetectan: si un dia entre semana no tiene clases del plan en la franja normal, el bot asume horario de festivo.
- El calendario se consulta en vivo en cada ciclo, asi que el horario de la semana siguiente se recoge solo, sin pasos manuales el domingo.
- Dispara la reserva del candidato principal en el segundo exacto de la apertura, con rafaga de reintentos. Si falla, intenta los fallbacks del dia.
- Si el dia queda sin clase (todo lleno), entra en rescate: revisa el calendario cada 15 minutos, de dia y de noche, y toma cualquier cupo que se libere hasta la hora de inicio de la clase.
- Si el gimnasio cancela una reserva que el bot habia logrado, lo detecta y vuelve a buscar clase para ese dia.
- Si el dia ya tiene una reserva tuya hecha a mano (desde la app), no toca nada.
- Puede avisar al celular con `notificar_url` (por ejemplo un topic de ntfy.sh).

Tiempos medidos en vivo (2026-07-21): el POST de reserva responde en menos de 2 segundos. En el daemon, el calendario y el login se resuelven antes de la ventana, asi que en el segundo de la apertura solo corre ese POST. El comando manual `reservar` completo, con calendario y login incluidos, tomo 17.6 segundos.

## Como funciona por dentro

El sitio de reservas es una app Next.js que habla con una API propia. El bot usa los mismos endpoints que usa la pagina, sin navegador:

| Paso | Endpoint | Auth |
|---|---|---|
| Catalogo de sedes | `GET https://action-cloud.com/v1/branches` | token publico del sitio |
| Calendario semanal | `GET https://prod.action-exp-api.com/api/v1/activities/generic` | ninguna |
| Login | `POST https://prod.action-exp-api.com/api/v1/auth/login` | email y password |
| Perfil (partner_user_id, membresia) | `GET https://prod.action-exp-api.com/api/v1/users` | Bearer JWT |
| Reservar | `POST https://prod.action-exp-api.com/api/v1/activities/booking` | Bearer JWT |
| Mis reservas | `GET https://prod.action-exp-api.com/api/v1/activities/bookings` | Bearer JWT |

Cuerpo de la reserva (el mismo que arma el sitio al pulsar RESERVAR, todos los campos son obligatorios):

```json
{
  "activity_id": "uuid de la clase",
  "activ_config_id": 12345,
  "activity_date": "2026-07-22",
  "token_branch": "token EVO de la sede",
  "activity_start": "06:25",
  "timezone": "America/Bogota",
  "activity_name": "SAVAGE",
  "capacity": 16,
  "branch_name": "PepeSierra",
  "branch_id": "30",
  "partner_name": "EVO",
  "country_code": "CO",
  "booking_origin": "WEB"
}
```

Detalles aprendidos del sistema:

- Estados de una clase: `Available`, `Full`, `Finalized`, `Canceled`. Las clases pueden pasar a `Finalized` estando en el futuro (deja de ser reservable) y el gimnasio cancela clases con frecuencia.
- El `activity_id` NO es unico por instancia: se repite entre dias y semanas. Siempre se combina con fecha y hora (`clave()` en scheduler.py).
- La respuesta de mis reservas trae `spot_number` y `group_name`. A veces responde `total_items > 0` con `items` vacios; por eso el bot guarda su propio registro en `logs/bot_reservas.json` como respaldo.
- Errores relevantes: `ACTIVITIES_OVERLAPPING` (ya tienes clase en ese horario, definitivo), `MISSING_PARAMETER` (falta un campo del payload, definitivo), `USER_BLOCKED_ERROR` (cuenta bloqueada). `INVALID_PARAMETER` NO es definitivo: la API lo devuelve cuando intentas reservar antes de que abra la ventana de 24 h (validado 2026-07-21 con el mismo payload que si funciona dentro de la ventana). Por eso se reintenta hasta que la ventana abre. Este es el mecanismo que hace posible disparar en el segundo exacto: el bot empieza unos segundos antes, recibe `INVALID_PARAMETER`, e insiste cada medio segundo hasta que entra.

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

`config.yaml`, comentado. Lo esencial:

```yaml
sede: PepeSierra
apertura_horas: 24
plan_semanal:
  mie:
    - { clase: TONIC, hora: "12:10" }
  jue:
    - { clase: SAVAGE, hora: "09:55" }
  vie:
    - { clase: TONIC, hora: "06:15" }
rescate:
  activo: true
  intervalo_min: 15
```

`plan_semanal` define la clase y hora exactas por dia de la semana. Los dias que no aparezcan no se reservan. Puedes poner varias opciones por dia (lista) y se intentan en orden de preferencia hasta lograr una. La apertura de cada clase es 24 h antes, a la misma hora: TONIC del miercoles 12:10 abre el martes 12:10, asi que la tarea programada dispara poco antes de cada apertura (no a una hora fija). Si el gimnasio mueve una clase unos minutos, `sesion` espera hasta la apertura real dentro de su margen.

## Comandos

```
python -m actionbot sedes                  lista de sedes
python -m actionbot calendario             calendario de la sede, --clase SAVAGE para filtrar
python -m actionbot horarios               mapa semanal por clase y aperturas del plan
python -m actionbot plan                   que reservaria el bot cada dia y a que hora abre
python -m actionbot login-test             prueba las credenciales del .env
python -m actionbot reservas               tus reservas vigentes
python -m actionbot reservar --fecha 2026-07-23 --hora 06:15 --clase SAVAGE [--esperar]
python -m actionbot sesion                 reserva el proximo dia sin cubrir y se cierra (tarea diaria)
python -m actionbot cazar --fecha F --clase C [--desde HH:MM --hasta HH:MM]   caza un cupo puntual
python -m actionbot vigilar [--una-vez]    modo demonio 24/7 (alternativa, ya no es el recomendado)
```

## Como corre: tareas que se despiertan, reservan y se cierran

El bot NO corre 24/7. Se despierta cerca de la hora de apertura, hace la reserva, y se apaga. Task Scheduler de Windows es quien lo despierta.

### Reserva diaria

`sesion.bat` reserva el proximo dia sin cubrir y se cierra. Busca la apertura mas cercana; si esta cerca espera al segundo exacto y reserva con prioridad y fallbacks, y si esta lejos se cierra para que la tarea lo relance. Tarea que lo lanza cada dia a las 05:45 (cubre aperturas de 06:15 entre semana hasta 08:20 el sabado):

```powershell
$dir = "C:\Users\jesil\OneDrive\Documentos\Claude\Code\ActionBlack"
$a = New-ScheduledTaskAction -Execute (Join-Path $dir "sesion.bat") -WorkingDirectory $dir
$tr = New-ScheduledTaskTrigger -Daily -At "05:45"
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromHours(4))
Register-ScheduledTask -TaskName "ActionBot-diario" -Action $a -Trigger $tr -Settings $s -Force
```

### Reserva especial puntual

Para cazar una clase concreta que ya esta llena (esperar una cancelacion), `cazar` corre en bucle hasta conseguir cupo o hasta que empiece la clase, y se cierra. Se lanza con una tarea de una sola vez (`New-ScheduledTaskTrigger -Once -At <hora>`) apuntando a un .bat con el comando `cazar` de esa fecha/clase (ver `cazar_tonic_manana.bat` como ejemplo).

Notas:

- El equipo debe estar encendido y sin suspender a la hora de la tarea. Si duerme a las 05:45, Task Scheduler la ejecuta al despertar (`StartWhenAvailable`), pero si sigue dormido a la hora de la apertura se pierde. Manten el PC despierto en esa franja.
- Los disparadores `-AtLogOn` y las opciones de reinicio automatico piden permisos de administrador; por eso se usa `-Daily`, que no los necesita.
- Los lunes no hay TONIC en la franja 06:00 a 07:00 en PepeSierra, ese dia solo se intenta SAVAGE.
- El log queda en `logs/actionbot.log` y el registro de reservas del bot en `logs/bot_reservas.json`.

## Limitaciones y avisos

- Uso personal: reserva con tu cuenta, en tu sede, lo que tu configuras. Los reintentos estan acotados para no golpear la API.
- La cancelacion no esta implementada: cancelar desde la pagina o la app del gimnasio.
- Si el gimnasio cambia su web o su API, toca actualizar `actionbot/api.py`.
