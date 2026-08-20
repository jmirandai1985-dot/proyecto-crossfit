"""
Siembra LOAD_TEST_BOX para el ESCENARIO A (registro masivo).

Solo crea el tenant (necesario por FK de usuarios) + un admin. Los alumnos los
crea el propio endpoint de registro. Escribe k6-tests/load_config.json.
"""
import json
import os
import random
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402

BASE = random.randint(700_000, 799_999)
TENANT = BASE
UID_ADMIN = BASE + 1
N_A = 500

SUBDOMAIN = f"load-test-box-{BASE}"
K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))


def dv_rut(cuerpo: int) -> str:
    suma = 0
    mult = 2
    for d in reversed(str(cuerpo)):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    resto = suma % 11
    dv = 11 - resto
    if dv == 11:
        dv = 0
    elif dv == 10:
        dv = "K"
    return f"{cuerpo}-{dv}"


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def main():
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT, "nom": "LOAD_TEST_BOX_A", "sub": SUBDOMAIN, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', 'administrador', TRUE, 'activo')"),
            {"id": UID_ADMIN, "tid": TENANT, "rut": dv_rut(700_001),
             "nom": "LOAD_TEST_A Admin", "mail": f"load_test_a_admin_{BASE}@test.com"})

    os.makedirs(K6_DIR, exist_ok=True)
    with open(os.path.join(K6_DIR, "load_config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "base_url": "http://localhost:8000",
            "tenant_id": TENANT,
            "n_a": N_A,
        }, f)

    print("=" * 60)
    print("LOAD_TEST_BOX (Escenario A) sembrado")
    print(f"  tenant id : {TENANT}  (subdomain {SUBDOMAIN})")
    print(f"  admin     : {UID_ADMIN}")
    print(f"  NOTA      : rate limit registro = 5/hora/IP -> se miden 5x201 + 495x429")
    print("=" * 60)


if __name__ == "__main__":
    main()
