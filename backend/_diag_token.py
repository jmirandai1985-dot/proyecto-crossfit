"""Diagnóstico rápido: prueba 1 token + 1 reserva real contra el backend en vivo."""
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
CLASE = cfg["clase_id"]
a = tokens[0]
h = {"Authorization": f"Bearer {a['token']}"}

print(f"token alumno {a['alumno_id']} -> clase {CLASE}")
t0 = time.time()
r1 = requests.get(f"{BASE}/api/v1/planes", headers=h, timeout=15)
print(f"GET /planes  : {r1.status_code}  ({time.time()-t0:.2f}s)  body={str(r1.text)[:80]}")
t0 = time.time()
r2 = requests.post(f"{BASE}/api/v1/reservas",
                   json={"clase_id": CLASE, "alumno_id": a["alumno_id"]},
                   headers=h, timeout=30)
print(f"POST /reservas: {r2.status_code}  ({time.time()-t0:.2f}s)  body={str(r2.text)[:120]}")
