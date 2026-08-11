
"""Verificar que las 4 migraciones post-sync se aplicaron correctamente."""
import psycopg2

URL = "postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-curly-rain-acg2z9h1-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

c = psycopg2.connect(URL)
c.autocommit = True
cur = c.cursor()

# 1. es_estudiante en planes
print("=== es_estudiante en planes ===")
cur.execute("SELECT nombre, es_estudiante FROM planes ORDER BY id")
for r in cur.fetchall():
    print(f"  {r[0]:25} es_estudiante={r[1]}")

# 2. requiere_coach en disciplinas
print("\n=== requiere_coach en disciplinas ===")
cur.execute("SELECT nombre, requiere_coach FROM disciplinas ORDER BY id")
for r in cur.fetchall():
    print(f"  {r[0]:25} requiere_coach={r[1]}")

# 3. coach_disciplinas
print()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name='coach_disciplinas'")
print(f"coach_disciplinas existe: {bool(cur.fetchone())}")
cur.execute("SELECT COUNT(*) FROM coach_disciplinas")
print(f"coach_disciplinas rows: {cur.fetchone()[0]}")

# 4. cobertura_emergencia
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name='cobertura_emergencia'")
print(f"cobertura_emergencia existe: {bool(cur.fetchone())}")

cur.close()
c.close()
print("\n✅ VERIFICACION COMPLETA")
