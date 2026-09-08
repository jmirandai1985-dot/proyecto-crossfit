#!/bin/sh
# entrypoint.render.sh — arranca nginx (servir build React) y uvicorn (backend)
# dentro del MISMO contenedor. nginx proxya /api/ y /static/ a 127.0.0.1:8000.
set -e

# Valida la config de nginx antes de arrancar (falla temprano si hay error).
nginx -t

# Arranca nginx en segundo plano (sirve el build estático de React).
nginx -g "daemon off;" &

# uvicorn en primer plano → se convierte en PID 1 del contenedor.
# (host 127.0.0.1: nginx lo alcanza en el mismo contenedor; no se expone 8000.)
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
