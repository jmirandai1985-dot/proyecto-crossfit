import urllib.request
import json

# Consultar movimientos
r = urllib.request.urlopen(
    'http://localhost:8000/api/v1/movimientos?tenant_id=1')
data = json.loads(r.read())
for m in data:
    print(f"ID={m['id']}: {m['nombre']}")
