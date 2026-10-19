# actionbot: reservas automaticas en Action Black

Bot de uso personal para reservar clases en actionblack.co. Las reservas de cada clase se habilitan 24 horas antes de que empiece (una clase del martes a las 08:40 abre el lunes a las 08:40) y en las sedes llenas se agotan en minutos. El bot:

- **Reserva en la apertura exacta** las clases de tu horario semanal, con el reloj sincronizado contra el servidor del gimnasio.
- **Caza cupos liberados** cuando una clase ya esta llena: revisa cada pocos minutos y reserva apenas alguien cancela.
- **Deja de cazar 10 minutos antes de la clase** (configurable), para no reservar algo a lo que no alcanzas a llegar.
- **Avisa por correo** cuando reserva o falla (opcional, con Gmail).

## Para empezar (paso a paso, sin saber programar)

Necesitas un computador con **Windows** que quede **encendido** a las horas en que abren tus reservas (normalmente en la manana). Si el computador esta apagado o suspendido a esa hora, esa reserva se pierde.

**1. Instala Python (una sola vez).**
Entra a https://www.python.org/downloads/ y descarga el instalador. Al abrirlo, **marca la casilla "Add python.exe to PATH"** (abajo en la primera pantalla) y dale "Install Now".

**2. Descarga el bot.**
En la pagina de este repositorio, boton verde **Code** y luego **Download ZIP**. Descomprime el ZIP en una carpeta fija, por ejemplo `Documentos\actionbot` (no lo dejes en Descargas, el bot debe quedarse en esa carpeta).

**3. Instala.**
Dentro de la carpeta, doble clic en **`instalar.bat`**. Si Windows muestra "Windows protegio su PC", dale "Mas informacion" y "Ejecutar de todas formas". Al terminar se abren dos archivos en el Bloc de notas:

- **`.env`**: cambia `tu_correo@ejemplo.com` y `tu_contrasena` por el correo y la contrasena con los que entras a actionblack.co. Guarda.
- **`config.yaml`**: pon tu sede y tus clases (ver el ejemplo de abajo). Guarda.

**4. Programa el bot.**
Doble clic en **`programar.bat`**. Revisa que diga "Login correcto", que liste las clases que quieres y que termine con "Listo". Desde ahi el bot trabaja solo, todas las semanas.

**Si cambias tu horario**, edita `config.yaml` y vuelve a dar doble clic a `programar.bat`.

### Como llenar config.yaml

Solo hay que cambiar dos cosas:

```yaml
sede: PepeSierra                    # el nombre de tu sede, sin espacios
plan_semanal:
  lun:
    - { clase: TONIC, hora: "11:00" }
  mar:
    - { clase: SAVAGE, hora: "08:40" }
  sab:
    - { clase: TONIC, hora: "07:10" }
```

- **Dias**: `lun`, `mar`, `mie`, `jue`, `vie`, `sab`, `dom`. Borra los dias en que no vas.
- **Clase y hora**: exactamente como aparecen en la pagina de reservas, en formato de 24 horas (`18:20`, no `6:20 pm`). La hora va entre comillas.
- Respeta los espacios al inicio de cada linea: la clase va con 4 espacios y un guion.
- Si no sabes el nombre exacto de tu sede o las horas de las clases, abre una ventana de comandos en la carpeta (en la barra de direcciones del explorador escribe `cmd` y Enter) y escribe `.venv\Scripts\python -m actionbot sedes` o `.venv\Scripts\python -m actionbot horarios`.

### Cosas importantes

- **Cancela a tiempo** en la app las clases a las que no vas a ir. Si no, el gimnasio te penaliza y durante un tiempo te bloquea los primeros 5 minutos de cada reserva, que es cuando se llenan.
- El bot no cancela nada: eso lo haces tu en la app.
- Para ver que hizo el bot, abre `logs\actionbot.log` con el Bloc de notas.

---

## Instalacion manual

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
| `programar [--ver]` | Crea la tarea de Windows para tu plan semanal. |
| `login-test`, `probar-correo` | Diagnostico. |

## Como dejarlo corriendo

**En Windows (PC personal).** `python -m actionbot programar` (o doble clic en `programar.bat`) lee el `plan_semanal`, calcula a que hora abre cada clase y crea la tarea `ActionBot-semanal` del Programador de tareas, que despierta el bot unos 40 minutos antes de cada apertura y corre oculto. `programar --ver` muestra los horarios sin crear nada.

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
