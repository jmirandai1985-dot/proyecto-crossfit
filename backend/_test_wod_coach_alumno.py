"""
Script de prueba: coach crea un WOD y alumno lo ve en Dashboard.
Ejecutar con: python _test_wod_coach_alumno.py
"""
import requests
import json
from datetime import date, datetime

BASE = "http://localhost:8000/api/v1"
TENANT_ID = 1

# Usar coach_id=1 (admin) para crear el WOD
COACH_ID = 1


def print_json(label, data):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def print_sep(titulo):
    print(f"\n{'='*60}")
    print(f"  {titulo}")
    print(f"{'='*60}")


hoy = str(date.today())

# ─── Paso 1: Consultar WOD de hoy ANTES ─────────────────────────
print_sep("PASO 1: WOD DE HOY (ANTES)")
r1 = requests.get(f"{BASE}/wods/hoy", params={"tenant_id": TENANT_ID})
print(f"  Status: {r1.status_code}")
resp1 = r1.json()
if resp1:
    print_json("WOD actual para hoy", resp1)
else:
    print("  (sin WOD para hoy - respuesta null)")

# ─── Paso 2: Coach crea un WOD para hoy ──────────────────────────
print_sep("PASO 2: COACH CREA WOD PARA HOY")

# Primero necesito IDs de movimientos reales para usar
r_movs = requests.get(f"{BASE}/movimientos", params={"tenant_id": TENANT_ID})
movs = r_movs.json()
# Buscar Thruster y Pull-ups (Dominadas)
thruster_id = None
pullup_id = None
for m in movs:
    if isinstance(m, dict):
        if "Thruster" in m.get("nombre", "") and not thruster_id:
            thruster_id = m["id"]
        if "Pull-ups" in m.get("nombre", "") and "Dominadas" in m.get("nombre", ""):
            pullup_id = m["id"]

print(f"  Thruster ID: {thruster_id}")
print(f"  Pull-ups ID: {pullup_id}")

payload = {
    "tenant_id": TENANT_ID,
    "fecha": hoy,
    "titulo": "WOD de prueba automatica",
    "descripcion": "15 min AMRAP",
    "coach_id": COACH_ID,
    "estado": "publicado",
    "movimientos": [
        {
            "movimiento_id": thruster_id,
            "orden": 1,
            "series": 3,
            "repeticiones": "10",
            "peso": 40,
            "fase": "WOD"
        },
        {
            "movimiento_id": pullup_id,
            "orden": 2,
            "series": 3,
            "repeticiones": "15",
            "fase": "WOD"
        }
    ]
}

print(f"  Enviando POST a /wods/ con payload:")
print(f"    fecha={hoy}, titulo={payload['titulo']}")

r2 = requests.post(
    f"{BASE}/wods/", params={"tenant_id": TENANT_ID}, json=payload)
print(f"  Status: {r2.status_code}")

if r2.status_code < 300:
    wod_creado = r2.json()
    wod_id = wod_creado.get("id")
    print(f"  WOD creado con ID={wod_id}")
    print(f"  Título: {wod_creado.get('titulo')}")
    print(f"  Fecha: {wod_creado.get('fecha')}")
else:
    print(f"  Error: {r2.text[:500]}")
    wod_id = None

# ─── Paso 3: Consultar WOD de hoy DESPUÉS ────────────────────────
print_sep("PASO 3: WOD DE HOY (DESPUÉS de crear)")
r3 = requests.get(f"{BASE}/wods/hoy", params={"tenant_id": TENANT_ID})
print(f"  Status: {r3.status_code}")
resp3 = r3.json()
if resp3:
    print_json("WOD para hoy (después de crear)", resp3)
else:
    print("  (null - no se encontró)")

# ─── Paso 4: Comparar ───────────────────────────────────────────
print_sep("PASO 4: VERIFICACIÓN")
if not resp1 and resp3:
    print("✅ ANTES: sin WOD → DESPUÉS: WOD encontrado")
    print("✅ El alumno ahora ve el WOD del día correctamente")
elif resp1 and resp3 and resp1.get("id") == resp3.get("id"):
    print("✅ Ya había WOD y se actualizó correctamente")
else:
    print("⚠️  REVISAR: el comportamiento no coincide con lo esperado")

if resp3:
    titulo = resp3.get("titulo")
    movs_count = len(resp3.get("movimientos", []) or [])
    fases_count = len(resp3.get("fases", []) or [])
    print(f"\n  Título del WOD: {titulo}")
    print(f"  Movimientos: {movs_count}")
    print(f"  Fases: {fases_count}")
    match = titulo == payload["titulo"] and movs_count == 2
    print(f"  Coincide título: {'✅' if titulo == payload['titulo'] else '❌'}")
    print(f"  Coincide cantidad movs: {'✅' if movs_count == 2 else '❌'}")
    print(f"  Test: {'✅ PASÓ' if match else '❌ FALLÓ - revisar detalle'}")

# ─── Paso 5: Limpieza ───────────────────────────────────────────
if wod_id:
    print_sep("PASO 5: LIMPIEZA")
    r_del = requests.delete(f"{BASE}/wods/{wod_id}",
                            params={"tenant_id": TENANT_ID})
    print(f"  DELETE /wods/{wod_id} → Status: {r_del.status_code}")
    print(f"  WOD de prueba eliminado")

print("\n" + "="*60)
print("  PRUEBA COMPLETADA")
print("="*60)
