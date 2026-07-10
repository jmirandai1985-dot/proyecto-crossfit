"""
Migration directa via psycopg2 raw
"""
import urllib.parse
import psycopg2
from app.core.config import settings
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')

# Forzar carga del .env

DATABASE_URL = settings.DATABASE_URL
print(f"DATABASE_URL found: {DATABASE_URL[:50]}...")


# Parse URL
parsed = urllib.parse.urlparse(DATABASE_URL)
print(f"Host: {parsed.hostname}, Port: {parsed.port or 5432}, DB: {parsed.path.lstrip('/')}")
print(f"User: {parsed.username}")

try:
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        dbname=parsed.path.lstrip('/'),
        user=parsed.username,
        password=parsed.password,
        sslmode='require',
        connect_timeout=10
    )
    print("✅ Connected!")
    cur = conn.cursor()

    # Get movimientos
    cur.execute(
        "SELECT id, nombre FROM movimientos WHERE tenant_id = 1 ORDER BY id")
    rows = cur.fetchall()
    print(f"\nMovimientos: {len(rows)}")
    for r in rows:
        print(f"  ID={r[0]}: {r[1]}")

    # Add column if not exists
    try:
        cur.execute(
            "ALTER TABLE movimientos ADD COLUMN IF NOT EXISTS categoria VARCHAR(50) DEFAULT 'fuerza'")
        conn.commit()
        print("\n✅ Columna categoria agregada")
    except Exception as e:
        print(f"\n⚠️ {e}")
        conn.rollback()
        try:
            cur.execute(
                "ALTER TABLE movimientos ADD COLUMN categoria VARCHAR(50) DEFAULT 'fuerza'")
            conn.commit()
            print("\n✅ Columna categoria agregada (v2)")
        except Exception as e2:
            print(f"\n⚠️ Error adding column: {e2}")
            conn.rollback()

    cur.close()
    conn.close()

except Exception as e:
    print(f"\n❌ Connection error: {e}")
