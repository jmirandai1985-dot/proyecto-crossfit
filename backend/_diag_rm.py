"""Diagnóstico: 1 POST /historial-rm con un token 'conc' para ver el response."""
import json
import os
import time
import requests

K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))
with open(os.path.join(K6_DIR, "load_config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
with open(os.path.join(K6_DIR, "tokens.json"), encoding="utf-8") as f:
    tokens = json.load(f)

BASE = cfg["base_url"]
MOV = cfg["mov_g1"]
a = next(t for t in tokens if t["grupo"] == "conc")
h = {"Authorization": f"Bearer {a['token']}", "Content-Type": "application/json"}

body = {"alumno_id": a["alumno_id"], "movimiento_id": MOV, "peso_kg": 12,
        "fecha": "2026-08-19"}
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/historial-rm", json=body, headers=h, timeout=30)
print(f"POST /historial-rm: {r.status_code} ({time.time()-t0:.2f}s) body={str(r.text)[:200]}")
