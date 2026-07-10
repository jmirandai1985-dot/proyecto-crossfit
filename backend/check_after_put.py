"""
Verificar si los datos del formulario se guardaron realmente
"""
import urllib.request
import json

API = "http://localhost:8001/api/v1"

print("=" * 60)
print("SELECT real de alumno 5 via GET")
print("=" * 60)
r = urllib.request.urlopen(f'{API}/usuarios/5?tenant_id=1')
print(json.dumps(json.loads(r.read()), indent=2, ensure_ascii=False))

print()
print("=" * 60)
print("nivel-general actual")
print("=" * 60)
r2 = urllib.request.urlopen(
    f'{API}/historial-rm/alumnos/5/nivel-general?tenant_id=1')
print(json.dumps(json.loads(r2.read()), indent=2, ensure_ascii=False))
