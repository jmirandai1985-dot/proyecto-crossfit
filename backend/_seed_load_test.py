"""
Siembra el tenant aislado LOAD_TEST_BOX directamente en BD + genera tokens.json.

- 1 tenant (subdomain load-test-box-{BASE}), 1 admin, 500 alumnos con
  membresía activa (30 créditos), 1 plan, 1 disciplina + horario + clase
  (cupo=50) para el escenario B, y RUTs chilenos VÁLIDOS (módulo 11).
- Escribe k6-tests/tokens.json (500 JWTs) para que k6 autentique por VU.
No usa la API (el alta por API está rate-limiteada): inserta directo.
"""
import json
import os
import random
from datetime import datetime, timezone, timedelta

from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402
from app.core.security import create_access_token  # noqa: E402

BASE = random.randint(4_000_000, 4_999_999)
TENANT = BASE
UID_ADMIN = BASE + 1
PLAN = BASE + 2
DISC = BASE + 3
HORARIO = BASE + 4
CLASE = BASE + 5
N_ALUMNOS = 500
UID_INI = BASE + 1000

SUBDOMAIN = f"load-test-box-{BASE}"
CORREO_BASE = f"load_test_{BASE}"
K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))
TOKENS_FILE = os.path.join(K6_DIR, "tokens.json")


def dv_rut(cuerpo: int) -> str:
    """RUT chileno válido (módulo 11), formato '{cuerpo}-{dv}'."""
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
    fex_clase = now.date().isoformat()

    alumnos = []
    suscripciones = []
    for i in range(N_ALUMNOS):
        uid = UID_INI + i
        alumnos.append({
            "id": uid, "rut": dv_rut(3_000_000 + i),
            "nom": f"LOAD_TEST Alumno {i}",
            "mail": f"{CORREO_BASE}_{i}@test.com",
        })
        suscripciones.append({
            "id": uid, "uid": uid,
            "fi": fmt(now), "fe": fex,
        })

    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT, "nom": "LOAD_TEST_BOX", "sub": SUBDOMAIN, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_ADMIN, "tid": TENANT, "rut": dv_rut(3_100_000),
              "nom": "LOAD_TEST Admin", "mail": f"{CORREO_BASE}_admin@test.com", "rol": "administrador"}]
            + [{"id": a["id"], "tid": TENANT, "rut": a["rut"], "nom": a["nom"],
                "mail": a["mail"], "rol": "alumno"} for a in alumnos])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, 'LOAD TEST Mensual', 30, FALSE, 50000, 30, TRUE)"),
            {"id": PLAN, "tid": TENANT})
        conn.execute(sa_text(
            "INSERT INTO disciplinas (id, tenant_id, nombre, descripcion, es_open_box, requiere_coach, activo) "
            "VALUES (:id, :tid, 'LOAD TEST WOD', 'test', FALSE, TRUE, TRUE)"),
            {"id": DISC, "tid": TENANT})
        conn.execute(sa_text(
            "INSERT INTO horarios (id, tenant_id, disciplina_id, dia_semana, hora_inicio, hora_fin, cupo_maximo, activo) "
            "VALUES (:id, :tid, :did, 1, '18:00', '19:00', 50, TRUE)"),
            {"id": HORARIO, "tid": TENANT, "did": DISC})
        conn.execute(sa_text(
            "INSERT INTO clases (id, tenant_id, horario_base_id, disciplina_id, coach_id, fecha, "
            "hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada) "
            "VALUES (:id, :tid, :hid, :did, NULL, :fecha, '18:00', '19:00', 50, 0, FALSE)"),
            {"id": CLASE, "tid": TENANT, "hid": HORARIO, "did": DISC, "fecha": fex_clase})
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', 30, 30, :fi, :fe)"),
            [{"id": s["id"], "tid": TENANT, "uid": s["uid"], "pid": PLAN,
              "fi": s["fi"], "fe": s["fe"]} for s in suscripciones])

    tokens = [{
        "alumno_id": a["id"],
        "token": create_access_token({
            "usuario_id": a["id"], "tenant_id": TENANT, "rol": "alumno",
            "correo": a["mail"], "nombre": a["nom"],
        }),
    } for a in alumnos]
    os.makedirs(K6_DIR, exist_ok=True)
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    with open(os.path.join(K6_DIR, "load_config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "base_url": "http://localhost:8000",
            "tenant_id": TENANT,
            "clase_id": CLASE,
            "n_alumnos": N_ALUMNOS,
        }, f)

    print("=" * 60)
    print("LOAD_TEST_BOX sembrado")
    print(f"  tenant id        : {TENANT}  (subdomain {SUBDOMAIN})")
    print(f"  admin            : {UID_ADMIN}")
    print(f"  alumnos          : {N_ALUMNOS}  (ids {UID_INI}..{UID_INI + N_ALUMNOS - 1})")
    print(f"  suscripciones    : {N_ALUMNOS}  (activas, 30 creditos, exp +30d)")
    print(f"  clase cupo=50    : {CLASE}  (escenario B)")
    print(f"  tokens.json      : {TOKENS_FILE} ({len(tokens)} tokens)")
    print("=" * 60)


if __name__ == "__main__":
    main()
