#!/bin/sh
# ============================================================
# cron_job.sh — wrapper de TODOS los jobs del crontab del contenedor `maintenance`.
#
# Por qué existe (auditoría 2026-10-26, hallazgo B1)
# -----------------------------------------------
# cron NO hereda el entorno del contenedor, así que el job corría sin `ENVIRONMENT` ni
# `DATABASE_URL` (ver `docker-entrypoint.sh`). Este wrapper:
#
#   1. carga el snapshot que dejó el entrypoint (`/etc/box-maintenance.env`, 0600 boxapp),
#   2. se ubica en /app (cron arranca en el HOME del usuario, y los `python -m
#      maintenance.*` resuelven el paquete desde el working directory),
#   3. ejecuta `python -m <módulo>` con el MISMO intérprete de la imagen.
#
# Uso (lo pone el crontab, no se escribe a mano):
#   /app/maintenance/cron_job.sh maintenance.run_daily
#   /app/maintenance/cron_job.sh maintenance.run_monthly
# ============================================================
set -eu

ARCHIVO="${CRON_ENV_FILE:-/etc/box-maintenance.env}"
PYTHON="${PYTHON_BIN:-/usr/local/bin/python}"

if [ -r "$ARCHIVO" ]; then
    # `set -a` ⇒ lo que se lea acá queda exportado a `python -m`.
    set -a
    # shellcheck disable=SC1090  # el archivo es dinámico a propósito
    . "$ARCHIVO"
    set +a
else
    # Sin el archivo el job vuelve al fallo silencioso de antes: decirlo y seguir (el
    # log del job es lo que después permite distinguir "no había entorno" de un bug).
    echo "[cron_job] ⚠️  no existe $ARCHIVO: el job corre SIN el entorno del contenedor" >&2
    echo "[cron_job]    (¿se saltó el entrypoint de la imagen? ver auditoría B1)" >&2
fi

# cron arranca en el HOME del usuario, y `python -m maintenance.<x>` resuelve el paquete
# desde el working directory.
if [ -d "${APP_DIR:-/app}" ]; then
    cd "${APP_DIR:-/app}"
fi

# Sin argumentos: lista los módulos disponibles y sale con error (evita un no-op verde).
if [ "$#" -eq 0 ]; then
    echo "[cron_job] falta el módulo: uso cron_job.sh maintenance.<script>" >&2
    exit 64
fi

exec "$PYTHON" -m "$@"
