"""DIAG: Sabado sin clases + bloque 11hs."""
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ENVIRONMENT", "test")
from app.core.config import settings

if settings.DATABASE_URL.startswith("postgresql://user:pass@"):
    print("FATAL: Define DATABASE_URL en backend/.env.test (copia .env.example)")
    sys.exit(1)
DB = settings.DATABASE_URL
conn = psycopg2.connect(DB, connect_timeout=10)
cur = conn.cursor()

cur.execute("SELECT coach_id, disciplina_id, activo FROM coach_disciplinas WHERE coach_id=7")
print("COACH_DISCIPLINAS coach7:", cur.fetchall())

cur.execute("SELECT id, nombre, es_open_box FROM disciplinas ORDER BY id")
print("DISCIPLINAS:", cur.fetchall())

cur.execute("""SELECT fecha, hora_inicio, disciplina_id, wod_id
               FROM clases WHERE tenant_id=1
               AND fecha BETWEEN '2026-08-01' AND '2026-08-09'
               ORDER BY fecha, hora_inicio""")
print("CLASES 01-09 AGO:")
for r in cur.fetchall():
    print("  ", r)

cur.execute("SELECT id, dia_semana, hora_inicio, disciplina_id, activo FROM horarios WHERE tenant_id=1 ORDER BY disciplina_id, hora_inicio")
print("HORARIOS:")
for r in cur.fetchall():
    print("  ", r)

cur.close()
conn.close()