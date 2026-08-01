"""Script temporal para crear la tabla transacciones_financieras en TEST."""
import psycopg2

URL = 'postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-muddy-term-aclwd3w7-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

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
