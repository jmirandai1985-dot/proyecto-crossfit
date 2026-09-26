# syntax=docker/dockerfile:1
# ============================================================
# BACKEND — Box CrossFit Platform API
# La BD vive en Neon (cloud, externa): este contenedor NO incluye Postgres.
#
# Dos targets de build:
#   prod        (default) — uvicorn en :8000 SIN --reload.
#   maintenance — cron interno con los scripts de mantenimiento
#                 (agrega postgresql-client para pg_dump real, no el .exe).
# ============================================================

# ---- Stage 1: dependencias Python (capa cacheable) ----
FROM python:3.12-slim AS deps

# psycopg2-binary ya es wheel: NO se agregan compiladores ni build-essential.
# Solo CA certs (TLS a Neon/SMTP/Sentry) y tzdata (ZoneInfo America/Santiago).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Solo requirements primero: la capa de pip se cachea hasta que cambie.
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: base (runtime) ----
FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/America/Santiago /etc/localtime \
    && echo "America/Santiago" > /etc/timezone

ENV TZ=America/Santiago \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencias desde la stage deps (evita re-instalar en cada build).
# Se copian TANTO site-packages como /usr/local/bin: pip instala los
# ejecutables (uvicorn, alembic, ...) en /usr/local/bin, NO en site-packages.
# Sin esta segunda copia el CMD "uvicorn ..." falla con "executable file not
# found in $PATH" (verificado 21/08/2026 al levantar el stack de Fase 1.4).
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Código de la app + modelos de ML + migraciones + scripts de mantenimiento.
COPY app/ app/
COPY ml/ ml/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY requirements.txt ./
COPY maintenance/ maintenance/

# Directorios de datos en runtime (los volúmenes se declaran en compose,
# no se bakean en la imagen).
RUN mkdir -p /app/app/static/uploads /app/app/private_uploads /app/logs

# Usuario no-root (buena práctica).
RUN useradd --create-home --uid 1000 boxapp \
    && chown -R boxapp:boxapp /app

EXPOSE 8000

# ---- Stage 3: backend (default) ----
FROM base AS prod
USER boxapp
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- Stage 4: contenedor de mantenimiento (cron) ----
FROM base AS maintenance
USER root
# cron + cliente PostgreSQL de la MISMA major que el servidor de Neon.
# Neon corre PostgreSQL 18.x y `pg_dump` ABORTA si el cliente es de una major menor
# ("pg_dump: error: aborting because of server version mismatch / server version: 18.6;
# pg_dump version: 17.11"), que es exactamente por lo que los backups no se generaban.
# Debian 13 (trixie) trae el cliente 17, y Neon corre PostgreSQL 18.6, así que se instala
# el cliente 18 desde el repo oficial de PGDG (`trixie-pgdg`) y se VERIFICA en el build:
# si algún día la base cambia de codename o PGDG de major, el build falla acá en vez de
# fallar en silencio en el cron de las 02:30 (que es lo que venía pasando desde el 24/09).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl cron \
    && grep -q '^VERSION_CODENAME=trixie' /etc/os-release \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/* \
    && pg_dump --version \
    && pg_dump --version | grep -q " 18\." \
    && mkdir -p /app/backups \
    && chown -R boxapp:boxapp /app
COPY maintenance/crontab /etc/cron.d/box-maintenance
RUN chmod 0644 /etc/cron.d/box-maintenance
# cron corre como root (Debian lo exige); los jobs se ejecutan como boxapp
# vía la columna de usuario del crontab (/etc/cron.d/box-maintenance).
# Los jobs escriben en /app/logs (volumen) y /app/backups (volumen).
CMD ["cron", "-f", "-l", "2"]
