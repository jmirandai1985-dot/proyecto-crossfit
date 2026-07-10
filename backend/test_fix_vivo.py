"""
FRESCO: Verificar fix recalculo en vivo
Usa puerto 8001 (nuevo servidor)
"""
import urllib.request
import json
import urllib.parse

API = "http://localhost:8001/api/v1"

print("=" * 60)
print("PASO 1: peso_kg/genero del alumno 5")
print("=" * 60)
r = urllib.request.urlopen(f'{API}/usuarios/5?tenant_id=1')
a5 = json.loads(r.read())
print(f"peso_kg={a5.get('peso_kg')!r}, genero={a5.get('genero')!r}")

print()
print("=" * 60)
print("PASO 2: nivel-general CON pesos NULL (debe ser 'Sin datos')")
print("=" * 60)
r2 = urllib.request.urlopen(
    f'{API}/historial-rm/alumnos/5/nivel-general?tenant_id=1')
print(json.dumps(json.loads(r2.read()), indent=2, ensure_ascii=False))

print()
print("=" * 60)
print("PASO 3: Set peso_kg=78, genero=F (dato de prueba EXPLICITO)")
print("=" * 60)
data = json.dumps({'peso_kg': 78, 'genero': 'F'}).encode('utf-8')
req = urllib.request.Request(f'{API}/usuarios/5?tenant_id=1',
                             data=data, headers={'Content-Type': 'application/json'}, method='PUT')
urllib.request.urlopen(req)
print("✅ peso_kg=78, genero=F guardado (PRUEBA - se revertira despues)")

print()
print("=" * 60)
print("PASO 4: nivel-general CON datos (debe recalcular en vivo)")
print("=" * 60)
r4 = urllib.request.urlopen(
    f'{API}/historial-rm/alumnos/5/nivel-general?tenant_id=1')
print(json.dumps(json.loads(r4.read()), indent=2, ensure_ascii=False))

print()
print("=" * 60)
print("PASO 5: Revertir a NULL")
print("=" * 60)
data = json.dumps({'peso_kg': None, 'genero': None}).encode('utf-8')
req = urllib.request.Request(f'{API}/usuarios/5?tenant_id=1',
                             data=data, headers={'Content-Type': 'application/json'}, method='PUT')
urllib.request.urlopen(req)
print("✅ Revertido a NULL")

print()
print("=" * 60)
print("PASO 6: Confirmar que volvio a 'Sin datos'")
print("=" * 60)
r6 = urllib.request.urlopen(
    f'{API}/historial-rm/alumnos/5/nivel-general?tenant_id=1')
print(json.dumps(json.loads(r6.read()), indent=2, ensure_ascii=False))
