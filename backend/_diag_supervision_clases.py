"""
DIAGNOSTICO (SOLO LECTURA) para el bug reportado:
Supervision de Clases muestra "0 clase(s) en el rango" en TODAS las disciplinas.
Verifica:
 1. Si la tabla cobertura_emergencia existe en TEST (el cambio de T5 usa EXISTS).
 2. Cuantas clases existen en fechas recientes.
 3. Simula la query exacta de listar_clases para ver si falla.
No modifica nada.
"""
import os
import sys
from datetime import date, timedelta

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

os.environ["ENVIRONMENT"] = "test"

import psycopg2
from app.core.config import settings

URL_TEST = settings.DATABASE_URL
print("=" * 70)
print("DIAGNOSTICO - Supervision de Clases '0 en el rango'")
print(f"BD TEST: small-butterfly = {'small-butterfly' in URL_TEST}")
print("=" * 70)

c = psycopg2.connect(URL_TEST)
cur = c.cursor()

# 1. Existe la tabla cobertura_emergencia?
cur.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema='public' AND table_name IN
      ('cobertura_emergencia','clases','horarios','disciplinas')
""")
tablas = [r[0] for r in cur.fetchall()]
print(f"\n[1] Tablas presentes en TEST: {sorted(tablas)}")
if 'cobertura_emergencia' not in tablas:
    print("    >>> FALTA cobertura_emergencia <<<")
else:
    cur.execute("SELECT COUNT(*) FROM cobertura_emergencia")
    print(f"    cobertura_emergencia existe, filas: {cur.fetchone()[0]}")

# 2. Clases en rango reciente (desde 2026-08-01)
cur.execute("""
    SELECT COUNT(*) FROM clases
    WHERE tenant_id=1 AND fecha >= '2026-08-01' AND fecha <= '2026-08-31'
""")
print(f"\n[2] Clases tenant=1 en agosto 2026: {cur.fetchone()[0]}")

cur.execute("""
    SELECT fecha, COUNT(*) FROM clases
    WHERE tenant_id=1 AND fecha >= '2026-08-01' AND fecha <= '2026-08-31'
    GROUP BY fecha ORDER BY fecha
""")
filas = cur.fetchall()
for f, cnt in filas:
    print(f"     {f}: {cnt} clases")

# 3. Simular la query de listar_clases con el EXISTS de T5
hoy = date.today()
desde = (hoy - timedelta(days=7)).isoformat()
hasta = (hoy + timedelta(days=8)).isoformat()
print(f"\n[3] Simulando query listar_clases rango [{desde}, {hasta}]...")
try:
    cur.execute("""
        SELECT COUNT(*)
        FROM clases c
        LEFT JOIN disciplinas d ON c.disciplina_id = d.id
        LEFT JOIN usuarios u ON c.coach_id = u.id
        WHERE c.tenant_id = 1 AND c.fecha >= %s AND c.fecha <= %s
          AND CASE WHEN EXISTS (
              SELECT 1 FROM cobertura_emergencia ce
              WHERE ce.clase_id = c.id AND ce.tenant_id = c.tenant_id
          ) THEN true ELSE false END IN (true, false)
    """, (desde, hasta))
    print(f"    Query OK: {cur.fetchone()[0]} clases en rango")
except Exception as e:
    print(f"    >>> QUERY FALLA: {e} <<<")
    print("    >>> CAUSA RAZ: el EXISTS referencia cobertura_emergencia")

cur.close()
c.close()
print("\n" + "=" * 70)
print("FIN DIAGNOSTICO")
print("=" * 70)