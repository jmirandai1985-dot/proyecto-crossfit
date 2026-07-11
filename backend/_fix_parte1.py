"""
PARTE 1: Regenerar clase del sábado con horario corregido
"""
import psycopg2
import os
import re
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

url = os.getenv('DATABASE_URL', '')
url = re.sub(r'&channel_binding=[^&]+', '', url)
url = re.sub(r'\?channel_binding=[^&]+&', '?', url)

conn = psycopg2.connect(url)
cur = conn.cursor()

hoy = '2026-07-11'

print("=" * 60)
print("PARTE 1 - REGENERAR CLASE SÁBADO")
print("=" * 60)

# 1. Verificar horario 205
cur.execute(
    "SELECT id, hora_inicio::text, hora_fin::text, cupo_maximo, disciplina_id FROM horarios WHERE id=205")
r = cur.fetchone()
print(f"\n📋 Horario 205: id={r[0]} {r[1]}-{r[2]} cupo={r[3]} disc_id={r[4]}")

# 2. Verificar si ya existe clase regenerada
cur.execute("SELECT id, hora_inicio::text, hora_fin::text FROM clases WHERE horario_base_id=205 AND fecha=%s AND tenant_id=1", (hoy,))
existing = cur.fetchone()
if existing:
    print(
        f"\n✅ Clase ya existe para hoy: id={existing[0]} {existing[1]}-{existing[2]}")
else:
    # Insertar clase regenerada
    cur.execute("""
        INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada)
        SELECT 1, 205, disciplina_id, %s, '10:00', '12:00', cupo_maximo, 0, false
        FROM horarios WHERE id=205
        RETURNING id
    """, (hoy,))
    new_id = cur.fetchone()[0]
    print(f"\n🔄 Clase regenerada: id={new_id} con horario 10:00-12:00")

# 3. Mostrar todas las clases de hoy
cur.execute("""
    SELECT c.id, c.hora_inicio::text, c.hora_fin::text, d.nombre, c.asistentes_confirmados, c.cupo_maximo
    FROM clases c
    LEFT JOIN disciplinas d ON c.disciplina_id = d.id
    WHERE c.fecha=%s AND c.tenant_id=1
    ORDER BY c.hora_inicio
""", (hoy,))
print(f"\n📋 CLASES DE HOY ({hoy}):")
for r in cur.fetchall():
    print(f"   id={r[0]} {r[1]}-{r[2]} {r[3]} asistentes={r[4]}/{r[5]}")

conn.commit()
cur.close()
conn.close()

print("\n✅ PARTE 1 COMPLETADA")
