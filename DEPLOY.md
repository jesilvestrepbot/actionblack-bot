# Despliegue en un servidor (VPS)

En una VPS el bot no depende de que tu PC este despierto: el servidor esta
siempre encendido, asi que nunca pierde una apertura. Hay dos modelos, elige
segun lo que tenga la VPS. Los dos son validos.

- **Despertar, reservar y cerrar**: systemd timer o cron lanzan `sesion` cada
  30 minutos. Si la proxima apertura del plan esta a menos de 40 minutos, espera
  y dispara; si no, termina en segundos. Sirve para cualquier horario.
- **Demonio siempre vivo**: un proceso `vigilar` que corre 24/7, duerme entre
  aperturas y se reinicia solo. Mas simple en Docker.

Nota de zona horaria: Colombia no tiene horario de verano, asi que
`America/Bogota` es UTC-5 fijo. Los archivos ya fijan `America/Bogota` de forma
explicita, sin depender de la hora del servidor.

## Preparacion (cualquier opcion)

```bash
git clone <repo> /opt/actionbot && cd /opt/actionbot
cp .env.example .env              # ACTION_EMAIL y ACTION_PASSWORD
cp config.example.yaml config.yaml # tu sede y tu plan_semanal
chmod 600 .env
```

El registro de reservas vive en `logs/bot_reservas.json`. Debe persistir entre
reinicios: si se borra, el bot no sabe que dias ya reservo y podria repetir.

## Opcion A: Docker, demonio (lo mas simple)

```bash
docker compose up -d --build
docker compose logs -f            # ver que arranca y decide bien
docker compose run --rm actionbot python -m actionbot login-test
```

`restart: unless-stopped` lo revive tras caidas o reinicios de la VPS.
`logs/` y `config.yaml` van montados, asi que persisten y se editan sin
reconstruir.

## Opcion B: systemd timer + sesion (despertar-reservar-cerrar)

Requiere venv en la VPS:

```bash
cd /opt/actionbot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo useradd -r -s /usr/sbin/nologin actionbot && sudo chown -R actionbot:actionbot /opt/actionbot
sudo cp deploy/actionbot-sesion.service deploy/actionbot-sesion.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now actionbot-sesion.timer
systemctl list-timers actionbot-sesion.timer     # confirma la proxima ejecucion
```

Prueba manual sin esperar al timer: `sudo systemctl start actionbot-sesion.service && journalctl -u actionbot-sesion -f`.

## Opcion C: cron + sesion

```bash
cd /opt/actionbot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
crontab deploy/crontab.example      # ajusta la ruta si no es /opt/actionbot
```

## Opcion D: Docker pero despertar-reservar-cerrar

Si en la VPS solo hay Docker pero quieres el modelo que se cierra, deja que el
cron del host lance un contenedor efimero cada 30 minutos:

```cron
CRON_TZ=America/Bogota
*/30 * * * * cd /opt/actionbot && flock -n /tmp/actionbot.lock docker compose run --rm actionbot python -m actionbot sesion --max-espera-min 40 >> logs/cron.log 2>&1
```

## Verificacion y operacion

- Credenciales: `... login-test` debe decir "Login correcto".
- Que planea: `... plan` y `... horarios`.
- Reservas vigentes: `... reservas` (recuerda que el endpoint del gym a veces
  devuelve la lista vacia; el estado real fiable esta en tu app).
- Logs: `logs/actionbot.log`. Reservas logradas por el bot: `logs/bot_reservas.json`.

## Seguridad

- `.env` con tus credenciales nunca se sube a git (esta en `.gitignore` y
  `.dockerignore`). En la VPS, restringe permisos: `chmod 600 .env`.
- El bot reserva solo con tu cuenta, en tu sede, las clases de tu `config.yaml`.
- Usa **una sola** forma de correrlo a la vez (PC o servidor, no ambos): dos
  copias del bot reservarian lo mismo dos veces.
