"""
Siembra LOAD_TEST_BOX para el ESCENARIO F (RMs: volumen + concurrencia).

- 1 tenant aislado, 1 admin, 1 plan pago (acceso completo).
- 4 movimientos del catálogo de niveles (2 fuerza + 2 gimnásticos).
- N_VOL=20 alumnos "históricos": ~20 registros de RM c/u (5 meses × 2
  movimientos × 2) para medir los GET de nivel/evolución/pizarra.
- N_CONC=500 alumnos para registrar 1 RM concurrente cada uno.
- Todos con peso_kg y genero (para el cálculo de nivel de fuerza).
- Escribe k6-tests/tokens.json (520 tokens, con grupo vol/conc) y
  load_config.json.
"""
import json
import os
import random
from datetime import datetime, timezone, timedelta

from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402
from app.core.security import create_access_token  # noqa: E402

BASE = random.randint(1_000_000, 1_999_999)
TENANT = BASE
UID_ADMIN = BASE + 1
PLAN_PAGO = BASE + 2
MOV_F1 = BASE + 10    # Back Squat
MOV_F2 = BASE + 11    # Deadlift
MOV_G1 = BASE + 12    # Pull-ups
MOV_G2 = BASE + 13    # Toes to Bar
N_VOL = 20
N_CONC = 500
UID_VOL_INI = BASE + 1000
UID_CONC_INI = BASE + 2000

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
    hoy = now.date()

    vol = [{"id": UID_VOL_INI + i} for i in range(N_VOL)]
    conc = [{"id": UID_CONC_INI + i} for i in range(N_CONC)]

    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT, "nom": "LOAD_TEST_BOX_F", "sub": SUBDOMAIN, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado, "
            "peso_kg, genero) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo', 70.0, 'M')"),
            [{"id": UID_ADMIN, "tid": TENANT, "rut": dv_rut(1_400_000),
              "nom": "LOAD_TEST_F Admin", "mail": f"load_test_f_admin_{BASE}@test.com",
              "rol": "administrador"}]
            + [{"id": a["id"], "tid": TENANT, "rut": dv_rut(1_500_000 + (a["id"] - UID_VOL_INI)),
                "nom": f"LOAD_TEST_F Vol {a['id']}", "mail": f"load_test_f_vol_{BASE}_{a['id']}@test.com",
                "rol": "alumno"} for a in vol]
            + [{"id": a["id"], "tid": TENANT, "rut": dv_rut(1_600_000 + (a["id"] - UID_CONC_INI)),
                "nom": f"LOAD_TEST_F Conc {a['id']}", "mail": f"load_test_f_conc_{BASE}_{a['id']}@test.com",
                "rol": "alumno"} for a in conc])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, 'LOAD TEST Pago F', 30, FALSE, 50000, 30, TRUE)"),
            {"id": PLAN_PAGO, "tid": TENANT})
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', 30, 30, :fi, :fe)"),
            [{"id": a["id"], "tid": TENANT, "uid": a["id"], "pid": PLAN_PAGO,
              "fi": fmt(now), "fe": fex} for a in vol + conc])
        conn.execute(sa_text(
            "INSERT INTO movimientos (id, tenant_id, nombre, categoria, activo) "
            "VALUES (:id, :tid, :nom, :cat, TRUE)"),
            [{"id": MOV_F1, "tid": TENANT, "nom": "Back Squat (Sentadilla Trasera)", "cat": "fuerza"},
             {"id": MOV_F2, "tid": TENANT, "nom": "Deadlift (Peso Muerto)", "cat": "fuerza"},
             {"id": MOV_G1, "tid": TENANT, "nom": "Pull-ups (Dominadas)", "cat": "gimnastico"},
             {"id": MOV_G2, "tid": TENANT, "nom": "Toes to Bar (T2B)", "cat": "gimnastico"}])
        # Historial: 20 alumnos x 20 filas (5 meses x 2 movimientos x 2)
        historial = []
        hid = BASE + 10000
        for a in vol:
            for m in range(5):
                for mov, peso in ((MOV_F1, 70 + m * 5), (MOV_G1, 8 + m)):
                    for k in range(2):
                        fecha = (hoy - timedelta(days=m * 30 + k * 14)).isoformat()
                        historial.append({
                            "id": hid, "tid": TENANT, "aid": a["id"], "mid": mov,
                            "peso": float(peso), "fecha": fecha, "ca": fmt(now),
                        })
                        hid += 1
        conn.execute(sa_text(
            "INSERT INTO historial_rm (id, tenant_id, alumno_id, movimiento_id, peso_kg, tipo_rm, fecha, "
            "created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :mid, :peso, 'peso', :fecha, :ca, :ca)"), historial)

    def _tok(uid, rol, nombre, correo):
        return create_access_token({
            "usuario_id": uid, "tenant_id": TENANT, "rol": rol,
            "correo": correo, "nombre": nombre})

    tokens = []
    for a in vol:
        tokens.append({"alumno_id": a["id"], "grupo": "vol",
                       "token": _tok(a["id"], "alumno",
                                     f"LOAD_TEST_F Vol {a['id']}",
                                     f"load_test_f_vol_{BASE}_{a['id']}@test.com")})
    for a in conc:
        tokens.append({"alumno_id": a["id"], "grupo": "conc",
                       "token": _tok(a["id"], "alumno",
                                     f"LOAD_TEST_F Conc {a['id']}",
                                     f"load_test_f_conc_{BASE}_{a['id']}@test.com")})
    admin_token = _tok(UID_ADMIN, "administrador", "LOAD_TEST_F Admin",
                       f"load_test_f_admin_{BASE}@test.com")

    os.makedirs(K6_DIR, exist_ok=True)
    with open(os.path.join(K6_DIR, "tokens.json"), "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    with open(os.path.join(K6_DIR, "load_config.json"), "w", encoding="utf-8") as f:
        json.dump({
            "base_url": "http://localhost:8000",
            "tenant_id": TENANT,
            "n_vol": N_VOL,
            "n_conc": N_CONC,
            "mov_f1": MOV_F1,
            "mov_g1": MOV_G1,
            "admin_token": admin_token,
            "historial_rows": len(historial),
        }, f)

    print("=" * 60)
    print("LOAD_TEST_BOX (Escenario F) sembrado")
    print(f"  tenant id    : {TENANT}  (subdomain {SUBDOMAIN})")
    print(f"  alumnos vol  : {N_VOL}  (x {len(historial)//N_VOL} filas de RM c/u = {len(historial)} filas)")
    print(f"  alumnos conc : {N_CONC}")
    print(f"  movimientos  : 4 (Back Squat, Deadlift, Pull-ups, T2B)")
    print(f"  tokens       : {len(tokens)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
