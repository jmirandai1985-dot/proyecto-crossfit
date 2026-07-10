import urllib.request
import json
import urllib.parse

API = "http://localhost:8000/api/v1"
TENANT = "1"


def api_put(path, data):
    qs = '&'.join(f"{k}={v}" for k, v in data.items())
    url = f"{API}{path}?{qs}"
    req = urllib.request.Request(url, method='PUT')
    return json.loads(urllib.request.urlopen(req).read())


# Fix Chest to Bar (C2B)  ID=2802 -> gimnastico
print("Fixing Chest to Bar (C2B) -> gimnastico...")
api_put("/movimientos/2802", {"categoria": "gimnastico", "tenant_id": TENANT})
print("OK")

# Fix Wall Balls ID=2814 -> fuerza (es lanzamiento de balon con peso)
print("Fixing Wall Balls -> fuerza...")
api_put("/movimientos/2814", {"categoria": "fuerza", "tenant_id": TENANT})
print("OK")

# Verify all movements with categoria
print("\n=== MOVIMIENTOS CON CATEGORIA ===")
r = urllib.request.urlopen(f"{API}/movimientos?tenant_id={TENANT}")
for m in json.loads(r.read()):
    cat = m.get("categoria", "?")
    print(f"  {m['nombre']:40s} -> {cat}")
