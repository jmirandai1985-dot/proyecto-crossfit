"""Verificación SOLO LECTURA del resultado del sync en TEST (lingering-shape)."""
import os
import sys
import importlib

os.environ["ENVIRONMENT"] = "test"
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

settings = importlib.import_module("app.core.config").settings
URL_TEST = settings.DATABASE_URL
print(f"BD de TEST: {URL_TEST[:80]}...")
print(f"lingering-shape (DIRECT): {'lingering-shape' in URL_TEST}")
print("=" * 60)

import psycopg2

c = psycopg2.connect(URL_TEST)
cur = c.cursor()

print("\nCONTEO DE TABLAS:")
for tabla in ["tenants", "movimientos", "disciplinas", "planes", "horarios",
              "usuarios", "suscripciones", "productos", "clases", "reservas",
              "historial_rm", "notificaciones"]:
    cur.execute(f"SELECT COUNT(*) FROM {tabla}")
    print(f"  {tabla}: {cur.fetchone()[0]}")

print("\nCOLUMNAS EN disciplinas:")
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='disciplinas' ORDER BY ordinal_position
""")
print("  " + ", ".join(r[0] for r in cur.fetchall()))

print("\nCOLUMNAS EN planes:")
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='planes' ORDER BY ordinal_position
""")
print("  " + ", ".join(r[0] for r in cur.fetchall()))

print("\nrequiere_coach POR DISCIPLINA:")
try:
    cur.execute("SELECT id, nombre, requiere_coach FROM disciplinas ORDER BY id")
    for r in cur.fetchall():
        print(f"  id={r[0]} nombre={r[1]!r} requiere_coach={r[2]}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\nes_estudiante EN planes (tabla vacia si fallo el sync):")
try:
    cur.execute("SELECT id, nombre, es_estudiante FROM planes ORDER BY id")
    rows = cur.fetchall()
    if not rows:
        print("  (sin filas - planes esta vacia)")
    for r in rows:
        print(f"  id={r[0]} nombre={r[1]!r} es_estudiante={r[2]}")
except Exception as e:
    print(f"  ERROR: {e}")

cur.close()
c.close()
print("\nVERIFICACION COMPLETA")