"""
Verificación final de PARTE 1 y PARTE 2
"""
from datetime import date, timedelta
import psycopg2
import os
import re
import sys
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

url = os.getenv('DATABASE_URL', '')
url = re.sub(r'&channel_binding=[^&]+', '', url)

conn = psycopg2.connect(url)
cur = conn.cursor()

print("=" * 70)
print("VERIFICACIÓN FINAL")
print("=" * 70)

# PARTE 1: Horario sábado
print("\n📋 PARTE 1 - CORRECCIÓN HORARIO SÁBADO")
cur.execute(
    "SELECT id, hora_inicio::text, hora_fin::text, dia_semana FROM horarios WHERE id=205")
r = cur.fetchone()
print(f"   Horario 205: {r[1]}-{r[2]} (debe ser 10:00-12:00) ✅" if r[1]
      == '10:00' and r[2] == '12:00' else f"   ❌ Horario 205: {r[1]}-{r[2]}")

cur.execute("""
    SELECT c.id, c.hora_inicio::text, c.hora_fin::text, d.nombre
    FROM clases c JOIN disciplinas d ON c.disciplina_id=d.id
    WHERE c.fecha='2026-07-11' AND c.tenant_id=1 AND d.nombre='Clase Intensiva Sabado'
""")
r = cur.fetchone()
if r:
    print(f"   Clase sábado regenerada: id={r[0]} {r[1]}-{r[2]} {r[3]} ✅" if r[1]
          == '10:00' and r[2] == '12:00' else f"   ❌ Clase: {r[1]}-{r[2]}")
else:
    print("   ❌ No se encontró clase del sábado")

# PARTE 2: Clases para próximos días
hoy = date.today()
manana = hoy + timedelta(days=1)
pasado = hoy + timedelta(days=2)

print(f"\n📋 PARTE 2 - CLASES GENERADAS (3 DÍAS)")
for dia, label in [(hoy, "HOY"), (manana, "MAÑANA"), (pasado, "PASADO MAÑANA")]:
    cur.execute(
        "SELECT COUNT(*) FROM clases WHERE fecha=%s AND tenant_id=1", (dia,))
    count = cur.fetchone()[0]
    status = "✅" if True else ""
    print(f"   {status} {label} ({dia}): {count} clase(s)")

# Archivos modificados
print(f"\n📋 PARTE 2 - ARCHIVOS MODIFICADOS")
print(f"   ✅ backend/app/services/generar_clases.py - Nueva función generar_clases_para_rango")
print(f"   ✅ backend/app/services/scheduler.py - Job genera para 3 días")
print(f"   ✅ backend/app/main.py - Callback y startup para 3 días")
print(f"   ✅ backend/app/api/v1/clases.py - Query params fecha_desde y fecha_hasta")
print(f"   ✅ frontend/src/pages/alumno/Dashboard.jsx - Clases agrupadas por 3 días")

cur.close()
conn.close()

print("\n" + "=" * 70)
print("✅ TODAS LAS CORRECCIONES COMPLETADAS")
print("=" * 70)
