import urllib.request
import json

# Consultar alumno 5
r = urllib.request.urlopen(
    'http://localhost:8000/api/v1/usuarios/5?tenant_id=1')
data = json.loads(r.read())
print(json.dumps(data, indent=2, ensure_ascii=False))
