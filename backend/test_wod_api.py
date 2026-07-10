"""Script para probar la creación de WODs vía API"""
import requests
import json

BASE_URL = "http://localhost:8000/api/v1/wods/"

# 1. Test GET - listar WODs
print("=" * 60)
print("1. TEST GET - Listar WODs")
print("=" * 60)
try:
    resp = requests.get(f"{BASE_URL}?tenant_id=1", headers={
                        "Content-Type": "application/json"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        wods = resp.json()
        print(f"WODs encontrados: {len(wods)}")
        print(f"Respuesta: {json.dumps(wods, indent=2, ensure_ascii=False)}")
    else:
        print(f"Error: {resp.text}")
except Exception as e:
    print(f"Error de conexión: {e}")

# 2. Test POST - Crear un WOD
print("\n" + "=" * 60)
print("2. TEST POST - Crear WOD")
print("=" * 60)
wod_data = {
    "fecha": "2026-03-07",
    "titulo": "WOD de prueba API",
    "descripcion": "WOD creado desde prueba automatizada",
    "coach_id": 1,
    "movimientos": [
        {
            "movimiento_id": 1,
            "orden": 1,
            "series": 3,
            "repeticiones": "10",
            "peso": 50.0,
            "tiempo": None,
            "notas": "Calentar bien"
        },
        {
            "movimiento_id": 5,
            "orden": 2,
            "series": 5,
            "repeticiones": "5",
            "peso": 80.0,
            "tiempo": None,
            "notas": "Deadlift"
        }
    ]
}
try:
    resp = requests.post(f"{BASE_URL}?tenant_id=1", json=wod_data)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        wod_creado = resp.json()
        print(f"WOD creado exitosamente!")
        print(
            f"Respuesta: {json.dumps(wod_creado, indent=2, ensure_ascii=False)}")
    else:
        print(f"Error: {resp.status_code}")
        print(f"Detalle: {resp.text}")
except Exception as e:
    print(f"Error de conexión: {e}")

# 3. Test GET nuevamente para verificar
print("\n" + "=" * 60)
print("3. TEST GET - Verificar WOD creado")
print("=" * 60)
try:
    resp = requests.get(f"{BASE_URL}?tenant_id=1", headers={
                        "Content-Type": "application/json"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        wods = resp.json()
        print(f"WODs encontrados: {len(wods)}")
        for w in wods:
            print(
                f"  - ID: {w['id']} | Fecha: {w['fecha']} | Título: {w.get('titulo', '')} | Estado: {w.get('estado', '')}")
            if 'movimientos' in w and w['movimientos']:
                for m in w['movimientos']:
                    print(
                        f"      Movimiento ID: {m['movimiento_id']} | Orden: {m['orden']} | Series: {m.get('series', '')} | Reps: {m.get('repeticiones', '')}")
except Exception as e:
    print(f"Error de conexión: {e}")

print("\n" + "=" * 60)
print("PRUEBA COMPLETADA")
print("=" * 60)
