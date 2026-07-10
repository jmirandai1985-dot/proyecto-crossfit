import psycopg2
from app.core.config import settings

conn = psycopg2.connect(settings.DATABASE_URL)
cur = conn.cursor()

cur.execute("""
    SELECT enumlabel 
    FROM pg_enum 
    WHERE enumtypid = (
        SELECT oid FROM pg_type WHERE typname = 'estado_suscripcion'
    )
    ORDER BY enumsortorder
""")
print("Valores del ENUM estado_suscripcion:")
for e in cur.fetchall():
    print(f"  '{e[0]}'")

conn.close()
