"""
Start uvicorn with ENVIRONMENT=test (muddy-term BD).
Uses importlib to ensure ENV is set BEFORE any app import.
"""
import uvicorn
import os
import sys
import importlib

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

os.environ["ENVIRONMENT"] = "test"

config = importlib.import_module("app.core.config")
db_url = config.settings.DATABASE_URL
is_test = "muddy" in db_url

print("=" * 60)
print("  INICIANDO SERVIDOR FASTAPI - BOX CROSSFIT")
print("=" * 60)
print()
print("  ENVIRONMENT=test")
if is_test:
    print("  CONECTADO A BD de TEST (muddy-term)")
else:
    print("  ALERTA: BD NO es TEST")
    print(f"  URL: {db_url[:50]}...")
print("  Servidor: http://localhost:8000")
print("  Swagger:  http://localhost:8000/docs")
print("  Presiona CTRL+C para detener")
print()
print("=" * 60)

app = importlib.import_module("app.main")
uvicorn.run(app.app, host="127.0.0.1", port=8000)
