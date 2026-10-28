#!/bin/sh
# ============================================================
# docker-entrypoint.sh — contenedor `maintenance` (target del backend/Dockerfile)
#
# Qué problema resuelve (auditoría 2026-10-26, hallazgo B1)
# --------------------------------------------------------
# `cron` NO hereda el entorno del contenedor: arma un entorno mínimo (HOME, LOGNAME,
# PATH, SHELL) desde /etc/cron.d y desde la sesión del usuario. Los jobs corrían con
# `ENVIRONMENT=None` y `DATABASE_URL` vacía ⇒ `app/core/config.py` caía al fail-safe,
# cargaba `.env.test` (DATABASE_URL = localhost:5432) y los 5 pasos de `run_daily`
# fallaban con "Connection refused" TODOS los días, con salida 0 para el sistema
# operativo: 15 corridas fallidas seguidas sin que nadie se enterara.
#
# Solución: volcar el entorno del CONTENEDOR (el que arma `docker compose` con
# `env_file:` + `environment:`) a $CRON_ENV_FILE, y que cada job lo cargue con
# `set -a; . $CRON_ENV_FILE; set +a` (lo hace `maintenance/cron_job.sh`, que es lo
# que invoca el crontab).
#
# Reglas del volcado
# ------------------
#   * `export VAR=<valor citado para shell>` con `shlex.quote`: espacios, comillas,
#     `$` y saltos de línea quedan literales (la app password de Gmail tiene espacios).
#   * permisos 0600 y dueño `boxapp`: el archivo tiene SECRETOS; sólo el usuario de
#     los jobs (y root) puede leerlo.
#   * NUNCA se imprimen valores. Sólo la cantidad de variables y, para las 4 que
#     diagnostican el fallo, "definida/FALTA" (de `DATABASE_URL` ni siquiera eso: su
#     valor incluye la password).
#   * Si falta `ENVIRONMENT` se avisa fuerte: es la causa raíz del falso verde.
#   * Si el volcado falla, el entrypoint NO arranca cron (fallar acá es visible; un
#     cron sin entorno vuelve a fallar en silencio todas las noches).
#
# Uso: no se invoca a mano. Es el ENTRYPOINT de la imagen; el CMD sigue siendo
#      `cron -f -l 2`. Para verificar: `docs/CRON_JOBS_RENDER.md` §"Verificación (B1)".
# ============================================================
set -eu

DESTINO="${CRON_ENV_FILE:-/etc/box-maintenance.env}"
# Mismo intérprete que usan los jobs (sobrescribible sólo para probar el script fuera de la
# imagen; en la imagen siempre es el de /usr/local/bin).
PYTHON="${PYTHON_BIN:-/usr/local/bin/python}"

volcar_entorno() {
    umask 077
    "$PYTHON" - "$DESTINO" <<'PY'
import os
import re
import shlex
import sys

destino = sys.argv[1]

# Variables del shell / del propio runtime: no aportan nada al job y `_` cambia de
# valor entre procesos, así que replicarlas sería ruido.
OMITIR = {"_", "SHLVL", "PWD", "OLDPWD", "PS1", "PS2", "TERM"}

lineas = []
for nombre in sorted(os.environ):
    if nombre in OMITIR or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nombre):
        continue
    lineas.append(f"export {nombre}={shlex.quote(os.environ[nombre])}")

with open(destino, "w", encoding="utf-8") as fh:
    fh.write("# Generado por maintenance/docker-entrypoint.sh — NO editar a mano.\n")
    fh.write("# Entorno del contenedor para los jobs de cron (que NO lo heredan).\n")
    fh.write("\n".join(lineas) + "\n")

print(f"[entrypoint] {len(lineas)} variable(s) exportadas a {destino}")
PY
}

echo "[entrypoint] volcando el entorno del contenedor para cron …"
if ! volcar_entorno; then
    echo "[entrypoint] ❌ no se pudo escribir $DESTINO: cron arrancaría SIN entorno" >&2
    echo "[entrypoint]    (los jobs escribirían en la base equivocada y fallarían en silencio)" >&2
    exit 1
fi
chown boxapp:boxapp "$DESTINO" 2>/dev/null || true
chmod 0600 "$DESTINO"

# Diagnóstico SIN valores: lo que se ve en `docker logs` es justamente lo que faltaba
# cuando el job falló 15 noches seguidas.
if valor_environment=$(printenv ENVIRONMENT 2>/dev/null); then
    echo "[entrypoint] ENVIRONMENT=$valor_environment"
else
    echo "[entrypoint] ⚠️  ENVIRONMENT no está definida: los jobs van a caer al fail-safe" >&2
    echo "[entrypoint]    (.env.test ⇒ localhost:5432) y volver a fallar en silencio (B1)" >&2
fi
for var in DATABASE_URL MAINT_DB_URL BACKEND_URL DRY_RUN; do
    if printenv "$var" >/dev/null 2>&1; then
        echo "[entrypoint] $var: definida"
    else
        echo "[entrypoint] $var: FALTA"
    fi
done

# CMD por defecto de la imagen (`cron -f -l 2`), por si se corre sin argumentos.
if [ "$#" -eq 0 ]; then
    set -- cron -f -l 2
fi

exec "$@"
