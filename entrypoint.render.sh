#!/bin/sh
# entrypoint.render.sh — arranca nginx (servir build React) y uvicorn (backend)
# dentro del MISMO contenedor. nginx proxya /api/, /static/ y /health a
# http://127.0.0.1:8000. nginx escucha en $PORT (Render lo inyecta, default 10000;
# en pruebas locales sin la variable cae a 80).
set -e

# ── Puerto de escucha de nginx ──
# nginx no lee variables de entorno nativas → se genera la config desde el template
# con sed, reemplazando el placeholder __PORT__ por el valor de $PORT.
PORT="${PORT:-80}"
sed "s/__PORT__/${PORT}/g" /etc/nginx/conf.d/default.conf.template | tr -d '\r' > /etc/nginx/conf.d/default.conf

# Valida la config generada antes de arrancar (falla temprano si hay error).
nginx -t

# Arranca nginx en segundo plano (sirve el build estático de React).
nginx -g "daemon off;" &

# uvicorn en primer plano → se convierte en PID 1 del contenedor.
# (host 127.0.0.1: nginx lo alcanza en el mismo contenedor; no se expone 8000.)
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
