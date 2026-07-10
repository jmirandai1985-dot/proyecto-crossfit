import urllib.request
import json

# Check alumno 5
r = urllib.request.urlopen(
    'http://localhost:8000/api/v1/usuarios/5?tenant_id=1')
d = json.loads(r.read())
print("GET alumno 5:")
for k, v in d.items():
    print(f"  {k}={v}")
