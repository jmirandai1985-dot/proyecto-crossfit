"""
Inserta Air Bike y Remo en la tabla movimientos con categoria='maquinas'
Usa psycopg2 directo, no necesita uvicorn corriendo.
"""
import psycopg2
from datetime import datetime
from app.core.config import settings
DATABASE_URL = settings.DATABASE_URL


# DATABASE_URL ahora se obtiene de settings

print("🔌 Conectando a la base de datos...")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# 1. Verificar si ya existen
cur.execute(
    "SELECT id, nombre, categoria FROM movimientos WHERE categoria='maquinas' AND tenant_id=1")
existentes = cur.fetchall()
if existentes:
    print(f"\n📋 Movimientos existentes con categoria='maquinas':")
    for row in existentes:
        print(f"   ID={row[0]}, nombre='{row[1]}', categoria='{row[2]}'")
else:
    print("\n📋 No hay movimientos con categoria='maquinas' aún")

# 2. Insertar Air Bike
cur.execute("""
    INSERT INTO movimientos (tenant_id, nombre, descripcion, categoria, activo, created_at, updated_at)
    VALUES (1, 'Air Bike', 'Bicicleta estática Assault Bike', 'maquinas', true, NOW(), NOW())
    ON CONFLICT DO NOTHING
    RETURNING id
""")
row = cur.fetchone()
if row:
    print(f"\n✅ Air Bike insertado con ID={row[0]}")
else:
    print("\n⚠️ Air Bike ya existía (no se insertó duplicado)")

# 3. Insertar Remo
cur.execute("""
    INSERT INTO movimientos (tenant_id, nombre, descripcion, categoria, activo, created_at, updated_at)
    VALUES (1, 'Remo', 'Máquina de remo', 'maquinas', true, NOW(), NOW())
    ON CONFLICT DO NOTHING
    RETURNING id
""")
row = cur.fetchone()
if row:
    print(f"✅ Remo insertado con ID={row[0]}")
else:
    print("⚠️ Remo ya existía (no se insertó duplicado)")

conn.commit()

# 4. Verificar
print("\n🔍 Verificando inserción...")
cur.execute(
    "SELECT id, nombre, categoria, activo FROM movimientos WHERE categoria='maquinas' AND tenant_id=1")
resultados = cur.fetchall()
print(f"\n📊 Movimientos con categoria='maquinas' (tenant_id=1):")
for r in resultados:
    print(f"   ID={r[0]}, nombre='{r[1]}', categoria='{r[2]}', activo={r[3]}")

print(f"\n📊 Total: {len(resultados)} movimiento(s)")

cur.close()
conn.close()
print("\n🔌 Conexión cerrada.")
