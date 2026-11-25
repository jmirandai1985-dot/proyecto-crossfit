"""
Start uvicorn con ENVIRONMENT=test.

Base de datos:
  * por defecto, la rama TEST oficial de Neon (`backend/.env.test`; ver
    `TEST_BRANCH_IDS` en `app/core/config.py`).
  * si existe `backend/.env.local` (ignorado por git), ese archivo PISA la
    conexión y el servidor usa el Postgres LOCAL de `docker-compose.local.yml`
    (no gasta cuota de Neon).

El guard usa la MISMA clasificación que el resto de los scripts
(`is_test_db_url`), no un id hardcodeado: antes chequeaba
`billowing-violet-acdqud44` (rama retirada) y avisaba "BD NO es TEST"
aunque el servidor estuviera apuntado a TEST.
"""
import uvicorn
import os
import sys
import importlib
import urllib.parse

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

os.environ["ENVIRONMENT"] = "test"

# ── Base LOCAL de Docker (opcional) ─────────────────────────────────────────
# `backend/.env.local` (ignorado por git) permite apuntar SOLO este servidor de
# desarrollo al Postgres de `docker-compose.local.yml` sin gastar la rama TEST de
# Neon. Se carga ANTES de importar `app.core.config` y con `override=True`: las
# variables de entorno GANAN sobre el `env_file` de Pydantic (`.env.test`), que
# sigue aportando el resto de la configuración (JWT, SMTP, etc.). Sin el archivo,
# nada cambia: se usa `.env.test` como siempre.
ENV_LOCAL = os.path.join(BACKEND_DIR, ".env.local")
USA_ENV_LOCAL = os.path.isfile(ENV_LOCAL)
if USA_ENV_LOCAL:
    from dotenv import load_dotenv
    load_dotenv(ENV_LOCAL, override=True)

config = importlib.import_module("app.core.config")
db_url = config.settings.DATABASE_URL
is_test = config.is_test_db_url(db_url)
rama = next((b for b in config.TEST_BRANCH_IDS if b in (db_url or "")), None)
partes = urllib.parse.urlsplit(db_url or "")
host = partes.hostname or "(URL vacia)"
base = (partes.path or "").strip("/") or "(sin base)"
# Postgres de docker-compose.local.yml (publicado en loopback). Para el guard de
# `config.py` un host desconocido no aborta; acá sólo se informa sin credenciales.
es_local = host in ("127.0.0.1", "localhost") and base == "urban_training_dev"

print("=" * 60)
print("  INICIANDO SERVIDOR FASTAPI - BOX CROSSFIT")
print("=" * 60)
print()
print("  ENVIRONMENT=test")
if es_local:
    print(f"  CONECTADO A BD LOCAL de Docker (host={host} | base={base})")
elif is_test:
    print(f"  CONECTADO A BD de TEST ({rama})")
else:
    print("  ALERTA: BD NO es TEST")
    print(f"  host={host} | base={base}")
print(f"  .env.local: {'SI' if USA_ENV_LOCAL else 'no'}")
print("  Servidor: http://localhost:8000")
print("  Swagger:  http://localhost:8000/docs")
print("  Presiona CTRL+C para detener")
print()
print("=" * 60)

app = importlib.import_module("app.main")
uvicorn.run(app.app, host="127.0.0.1", port=8000)
