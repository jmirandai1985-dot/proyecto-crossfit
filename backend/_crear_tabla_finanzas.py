"""Script temporal para crear la tabla transacciones_financieras en TEST."""
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ENVIRONMENT", "test")
from app.core.config import settings

if settings.DATABASE_URL.startswith("postgresql://user:pass@"):
    print("FATAL: Define DATABASE_URL en backend/.env.test (copia .env.example)")
    sys.exit(1)
URL = settings.DATABASE_URL

c = psycopg2.connect(URL)
c.autocommit = True
cur = c.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS transacciones_financieras (
        id SERIAL PRIMARY KEY,
        tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        tipo VARCHAR(20) NOT NULL,
        categoria VARCHAR(50) NOT NULL,
        monto NUMERIC(12,0) NOT NULL,
        descripcion VARCHAR(500),
        referencia_tipo VARCHAR(50),
        referencia_id INT,
        fecha DATE NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
""")
cur.execute("CREATE INDEX IF NOT EXISTS ix_transacciones_financieras_tenant_fecha ON transacciones_financieras(tenant_id, fecha)")
print('[OK] Tabla transacciones_financieras creada')
cur.close()
c.close()
