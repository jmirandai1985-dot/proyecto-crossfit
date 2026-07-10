import psycopg2
from app.core.config import settings

conn = psycopg2.connect(settings.DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("ALTER TABLE suscripciones ALTER COLUMN voucher_url DROP NOT NULL;")
print("✓ voucher_url ahora acepta NULL")

cur.execute("ALTER TABLE suscripciones ALTER COLUMN aprobado_por DROP NOT NULL;")
print("✓ aprobado_por ahora acepta NULL")

conn.close()
