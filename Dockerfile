# Imagen para correr el bot de reservas Action Black en una VPS.
FROM python:3.12-slim

# Zona horaria: Colombia no tiene horario de verano, asi que America/Bogota
# es estable (UTC-5 todo el ano). Deja logs y cron en hora local.
ENV TZ=America/Bogota \
    PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY actionbot ./actionbot
COPY config.yaml ./config.yaml

# logs/ (con bot_reservas.json) se monta como volumen para que persista.
RUN mkdir -p /app/logs

# Por defecto: demonio siempre vivo. En una VPS es simple y robusto.
# Para el modelo "despertar, reservar y cerrar" usa cron o systemd
# lanzando: python -m actionbot sesion --max-espera-min 200  (ver DEPLOY.md)
CMD ["python", "-m", "actionbot", "vigilar"]
