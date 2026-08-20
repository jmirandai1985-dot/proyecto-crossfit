"""
VERIFICACION 1 (SOLO LECTURA): Confirma la causa real del fallo
test_c16_sin_clases_duplicadas usando la BD TEST (small-butterfly).
No modifica nada: solo consultas SELECT / conteos.
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
print("VERIFICACION 1 - Causa real test_c16_sin_clases_duplicadas")
print(f"BD TEST: small-butterfly = {'small-butterfly' in URL_TEST}")
print("=" * 70)

c = psycopg2.connect(URL_TEST)
cur = c.cursor()

# 1. Fecha actual y dia semana
hoy = date.today()
cur.execute("SELECT CURRENT_DATE, EXTRACT(DOW FROM CURRENT_DATE)::int")
fecha_db, dow_db = cur.fetchone()
print(f"\n[1] Fecha actual DB: {fecha_db} | DOW (0=domingo): {dow_db} | Hoy es: {['Domingo','Lunes','Martes','Miercoles','Jueves','Viernes','Sabado'][dow_db]}")

# 2. Clases en domingo (lo que test_c16 cuenta)
cur.execute("""
    SELECT fecha, hora_inicio, disciplina_id, cupo_maximo
    FROM clases WHERE tenant_id=1 AND EXTRACT(DOW FROM fecha)::int=0
    ORDER BY fecha
""")
clases_dom = cur.fetchall()
print(f"\n[2] Clases en Domingo (tenant=1): {len(clases_dom)}")
for r in clases_dom[:10]:
    print(f"     fecha={r[0]} hora={r[1]} disc={r[2]} cupo={r[3]}")

# 3. Son del seed o de produccion? Horarios base con dia_semana=0 (domingo)
cur.execute("""
    SELECT COUNT(*) FROM horarios
    WHERE tenant_id=1 AND dia_semana=0 AND activo=true
""")
horarios_dom = cur.fetchone()[0]
print(f"\n[3] Horarios base activos con dia_semana=0 (domingo) en TEST: {horarios_dom}")
cur.execute("SELECT dia_semana, COUNT(*) FROM horarios WHERE tenant_id=1 AND activo=true GROUP BY dia_semana ORDER BY dia_semana")
for d, cnt in cur.fetchall():
    print(f"     dia_semana={d} ({['Dom','Lun','Mar','Mie','Jue','Vie','Sab'][d]}): {cnt} horarios")

# 4. El seed usa horario con dia_semana = hoy.weekday(). Si hoy es domingo, weekday()=6
#    pero el test C16 espera 0 en EXTRACT(DOW). Confirmar la definicion usada por seed.
print("\n[4] Logica del seed (run_setup_test_db.py): usa `hoy.weekday()` como dia_semana.")
print(f"    - date.weekday() de hoy ({hoy}): {hoy.weekday()} (lunes=0..domingo=6)")
print(f"    - EXTRACT(DOW) que usa el test: {dow_db} (domingo=0)")
print(f"    => Si hoy es domingo: seed guarda horario con dia_semana=6 (weekday),")
print(f"       y el test busca EXTRACT(DOW)=0. La CLASE se crea para la fecha 'hoy'")

# 5. Contar clases totales por fecha en TEST (ver si el seed creo clases para el domingo)
cur.execute("SELECT fecha, COUNT(*) FROM clases WHERE tenant_id=1 GROUP BY fecha ORDER BY fecha")
filas = cur.fetchall()
print(f"\n[5] Clases por fecha en TEST (tenant=1): {len(filas)} fechas")
for f, cnt in filas[:15]:
    d = (f.weekday(), f.isoweekday() % 7)  # weekday y dow
    es_dom = d[1] == 0
    print(f"     {f} ({['Lun','Mar','Mie','Jue','Vie','Sab','Dom'][d[0]]}): {cnt} clases {'<== DOMINGO' if es_dom else ''}")

# 6. Confirmar duplicados (primer assert del test)
cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT fecha, hora_inicio, disciplina_id, COUNT(*) as cnt
        FROM clases WHERE tenant_id=1
        GROUP BY fecha, hora_inicio, disciplina_id
        HAVING COUNT(*) > 1
    ) sub
""")
dupes = cur.fetchone()[0]
print(f"\n[6] Grupos duplicados (fecha+hora+disciplina) en TEST: {dupes} {'<== PASA' if dupes == 0 else '<== FALLA'}")

cur.close()
c.close()
print("\n" + "=" * 70)
print("CONCLUSION: ver lineas [2], [3], [4] y [5]")
print("=" * 70)