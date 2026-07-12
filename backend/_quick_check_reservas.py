import requests
import json
r = requests.get("http://localhost:8000/api/v1/reservas",
                 params={"tenant_id": 1, "usuario_id": 5, "limit": 200})
data = r.json()
print(f"Total reservas: {len(data)}")
print(json.dumps(data, indent=2, ensure_ascii=False))
