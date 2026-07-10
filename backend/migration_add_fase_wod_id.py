"""
Migracion: Agregar columnas faltantes para conectar WODs con clases y fases.

Paso 1: Columna "fase" en wod_movimientos
Paso 2: Columna "wod_id" en clases (FK -> wods.id)

Ejecutar desde la carpeta backend:
  cd backend
  python migration_add_fase_wod_id.py
"""
import psycopg2
from dotenv import load_dotenv
import sys
import os
import re

# Asegurar que estamos en el directorio backend
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

# Cargar .env manualmente para evitar problemas de ruta
load_dotenv(os.path.join(script_dir, '.env'))

DATABASE_URL = os.getenv("DATABASE_URL", "")
print(f"URL encontrada: {DATABASE_URL[:50]}...")

if not DATABASE_URL or "localhost" in DATABASE_URL:
    print("ERROR: La URL de BD es localhost o esta vacia.")
    print("Verifica que backend/.env tenga la URL real de Neon.")
    sys.exit(1)

# Limpiar URL: channel_binding no es soportado por psycopg2
clean_url = re.sub(r'&channel_binding=[^&]+', '', DATABASE_URL)
clean_url = re.sub(r'\?channel_binding=[^&]+&', '?', clean_url)
clean_url = re.sub(r'\?channel_binding=[^&]+$', '', clean_url)

# Usar psycopg2 directamente

print("Conectando a Neon DB...")
conn = psycopg2.connect(clean_url)
cursor = conn.cursor()
print("  Conexion exitosa!")

# Paso 1
print("\n1. Agregando columna 'fase' a wod_movimientos...")
cursor.execute("""
    ALTER TABLE wod_movimientos
    ADD COLUMN IF NOT EXISTS fase VARCHAR(30) DEFAULT NULL
""")
conn.commit()
print("   OK Columna 'fase' agregada")

# Paso 2
print("\n2. Agregando columna 'wod_id' a clases...")
cursor.execute("""
    ALTER TABLE clases
    ADD COLUMN IF NOT EXISTS wod_id INTEGER
    REFERENCES wods(id) ON DELETE SET NULL
    DEFAULT NULL
""")
conn.commit()
print("   OK Columna 'wod_id' agregada (FK -> wods.id)")

# Paso 3
print("\n3. Creando indice para wod_id en clases...")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS ix_clases_wod_id
    ON clases(wod_id)
""")
conn.commit()
print("   OK Indice creado")

# Verificar
print("\n" + "=" * 50)
print("VERIFICACION")
print("=" * 50)

cursor.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'wod_movimientos'
    AND column_name = 'fase'
""")
r = cursor.fetchone()
if r:
    print(f"OK wod_movimientos.fase: {r[0]} ({r[1]}, nullable={r[2]})")
else:
    print("ERROR: wod_movimientos.fase NO encontrada")

cursor.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'clases'
    AND column_name = 'wod_id'
""")
r = cursor.fetchone()
if r:
    print(f"OK clases.wod_id: {r[0]} ({r[1]}, nullable={r[2]})")
else:
    print("ERROR: clases.wod_id NO encontrada")

cursor.close()
conn.close()

print("\nOK Migracion completada exitosamente!")
