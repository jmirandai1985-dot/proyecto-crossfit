"""Solo lectura: conteos de LOAD_TEST_BOX (verificación de seed)."""
import json
import os
from sqlalchemy import create_engine, text
from app.core.config import settings

K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))
with open(os.path.join(K6_DIR, "load_config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
TENANT = cfg["tenant_id"]

e = create_engine(settings.DATABASE_URL)
c = e.connect()
checks = [
    ("tenants", "SELECT COUNT(*) FROM tenants WHERE id=:t"),
    ("usuarios alumnos", "SELECT COUNT(*) FROM usuarios WHERE tenant_id=:t AND rol='alumno'"),
    ("usuarios admin", "SELECT COUNT(*) FROM usuarios WHERE tenant_id=:t AND rol='administrador'"),
    ("suscripciones activas", "SELECT COUNT(*) FROM suscripciones WHERE tenant_id=:t AND estado='activo'"),
    ("planes", "SELECT COUNT(*) FROM planes WHERE tenant_id=:t"),
    ("disciplinas", "SELECT COUNT(*) FROM disciplinas WHERE tenant_id=:t"),
    ("horarios", "SELECT COUNT(*) FROM horarios WHERE tenant_id=:t"),
    ("clases", "SELECT COUNT(*) FROM clases WHERE tenant_id=:t"),
    ("creditos sumados", "SELECT COALESCE(SUM(creditos_disponibles),0) FROM suscripciones WHERE tenant_id=:t"),
]
for nombre, sql in checks:
    n = c.execute(text(sql), {"t": TENANT}).scalar()
    print(f"[seed-check] {nombre}: {n}")
with open(os.path.join(K6_DIR, "tokens.json"), encoding="utf-8") as f:
    n_tokens = len(json.load(f))
print(f"[seed-check] tokens.json: {n_tokens}")
c.close()
