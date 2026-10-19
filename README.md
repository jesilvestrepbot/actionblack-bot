# actionbot: reservas automaticas en Action Black

Bot de uso personal para reservar clases en actionblack.co. Las reservas de cada clase se habilitan 24 horas antes de que empiece (una clase del martes a las 08:40 abre el lunes a las 08:40) y en las sedes llenas se agotan en minutos. El bot:

- **Reserva en la apertura exacta** las clases de tu horario semanal, con el reloj sincronizado contra el servidor del gimnasio.
- **Caza cupos liberados** cuando una clase ya esta llena: revisa cada pocos minutos y reserva apenas alguien cancela.
- **Deja de cazar 10 minutos antes de la clase** (configurable), para no reservar algo a lo que no alcanzas a llegar.
- **Avisa por correo** cuando reserva o falla (opcional, con Gmail).

## Instalacion

Requiere Python 3.11 o superior. Desde la carpeta del repo:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      (Linux/Mac: .venv/bin/pip)
copy .env.example .env                              (Linux/Mac: cp)
copy config.example.yaml config.yaml
```

- `.env`: tu correo y contrasena de actionblack.co (y la de Gmail si quieres avisos). No se sube a git.
- `config.yaml`: tu sede y tu horario. Tampoco se sube a git; en el repo va `config.example.yaml`.

Prueba que todo funcione:

```
python -m actionbot login-test     credenciales correctas
python -m actionbot sedes          nombre exacto de tu sede para config.yaml
python -m actionbot horarios       horario de la sede, con tus clases marcadas
python -m actionbot plan           que va a reservar el bot y cuando abre cada una
```

Todos los comandos se corren desde la carpeta del repo: ahi busca `config.yaml` y escribe `logs/`.

## Configuracion

```yaml
sede: PepeSierra            # como aparece en "python -m actionbot sedes"
apertura_horas: 24          # cuanto antes de la clase abre la reserva
plan_semanal:               # clase y hora exactas por dia
  lun:
    - { clase: TONIC, hora: "11:00" }
  mar:
    - { clase: SAVAGE, hora: "08:40" }
    - { clase: TONIC, hora: "08:30" }   # opcional: segunda opcion si falla la primera
margen_caza_min: 10         # deja de cazar estos minutos antes de la clase
notificar_email: tu_correo@gmail.com    # opcional
```

Los dias que no aparecen en `plan_semanal` no se reservan. El calendario se consulta en vivo, asi que si el gimnasio corre una clase unos minutos el bot lo nota; si la clase cambia de hora del todo, hay que actualizar el plan.

**Festivos:** el gimnasio usa horario de fin de semana y la clase del plan puede no existir ese dia. El bot simplemente no reserva nada; para el festivo usa `reservar` o `cazar` a mano.

## Comandos

| Comando | Para que |
|---|---|
| `sesion` | Reserva el proximo dia del plan: si su apertura esta cerca, espera al segundo exacto y dispara; si esta lejos, termina. Pensado para una tarea programada. |
| `vigilar` | Igual que `sesion` pero como proceso siempre vivo (para Docker o un servidor). |
| `reservar --fecha 2026-10-21 --hora 08:40 --clase SAVAGE [--esperar]` | Reserva una clase puntual. Con `--esperar` aguarda su apertura. |
| `cazar --fecha 2026-10-21 --objetivo TONIC:06:20 --objetivo SAVAGE:06:30` | Busca cupo liberado en clases llenas, en orden de preferencia, hasta conseguirlo o hasta 10 min antes de la clase. `--intervalo-min` cambia cada cuanto revisa; `--permitir-otra` caza aunque ya tengas otra clase ese dia. |
| `calendario [--clase TONIC]`, `horarios`, `plan`, `reservas` | Consulta. |
| `login-test`, `probar-correo` | Diagnostico. |

## Como dejarlo corriendo

**En Windows (PC personal).** El Programador de tareas lanza `sesion.bat` unos 40 minutos antes de cada apertura del plan (una tarea con un disparador semanal por dia). Ejemplo para un plan con clase el martes a las 08:40, que abre el lunes 08:40:

```powershell
$dir = (Get-Location).Path      # carpeta del repo
$a  = New-ScheduledTaskAction -Execute (Join-Path $dir "sesion.bat") -WorkingDirectory $dir
$tr = @(New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00")   # uno por cada dia del plan
$s  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromHours(3))
Register-ScheduledTask -TaskName "ActionBot-semanal" -Action $a -Trigger $tr -Settings $s -Force
```

Para cazas puntuales conviene lanzar `pythonw.exe -m actionbot cazar ...` (del `.venv`) en una tarea de una sola vez: corre oculto, sin ventana que se pueda cerrar por error. El PC debe estar encendido y sin suspender: si esta dormido a la hora de la apertura, la reserva se pierde.

**En un servidor (siempre encendido).** Ver `DEPLOY.md`: Docker con `vigilar`, o systemd/cron lanzando `sesion` cada 30 minutos.

Registro: `logs/actionbot.log`. Reservas que hizo el bot: `logs/bot_reservas.json`.

## Comportamiento del gimnasio que el bot ya maneja

- **Antes de la apertura** la API responde `INVALID_PARAMETER`. El bot dispara 2 s antes y reintenta cada medio segundo hasta que la ventana abre.
- **Penalizacion por inasistencia** (`USER_PENALIZED_ERROR`): bloquea los primeros 5 minutos de cada apertura. El bot espera esos 5 minutos y reintenta; si la clase ya se lleno, avisa. Para no caer en esto, cancela con tiempo las clases a las que no vas a ir.
- **El listado de "mis reservas" es poco fiable**: a veces dice que tienes N reservas pero no las muestra. Por eso el bot lleva su propio registro y no depende de ese listado.
- **Clases que se cruzan** (`ACTIVITIES_OVERLAPPING`): el gimnasio no deja tener dos clases al mismo tiempo, pero si dos el mismo dia a horas distintas.

## Limitaciones

- El bot no cancela reservas: eso se hace en la app o la pagina del gimnasio.
- Usa la misma API que la pagina web del gimnasio, sin documentacion oficial. Si el gimnasio la cambia, hay que ajustar `actionbot/api.py`.
- Es para uso personal con tu propia cuenta. Revisa los terminos del gimnasio antes de usarlo.
