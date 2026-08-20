"""
Siembra LOAD_TEST_BOX para el ESCENARIO E (mix final: apertura de temporada).

- 1 tenant aislado, 1 admin, 1 plan pago, 200 alumnos con acceso completo
  (suscripción paga + password bcrypt real para LOGIN), clase cupo=30,
  producto stock=20, y 15 solicitudes pending (compra de plan).
- Todos los datos de prueba usan prefijo LOAD_TEST (identificables).
- Escribe k6-tests/tokens.json y load_config.json.
"""
import bcrypt
import json
import os
import random
from datetime import datetime, timezone, timedelta

from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402
from app.core.security import create_access_token  # noqa: E402

BASE = random.randint(600_000, 699_999)
TENANT = BASE
UID_ADMIN = BASE + 1
PLAN_PAGO = BASE + 2
DISC = BASE + 3
HORARIO = BASE + 4
CLASE = BASE + 5
PRODUCTO = BASE + 6
N_ALUM = 200
UID_INI = BASE + 1000
STOCK = 20
CUPO = 30
N_SOL = 15
PASSWORD = "Test1234!"

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
    phash = bcrypt.hashpw(PASSWORD.encode()[:72], bcrypt.gensalt()).decode()

    alumnos = [{"id": UID_INI + i} for i in range(N_ALUM)]

    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT, "nom": "LOAD_TEST_BOX_E", "sub": SUBDOMAIN, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, :ph, :rol, TRUE, 'activo')"),
            [{"id": UID_ADMIN, "tid": TENANT, "rut": dv_rut(600_001),
              "nom": "LOAD_TEST_E Admin", "mail": f"load_test_e_admin_{BASE}@test.com",
              "ph": phash, "rol": "administrador"}]
            + [{"id": a["id"], "tid": TENANT, "rut": dv_rut(610_000 + i),
                "nom": f"LOAD_TEST_E Alumno {i}", "mail": f"load_test_e_{BASE}_{i}@test.com",
                "ph": phash, "rol": "alumno"} for i, a in enumerate(alumnos)])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, 'LOAD TEST Pago E', 30, FALSE, 50000, 30, TRUE)"),
            {"id": PLAN_PAGO, "tid": TENANT})
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', 30, 30, :fi, :fe)"),
            [{"id": a["id"], "tid": TENANT, "uid": a["id"], "pid": PLAN_PAGO,
              "fi": fmt(now), "fe": fex} for a in alumnos])
        conn.execute(sa_text(
            "INSERT INTO disciplinas (id, tenant_id, nombre, descripcion, es_open_box, requiere_coach, activo) "
            "VALUES (:id, :tid, 'LOAD TEST E WOD', 'test', FALSE, TRUE, TRUE)"),
            {"id": DISC, "tid": TENANT})
        conn.execute(sa_text(
            "INSERT INTO horarios (id, tenant_id, disciplina_id, dia_semana, hora_inicio, hora_fin, cupo_maximo, activo) "
            "VALUES (:id, :tid, :did, 1, '18:00', '19:00', :cupo, TRUE)"),
            {"id": HORARIO, "tid": TENANT, "did": DISC, "cupo": CUPO})
        conn.execute(sa_text(
            "INSERT INTO clases (id, tenant_id, horario_base_id, disciplina_id, coach_id, fecha, "
            "hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada) "
            "VALUES (:id, :tid, :hid, :did, NULL, :fecha, '18:00', '19:00', :cupo, 0, FALSE)"),
            {"id": CLASE, "tid": TENANT, "hid": HORARIO, "did": DISC,
             "fecha": now.date().isoformat(), "cupo": CUPO})
        conn.execute(sa_text(
            "INSERT INTO productos (id, tenant_id, nombre, descripcion, precio, stock, activo, created_at, updated_at) "
            "VALUES (:id, :tid, 'LOAD TEST Producto E', 'test', 10000, :stock, TRUE, :ca, :ca)"),
            {"id": PRODUCTO, "tid": TENANT, "stock": STOCK, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO solicitudes_planes (id, tenant_id, alumno_id, plan_id, estado, voucher_url, "
            "created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :pid, 'pending', NULL, :ca, :ca)"),
            [{"id": BASE + 3000 + i, "tid": TENANT, "aid": alumnos[i]["id"], "pid": PLAN_PAGO,
              "ca": fmt(now)} for i in range(N_SOL)])

    def _tok(uid, rol, nombre, correo):
        return create_access_token({
            "usuario_id": uid, "tenant_id": TENANT, "rol": rol,
            "correo": correo, "nombre": nombre})

    tokens = [{"alumno_id": a["id"], "grupo": "mix",
               "token": _tok(a["id"], "alumno",
                             f"LOAD_TEST_E Alumno {i}",
                             f"load_test_e_{BASE}_{i}@test.com")}
              for i, a in enumerate(alumnos)]
    admin_token = _tok(UID_ADMIN, "administrador", "LOAD_TEST_E Admin",
                       f"load_test_e_admin_{BASE}@test.com")

    os.makedirs(K6_DIR, exist_ok=True)
    with open(os.path.join(K6_DIR, "tokens.json"), "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    with open(os.path.join(K6_DIR, "load_config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "base_url": "http://localhost:8000",
            "tenant_id": TENANT,
            "n_alumnos": N_ALUM,
            "clase_id": CLASE,
            "product_id": PRODUCTO,
            "plan_pago_id": PLAN_PAGO,
            "admin_token": admin_token,
            "password": PASSWORD,
            "solicitudes": [{"solicitud_id": BASE + 3000 + i, "alumno_id": alumnos[i]["id"]}
                            for i in range(N_SOL)],
        }, f)

    print("=" * 60)
    print("LOAD_TEST_BOX (Escenario E) sembrado")
    print(f"  tenant id    : {TENANT}  (subdomain {SUBDOMAIN})")
    print(f"  alumnos mix  : {N_ALUM}  (password bcrypt real para LOGIN)")
    print(f"  clase cupo   : {CLASE}  ({CUPO})  | producto stock: {PRODUCTO} ({STOCK})")
    print(f"  solicitudes  : {N_SOL}  (pending, para aprobar en el mix)")
    print(f"  admin token  : ok  | password: {PASSWORD}")
    print("=" * 60)


if __name__ == "__main__":
    main()
