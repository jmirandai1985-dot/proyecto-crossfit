"""
Start uvicorn with ENVIRONMENT=test contra la rama TEST oficial.

La rama TEST oficial es `ep-crimson-tooth-akhx7q2s` (ver `TEST_BRANCH_IDS` en
`app/core/config.py` y `backend/.env.test`). El guard usa la MISMA clasificación
que el resto de los scripts (`is_test_db_url`), no un id hardcodeado: antes
chequeaba `billowing-violet-acdqud44` (rama retirada) y avisaba "BD NO es TEST"
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

config = importlib.import_module("app.core.config")
db_url = config.settings.DATABASE_URL
is_test = config.is_test_db_url(db_url)
rama = next((b for b in config.TEST_BRANCH_IDS if b in (db_url or "")), None)
host = urllib.parse.urlsplit(db_url or "").hostname or "(URL vacia)"

print("=" * 60)
print("  INICIANDO SERVIDOR FASTAPI - BOX CROSSFIT")
print("=" * 60)
print()
print("  ENVIRONMENT=test")
if is_test:
    print(f"  CONECTADO A BD de TEST ({rama})")
else:
    print("  ALERTA: BD NO es TEST")
    print(f"  host: {host}")
print("  Servidor: http://localhost:8000")
print("  Swagger:  http://localhost:8000/docs")
print("  Presiona CTRL+C para detener")
print()
print("=" * 60)

app = importlib.import_module("app.main")
uvicorn.run(app.app, host="127.0.0.1", port=8000)
