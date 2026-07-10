"""
PASO 1: Revertir peso_kg/genero del alumno 5 a NULL
PASO 2: Confirmar cambios
PASO 2b: Listar alumnos y verificar datos
"""
import urllib.request
import json
import urllib.parse

print("=" * 60)
print("PASO 1: REVERTIR DATO INVENTADO DEL ALUMNO 5")
print("=" * 60)

data = json.dumps({'peso_kg': None, 'genero': None}).encode('utf-8')
req = urllib.request.Request(
    'http://localhost:8000/api/v1/usuarios/5?tenant_id=1',
    data=data, headers={'Content-Type': 'application/json'}, method='PUT'
)
r = urllib.request.urlopen(req)
resp = json.loads(r.read())
print("PUT response (sin peso_kg/genero):")
for k, v in resp.items():
    print(f"  {k}={v}")

print()
print("=" * 60)
print("PASO 2: VERIFICAR NIVEL-FUERZA TRAS REVERTIR")
print("=" * 60)

params = urllib.parse.urlencode({
    'alumno_id': 5, 'movimiento_id': 2793, 'peso_rm': 102, 'tenant_id': 1
})
req2 = urllib.request.Request(
    f'http://localhost:8000/api/v1/historial-rm/nivel-fuerza?{params}',
    method='POST'
)
r2 = urllib.request.urlopen(req2)
print("Resultado nivel-fuerza:")
print(json.dumps(json.loads(r2.read()), indent=2, ensure_ascii=False))

print()
print("=" * 60)
print("PASO 2b: LISTAR ALUMNOS")
print("=" * 60)

r3 = urllib.request.urlopen(
    'http://localhost:8000/api/v1/usuarios?tenant_id=1&rol=alumno&limit=100'
)
alumnos = json.loads(r3.read())
print(f"Total alumnos: {len(alumnos)}")

# Obtener datos completos de cada alumno via GET individual
for a in alumnos:
    aid = a['id']
    aname = a['nombre']
    r4 = urllib.request.urlopen(
        f'http://localhost:8000/api/v1/usuarios/{aid}?tenant_id=1'
    )
    detalle = json.loads(r4.read())
    pc = detalle.get('peso_kg')
    gen = detalle.get('genero')
    fn = detalle.get('fecha_nacimiento', 'N/A')
    print(f"  ID={aid}: {aname} | peso_kg={pc} | genero={gen} | fecha_nac={fn}")
