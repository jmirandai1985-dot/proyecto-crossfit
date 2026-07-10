"""
Insertar Air Bike y Rowing Machine, corregir RMs historicos
"""
import urllib.parse
import psycopg2
from app.core.config import settings
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))


parsed = urllib.parse.urlparse(settings.DATABASE_URL)
conn = psycopg2.connect(host=parsed.hostname, port=parsed.port or 5432,
                        dbname=parsed.path.lstrip('/'), user=parsed.username,
                        password=parsed.password, sslmode='require')
cur = conn.cursor()

# 1. Add Air Bike and Rowing Machine
for nombre, descripcion in [
    ("Air Bike", "Bicicleta de asalto"),
    ("Rowing Machine", "Maquina de remo")
]:
    cur.execute(
        "SELECT id FROM movimientos WHERE tenant_id = 1 AND nombre = %s",
        (nombre,)
    )
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO movimientos (tenant_id, nombre, descripcion, categoria, activo, created_at, updated_at) "
            "VALUES (1, %s, %s, 'maquinas', true, NOW(), NOW())",
            (nombre, descripcion)
        )
        print(f"Insertado: {nombre}")
    else:
        print(f"Ya existe: {nombre}")

conn.commit()

# 2. Check total
cur.execute("SELECT COUNT(*) FROM movimientos WHERE tenant_id = 1")
print(f"\nTotal movimientos: {cur.fetchone()[0]}")

# 3. Show all with categories
cur.execute(
    "SELECT id, nombre, categoria FROM movimientos WHERE tenant_id = 1 ORDER BY id")
for r in cur.fetchall():
    print(f"  ID={r[0]:5d}: {r[2]:12s} - {r[1]}")

# 4. Fix historical RMs
cur.execute("""
    SELECT hr.id, hr.tipo_rm, m.nombre
    FROM historial_rm hr
    JOIN movimientos m ON hr.movimiento_id = m.id
    WHERE hr.tipo_rm = 'peso' AND m.categoria IN ('gimnastico', 'cardio')
""")
wrong = cur.fetchall()
print(f"\nRMs con tipo_rm incorrecto (peso -> reps): {len(wrong)}")
for r in wrong:
    cur.execute(
        "UPDATE historial_rm SET tipo_rm = 'reps' WHERE id = %s", (r[0],))
    print(f"  Corregido ID={r[0]}: {r[2]}")
conn.commit()

cur.close()
conn.close()
print(f"\n✅ Completado. Corregidos {len(wrong)} RMs historicos")
