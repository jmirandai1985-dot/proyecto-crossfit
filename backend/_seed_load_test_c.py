"""
Siembra LOAD_TEST_BOX para el ESCENARIO C (compra de plan + doble-aprobación).

- 1 tenant aislado, 1 admin, 1 plan 'Prueba' y 1 plan pago (30 créditos).
- N_C alumnos, cada uno con suscripción 'Prueba' ACTIVA (para validar el fix
  P3b: al aprobar el pago, la Prueba debe pasar a 'vencido').
- N_C solicitudes de plan PENDING (una por alumno) listas para aprobar.
- Escribe k6-tests/load_config.json (admin_token, solicitudes[]) y tokens.json.
"""
import json
import os
import random
from datetime import datetime, timezone, timedelta

from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402
from app.core.security import create_access_token  # noqa: E402

BASE = random.randint(3_000_000, 3_999_999)
TENANT = BASE
UID_ADMIN = BASE + 1
PLAN_PRUEBA = BASE + 2
PLAN_PAGO = BASE + 3
N_C = 20
UID_INI = BASE + 1000

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
    fex_prueba = fmt(now + timedelta(days=7))

    alumnos = []
    for i in range(N_C):
        uid = UID_INI + i
        alumnos.append({
            "id": uid, "rut": dv_rut(3_500_000 + i),
            "nom": f"LOAD_TEST_C Alumno {i}",
            "mail": f"load_test_c_{BASE}_{i}@test.com",
        })

    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT, "nom": "LOAD_TEST_BOX_C", "sub": SUBDOMAIN, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_ADMIN, "tid": TENANT, "rut": dv_rut(3_400_000),
              "nom": "LOAD_TEST_C Admin", "mail": f"load_test_c_admin_{BASE}@test.com",
              "rol": "administrador"}]
            + [{"id": a["id"], "tid": TENANT, "rut": a["rut"], "nom": a["nom"],
                "mail": a["mail"], "rol": "alumno"} for a in alumnos])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, :nom, :cred, FALSE, :precio, :dias, TRUE)"),
            [{"id": PLAN_PRUEBA, "tid": TENANT, "nom": "Prueba", "cred": 1, "precio": 0, "dias": 7},
             {"id": PLAN_PAGO, "tid": TENANT, "nom": "LOAD TEST Pago", "cred": 30, "precio": 50000, "dias": 30}])
        # Cada alumno con suscripción Prueba ACTIVA (para el fix P3b)
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', 1, 1, :fi, :fe)"),
            [{"id": a["id"], "tid": TENANT, "uid": a["id"], "pid": PLAN_PRUEBA,
              "fi": fmt(now), "fe": fex_prueba} for a in alumnos])
        # N_C solicitudes pending (una por alumno, plan pago)
        conn.execute(sa_text(
            "INSERT INTO solicitudes_planes (id, tenant_id, alumno_id, plan_id, estado, voucher_url, "
            "created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :pid, 'pending', NULL, :ca, :ca)"),
            [{"id": BASE + 2000 + i, "tid": TENANT, "aid": a["id"], "pid": PLAN_PAGO, "ca": fmt(now)}
             for i, a in enumerate(alumnos)])

    # tokens de alumnos + admin
    tokens = [{"alumno_id": a["id"],
               "token": create_access_token({
                   "usuario_id": a["id"], "tenant_id": TENANT, "rol": "alumno",
                   "correo": a["mail"], "nombre": a["nom"]})}
              for a in alumnos]
    admin_token = create_access_token({
        "usuario_id": UID_ADMIN, "tenant_id": TENANT, "rol": "administrador",
        "correo": f"load_test_c_admin_{BASE}@test.com", "nombre": "LOAD_TEST_C Admin"})
    solicitudes = [{"solicitud_id": BASE + 2000 + i, "alumno_id": a["id"]}
                   for i, a in enumerate(alumnos)]

    os.makedirs(K6_DIR, exist_ok=True)
    with open(os.path.join(K6_DIR, "tokens.json"), "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    with open(os.path.join(K6_DIR, "load_config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "base_url": "http://localhost:8000",
            "tenant_id": TENANT,
            "n_c": N_C,
            "plan_pago_id": PLAN_PAGO,
            "admin_token": admin_token,
            "solicitudes": solicitudes,
        }, f)

    print("=" * 60)
    print("LOAD_TEST_BOX (Escenario C) sembrado")
    print(f"  tenant id       : {TENANT}  (subdomain {SUBDOMAIN})")
    print(f"  admin           : {UID_ADMIN}")
    print(f"  alumnos C       : {N_C}  (con suscripcion Prueba ACTIVA)")
    print(f"  solicitudes     : {N_C}  (pending, plan pago {PLAN_PAGO})")
    print(f"  load_config.json: {os.path.join(K6_DIR, 'load_config.json')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
