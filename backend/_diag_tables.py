from sqlalchemy import text
from app.db.database import SessionLocal
import sys
sys.path.insert(0, '.')

db = SessionLocal()
rows = db.execute(text(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")).fetchall()
print("=== TABLAS ===")
for r in rows:
    print(f"  {r.table_name}")

# Check horarios_base columns via pg_attribute
rows2 = db.execute(text("""
    SELECT a.attname, t.typname
    FROM pg_class c
    JOIN pg_attribute a ON a.attrelid = c.oid
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE c.relname = 'horarios_base'
    AND a.attnum > 0
    AND NOT a.attisdropped
    ORDER BY a.attnum
""")).fetchall()
print("\n=== horarios_base columns ===")
for r in rows2:
    print(f"  {r.attname} ({r.typname})")

# Check horarios table columns too
rows3 = db.execute(text("""
    SELECT a.attname, t.typname
    FROM pg_class c
    JOIN pg_attribute a ON a.attrelid = c.oid
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE c.relname = 'horarios'
    AND a.attnum > 0
    AND NOT a.attisdropped
    ORDER BY a.attnum
""")).fetchall()
print("\n=== horarios table columns ===")
for r in rows3:
    print(f"  {r.attname} ({r.typname})")

# Check if horarios_base might be a view or foreign table referencing horarios
# Also get the actual record
row4 = db.execute(text(
    "SELECT id, tenant_id, disciplina_id, dia_semana, hora, cupo_maximo, activo FROM horarios_base WHERE dia_semana = 5")).fetchall()
print("\n=== Sábado records (using 'hora' column) ===")
for r in row4:
    print(
        f"  id={r.id} disc={r.disciplina_id} dia={r.dia_semana} hora={r.hora} cupo={r.cupo_maximo}")

db.close()
