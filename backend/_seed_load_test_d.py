"""
Siembra LOAD_TEST_BOX para el ESCENARIO D (Bazar — stock bajo concurrencia).

- 1 tenant aislado, 1 admin, 1 plan pago (acceso completo, NO Prueba).
- N_D alumnos con suscripción paga ACTIVA (require_full_access los deja pasar).
- 1 producto con stock=30 y precio 10000.
- Escribe k6-tests/load_config.json (product_id) y tokens.json.
El fix atómico de pedidos.py garantiza que 30 compras ganen y el stock nunca
quede negativo (verificado en _verificar_escenario_d.py).
"""
import json
import os
import random
from datetime import datetime, timezone, timedelta

from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402
from app.core.security import create_access_token  # noqa: E402

BASE = random.randint(2_000_000, 2_999_999)
TENANT = BASE
UID_ADMIN = BASE + 1
PLAN_PAGO = BASE + 2
PRODUCTO = BASE + 3
N_D = 50
STOCK = 30
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
    fex = fmt(now + timedelta(days=30))

    alumnos = []
    for i in range(N_D):
        uid = UID_INI + i
        alumnos.append({
            "id": uid, "rut": dv_rut(2_500_000 + i),
            "nom": f"LOAD_TEST_D Alumno {i}",
            "mail": f"load_test_d_{BASE}_{i}@test.com",
        })

    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT, "nom": "LOAD_TEST_BOX_D", "sub": SUBDOMAIN, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_ADMIN, "tid": TENANT, "rut": dv_rut(2_400_000),
              "nom": "LOAD_TEST_D Admin", "mail": f"load_test_d_admin_{BASE}@test.com",
              "rol": "administrador"}]
            + [{"id": a["id"], "tid": TENANT, "rut": a["rut"], "nom": a["nom"],
                "mail": a["mail"], "rol": "alumno"} for a in alumnos])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, 'LOAD TEST Pago D', 30, FALSE, 50000, 30, TRUE)"),
            {"id": PLAN_PAGO, "tid": TENANT})
        # Alumnos con suscripción paga ACTIVA (acceso completo)
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', 30, 30, :fi, :fe)"),
            [{"id": a["id"], "tid": TENANT, "uid": a["id"], "pid": PLAN_PAGO,
              "fi": fmt(now), "fe": fex} for a in alumnos])
        conn.execute(sa_text(
            "INSERT INTO productos (id, tenant_id, nombre, descripcion, precio, stock, activo, created_at, updated_at) "
            "VALUES (:id, :tid, 'LOAD TEST Producto', 'test', 10000, :stock, TRUE, :ca, :ca)"),
            {"id": PRODUCTO, "tid": TENANT, "stock": STOCK, "ca": fmt(now)})

    tokens = [{"alumno_id": a["id"],
               "token": create_access_token({
                   "usuario_id": a["id"], "tenant_id": TENANT, "rol": "alumno",
                   "correo": a["mail"], "nombre": a["nom"]})}
              for a in alumnos]

    os.makedirs(K6_DIR, exist_ok=True)
    with open(os.path.join(K6_DIR, "tokens.json"), "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    with open(os.path.join(K6_DIR, "load_config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "base_url": "http://localhost:8000",
            "tenant_id": TENANT,
            "n_d": N_D,
            "product_id": PRODUCTO,
            "stock_inicial": STOCK,
        }, f)

    print("=" * 60)
    print("LOAD_TEST_BOX (Escenario D) sembrado")
    print(f"  tenant id   : {TENANT}  (subdomain {SUBDOMAIN})")
    print(f"  alumnos D   : {N_D}  (acceso completo, suscripcion paga)")
    print(f"  producto    : {PRODUCTO}  stock={STOCK}  precio=10000")
    print("=" * 60)


if __name__ == "__main__":
    main()
