# QR File Share -- container image. See docs/planning/spec-docker.md.
FROM python:3.13-slim

# OS time-zone database: lets TZ / HOST_WINDOWS_TZ switch the zone time limits use
# (app/timezone.py). Without it every zone name silently falls back to UTC.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as an ordinary user, never root. /data is the persistent volume.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data \
 && chown app:app /data
COPY app/ app/
USER app

# Docker-mode settings (spec-docker section 4). Native defaults live in app/config.py.
ENV RUN_MODE=docker \
    TOKEN_STORE=file \
    TOKEN_FILE=/data/google-token.json \
    DB_PATH=/data/file_qr.db \
    GOOGLE_CLIENT_SECRET_FILE=/run/secrets/client_secret \
    OAUTH_REDIRECT_PORT=8766 \
    OAUTH_BIND_ADDRESS=0.0.0.0 \
    OAUTH_OPEN_BROWSER=false

VOLUME ["/data"]
EXPOSE 8000 8766

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# All interfaces *inside* the container, so Docker can forward to it. compose.yaml
# publishes the port on the laptop's 127.0.0.1 only -- nothing on the network can reach it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
