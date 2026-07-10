"""
FRESCO: Verificar estado actual del alumno 5 y endpoint nivel-general
"""
import urllib.request
import json
import urllib.parse

print("=" * 60)
print("PASO 1: SELECT real de alumno 5 vía endpoint GET")
print("=" * 60)

r = urllib.request.urlopen(
    'http://localhost:8000/api/v1/usuarios/5?tenant_id=1', timeout=5)
a5 = json.loads(r.read())
print(f"ID={a5.get('id')}")
print(f"nombre={a5.get('nombre')}")
print(f"peso_kg={a5.get('peso_kg')!r}")
print(f"genero={a5.get('genero')!r}")

print()
print("=" * 60)
print("PASO 2: nivel-general FRESCO (nueva llamada)")
print("=" * 60)

r2 = urllib.request.urlopen(
    'http://localhost:8000/api/v1/historial-rm/alumnos/5/nivel-general?tenant_id=1', timeout=5)
print("Respuesta:")
print(json.dumps(json.loads(r2.read()), indent=2, ensure_ascii=False))

print()
print("=" * 60)
print("PASO 3: Verificar nivel-fuerza recalcula en vivo")
print("=" * 60)

params = urllib.parse.urlencode(
    {'alumno_id': 5, 'movimiento_id': 2793, 'peso_rm': 102, 'tenant_id': 1})
req = urllib.request.Request(
    f'http://localhost:8000/api/v1/historial-rm/nivel-fuerza?{params}', method='POST')
r3 = urllib.request.urlopen(req)
print("nivel-fuerza ENDPOINT (recalcula en vivo):")
print(json.dumps(json.loads(r3.read()), indent=2, ensure_ascii=False))
