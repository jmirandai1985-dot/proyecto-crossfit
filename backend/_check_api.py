import requests
try:
    r = requests.get("http://localhost:8000/health", timeout=3)
    print(f"API Status: {r.status_code}")
    print(r.json())
except Exception as e:
    print(f"ERROR: {e}")
