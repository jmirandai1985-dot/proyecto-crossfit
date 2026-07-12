"""
Script de prueba: registrar RM de categoría MAQUINAS y verificar que aparece.
Ejecutar con: python _test_rm_maquinas.py
"""
import requests
import json
from datetime import date

BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 5
TENANT_ID = 1

hoy = str(date.today())


def print_json(label, data):
    print(f"\n  {label}:")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# 1. Buscar un movimiento de categoría maquinas o cardio
r = requests.get(f"{BASE}/movimientos", params={"tenant_id": TENANT_ID})
movs = r.json()
maquinas = [m for m in movs if isinstance(m, dict) and m.get(
    "categoria") in ("metabolico", "cardio")]
print(f"\nMovimientos MAQUINAS/CARDIO disponibles: {len(maquinas)}")
for m in maquinas[:5]:
    print(f"  ID={m['id']} nombre={m['nombre']} categoria={m.get('categoria')}")

# Elegir el primero
mov = maquinas[0] if maquinas else None
if not mov:
    print("❌ No hay movimientos de maquinas/cardio")
    exit(1)

print(
    f"\n✅ Movimiento elegido: ID={mov['id']} '{mov['nombre']}' (categoria={mov['categoria']})")

# 2. Crear RM de maquinas
print("\n--- CREANDO RM DE MAQUINAS ---")
payload = {
    "tenant_id": TENANT_ID,
    "alumno_id": ALUMNO_ID,
    "movimiento_id": mov["id"],
    "peso_kg": 1,
    "calorias": 300,
    "km": 3.5,
    "vueltas": 10,
    "minutos": 25,
    "fecha": hoy,
    "notas": "RM maquinas test automatico"
}
print(f"Payload: {json.dumps(payload, indent=2)}")

r = requests.post(f"{BASE}/historial-rm", json=payload)
print(f"\nPOST /historial-rm → Status: {r.status_code}")
if r.status_code < 300:
    print_json("Respuesta POST", r.json())
else:
    print(f"Error: {r.text[:500]}")
    exit(1)

# 3. Listar todos los RMs del alumno para ver si aparece
print("\n--- LISTANDO RMs DEL ALUMNO ---")
r = requests.get(f"{BASE}/historial-rm/alumnos/{ALUMNO_ID}/rms",
                 params={"tenant_id": TENANT_ID})
rms = r.json()
print_json(f"Total RMs: {len(rms) if isinstance(rms, list) else 0}", rms)

# 4. Buscar específicamente el RM que acabamos de crear
if isinstance(rms, list):
    encontrado = [rm for rm in rms if rm.get("movimiento_id") == mov["id"]]
    if encontrado:
        print(f"\n✅ RM encontrado en la lista!")
        print_json("Datos del RM en la lista", encontrado[0])
    else:
        print(f"\n❌ RM NO aparece en la lista de RMs")

# 5. Listar el historial completo para ver si aparece
print("\n--- LISTANDO HISTORIAL COMPLETO ---")
r = requests.get(f"{BASE}/historial-rm",
                 params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID, "limit": 50})
historial = r.json()
if isinstance(historial, list):
    nuevos = [h for h in historial if h.get(
        "notas") == "RM maquinas test automatico"]
    print(f"Registros nuevos encontrados: {len(nuevos)}")
    for n in nuevos:
        print_json("Nuevo registro", n)

# 6. Verificar si las columnas nuevas existen en la BD
print("\n--- VERIFICANDO CAMPOS EN RESPUESTA ---")
if isinstance(rms, list) and len(rms) > 0:
    rm_ejemplo = rms[0]
    tiene_campos_nuevos = any(k in rm_ejemplo for k in [
                              "calorias", "km", "vueltas", "minutos", "repeticiones", "series"])
    print(
        f"Campos nuevos en respuesta: {'✅' if tiene_campos_nuevos else '❌ NO'}")
    print(f"Keys en respuesta: {list(rm_ejemplo.keys())}")
