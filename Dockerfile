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
# config por defecto; docker-compose monta tu config.yaml encima
COPY config.example.yaml ./config.yaml

# logs/ (con bot_reservas.json) se monta como volumen para que persista.
RUN mkdir -p /app/logs

# Demonio siempre vivo: calcula cada apertura del plan y dispara a tiempo.
CMD ["python", "-m", "actionbot", "vigilar"]
