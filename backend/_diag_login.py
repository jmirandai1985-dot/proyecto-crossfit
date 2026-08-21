"""Diagnóstico: 1 login con alumno LOAD_TEST_E (password bcrypt real)."""
import json
import os
import time
import requests

K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))
with open(os.path.join(K6_DIR, "load_config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
BASE = cfg["base_url"]
TENANT = cfg["tenant_id"]
PWD = cfg["password"]

correo = f"load_test_e_{TENANT}_0@test.com"
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/auth/login",
                  json={"correo": correo, "password": PWD}, timeout=20)
print(f"login {correo}: {r.status_code} ({time.time()-t0:.2f}s) body={str(r.text)[:80]}")
