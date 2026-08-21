"""Verificación de los 2 fixes de seguridad Coach (tanda 1).

Datos con prefijo TEST_VALIDACION_FIXCOACH en tenant aislado + cleanup final.
Casos:
  FIX1: coach NO puede editar PR ajeno (403); alumno edita su PR (<24h) -> 200;
        admin edita cualquier PR -> 200.
  FIX2: coach sin disciplina asignada NO ve reservas por-clase (403);
        coach asignado ve su clase (200).
"""
import os
import sys
import random
from datetime import datetime, timezone

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["SENTRY_DSN"] = ""

from sqlalchemy import text as sa_text  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.database import engine  # noqa: E402

BASE = random.randint(8_000_000, 8_999_000)
TENANT_ID = BASE
UID_ALUMNO = BASE + 100
UID_COACH_A = BASE + 101   # asignado a DISC_X
UID_COACH_B = BASE + 102   # no asignado
UID_ADMIN = BASE + 103
DISC_X = BASE + 200
DISC_Y = BASE + 201
MOV = BASE + 300
PR = BASE + 400
CLASE_X = BASE + 500       # disciplina DISC_X
CLASE_Y = BASE + 501       # disciplina DISC_Y
HORARIO_BASE = BASE + 550  # horarios_base (FK NOT NULL en clases)
RES = BASE + 600

SUB = f"test-validacion-fixcoach-{BASE}"
TIDS = (TENANT_ID,)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def token(uid, rol):
    return create_access_token({
        "usuario_id": uid, "tenant_id": TENANT_ID, "rol": rol,
        "correo": f"u{uid}@fix.cl", "nombre": f"u{uid}",
    })


def seed():
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT_ID, "nom": "TEST_VALIDACION_FIXCOACH Tenant", "sub": SUB, "ca": now()})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [
                {"id": UID_ALUMNO, "tid": TENANT_ID, "rut": "TV000201", "nom": "FC Alumno",
                 "mail": f"test_validacion_fixcoach_alumno_{BASE}@test.com", "rol": "alumno"},
                {"id": UID_COACH_A, "tid": TENANT_ID, "rut": "TV000202", "nom": "FC CoachA",
                 "mail": f"test_validacion_fixcoach_coacha_{BASE}@test.com", "rol": "coach"},
                {"id": UID_COACH_B, "tid": TENANT_ID, "rut": "TV000203", "nom": "FC CoachB",
                 "mail": f"test_validacion_fixcoach_coachb_{BASE}@test.com", "rol": "coach"},
                {"id": UID_ADMIN, "tid": TENANT_ID, "rut": "TV000204", "nom": "FC Admin",
                 "mail": f"test_validacion_fixcoach_admin_{BASE}@test.com", "rol": "administrador"},
            ])
        conn.execute(sa_text(
            "INSERT INTO disciplinas (id, tenant_id, nombre, activo, requiere_coach) "
            "VALUES (:id, :tid, :nom, TRUE, TRUE)"),
            [
                {"id": DISC_X, "tid": TENANT_ID, "nom": "FC Disc X"},
                {"id": DISC_Y, "tid": TENANT_ID, "nom": "FC Disc Y"},
            ])
        conn.execute(sa_text(
            "INSERT INTO coach_disciplinas (id, tenant_id, coach_id, disciplina_id, activo) "
            "VALUES (:id, :tid, :cid, :did, TRUE)"),
            {"id": BASE + 700, "tid": TENANT_ID, "cid": UID_COACH_A, "did": DISC_X})
        conn.execute(sa_text(
            "INSERT INTO movimientos (id, tenant_id, nombre, categoria, activo) "
            "VALUES (:id, :tid, 'FC Movimiento', 'fuerza', TRUE)"),
            {"id": MOV, "tid": TENANT_ID})
        conn.execute(sa_text(
            "INSERT INTO historial_rm (id, tenant_id, alumno_id, movimiento_id, peso_kg, tipo_rm, "
            "fecha, created_at, updated_at) VALUES (:id, :tid, :aid, :mid, 100.0, 'peso', :f, :ca, :ua)"),
            {"id": PR, "tid": TENANT_ID, "aid": UID_ALUMNO, "mid": MOV, "f": "2026-08-19", "ca": now(), "ua": now()})
        conn.execute(sa_text(
            "INSERT INTO horarios (id, tenant_id, disciplina_id, dia_semana, hora_inicio, hora_fin, "
            "cupo_maximo, activo, created_at) "
            "VALUES (:id, :tid, :did, 2, '10:00', '11:00', 16, TRUE, :ca)"),
            {"id": HORARIO_BASE, "tid": TENANT_ID, "did": DISC_X, "ca": now()})
        conn.execute(sa_text(
            "INSERT INTO clases (id, tenant_id, fecha, hora_inicio, hora_fin, disciplina_id, coach_id, "
            "cupo_maximo, asistentes_confirmados, cancelada, horario_base_id, created_at, updated_at) "
            "VALUES (:id, :tid, :f, :hi, :hf, :did, :cid, 16, 0, FALSE, :hb, :ca, :ua)"),
            [
                {"id": CLASE_X, "tid": TENANT_ID, "f": "2026-08-20", "hi": "10:00", "hf": "11:00",
                 "did": DISC_X, "cid": UID_COACH_A, "hb": HORARIO_BASE, "ca": now(), "ua": now()},
                {"id": CLASE_Y, "tid": TENANT_ID, "f": "2026-08-20", "hi": "12:00", "hf": "13:00",
                 "did": DISC_Y, "cid": None, "hb": HORARIO_BASE, "ca": now(), "ua": now()},
            ])
        conn.execute(sa_text(
            "INSERT INTO reservas (id, tenant_id, alumno_id, clase_id, estado, tokens_gastados, "
            "fecha_reserva, created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :cid, 'confirmada', 1, :fr, :ca, :ua)"),
            {"id": RES, "tid": TENANT_ID, "aid": UID_ALUMNO, "cid": CLASE_X,
             "fr": now(), "ca": now(), "ua": now()})


def cleanup():
    tlist = ", ".join(str(t) for t in TIDS)
    sub = ("(SELECT id FROM usuarios WHERE correo LIKE 'test_validacion_fixcoach_%' "
           f"OR rut LIKE 'TV%' OR tenant_id IN ({tlist}))")
    pasos = [
        ("reservas", f"DELETE FROM reservas WHERE tenant_id IN ({tlist}) OR alumno_id IN {sub}"),
        ("historial_rm", f"DELETE FROM historial_rm WHERE tenant_id IN ({tlist})"),
        ("clases", f"DELETE FROM clases WHERE tenant_id IN ({tlist})"),
        ("horarios", f"DELETE FROM horarios WHERE tenant_id IN ({tlist})"),
        ("horarios_base", f"DELETE FROM horarios_base WHERE tenant_id IN ({tlist})"),
        ("coach_disciplinas", f"DELETE FROM coach_disciplinas WHERE tenant_id IN ({tlist})"),
        ("movimientos", f"DELETE FROM movimientos WHERE tenant_id IN ({tlist})"),
        ("disciplinas", f"DELETE FROM disciplinas WHERE tenant_id IN ({tlist})"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tlist}) OR correo LIKE 'test_validacion_fixcoach_%'"),
        ("tenants", f"DELETE FROM tenants WHERE id IN ({tlist}) OR subdomain LIKE 'test-validacion-fixcoach-%'"),
    ]
    for tabla, sql in pasos:
        try:
            with engine.begin() as c:
                c.execute(sa_text(sql))
        except Exception as e:
            print(f"  cleanup {tabla}: {type(e).__name__}: {str(e)[:120]}")


def check(nombre, ok, detalle=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {nombre}  {detalle}")
    return ok


def main():
    from httpx import ASGITransport, AsyncClient
    import asyncio

    async def run():
        results = []
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            hA = {"Authorization": f"Bearer {token(UID_ALUMNO, 'alumno')}"}
            hCA = {"Authorization": f"Bearer {token(UID_COACH_A, 'coach')}"}
            hCB = {"Authorization": f"Bearer {token(UID_COACH_B, 'coach')}"}
            hAdm = {"Authorization": f"Bearer {token(UID_ADMIN, 'administrador')}"}

            # FIX 1: editar PRs
            r = await c.put(f"/api/v1/historial-rm/{PR}", json={"peso_kg": 150}, headers=hCB)
            results.append(check("FIX1: coach NO asig. edita PR ajeno -> 403", r.status_code == 403, f"got {r.status_code}"))
            r = await c.put(f"/api/v1/historial-rm/{PR}", json={"peso_kg": 150}, headers=hA)
            results.append(check("FIX1: alumno edita su PR (<24h) -> 200", r.status_code == 200, f"got {r.status_code}"))
            r = await c.put(f"/api/v1/historial-rm/{PR}", json={"peso_kg": 160}, headers=hAdm)
            results.append(check("FIX1: admin edita cualquier PR -> 200", r.status_code == 200, f"got {r.status_code}"))
            r = await c.put(f"/api/v1/historial-rm/{PR}", json={"peso_kg": 170}, headers=hCA)
            results.append(check("FIX1: coach SÍ asignado tampoco edita PR -> 403", r.status_code == 403, f"got {r.status_code}"))

            # FIX 1b: crear PR (POST) — mismo criterio que el PUT
            body_pr = {"tenant_id": TENANT_ID, "alumno_id": UID_ALUMNO,
                       "movimiento_id": MOV, "peso_kg": 90, "fecha": "2026-08-19"}
            r = await c.post("/api/v1/historial-rm", json=body_pr, headers=hCA)
            results.append(check("FIX1b: coach NO puede crear PR -> 403", r.status_code == 403, f"got {r.status_code}"))
            r = await c.post("/api/v1/historial-rm", json=body_pr, headers=hCB)
            results.append(check("FIX1b: coach no asig. tampoco crea PR -> 403", r.status_code == 403, f"got {r.status_code}"))
            r = await c.post("/api/v1/historial-rm", json=body_pr, headers=hA)
            results.append(check("FIX1b: alumno crea su propio PR -> 201", r.status_code == 201, f"got {r.status_code}"))
            r = await c.post("/api/v1/historial-rm", json=body_pr, headers=hAdm)
            results.append(check("FIX1b: admin crea PR de cualquier alumno -> 201", r.status_code == 201, f"got {r.status_code}"))

            # FIX 2: reservas por-clase
            r = await c.get(f"/api/v1/reservas/por-clase/{CLASE_Y}", headers=hCB)
            results.append(check("FIX2: coach sin asig. ve reservas de clase ajena -> 403", r.status_code == 403, f"got {r.status_code}"))
            r = await c.get(f"/api/v1/reservas/por-clase/{CLASE_X}", headers=hCA)
            results.append(check("FIX2: coach asignado ve reservas de su clase -> 200", r.status_code == 200, f"got {r.status_code}"))
            r = await c.get(f"/api/v1/reservas/por-clase/{CLASE_Y}", headers=hAdm)
            results.append(check("FIX2: admin ve cualquier clase -> 200", r.status_code == 200, f"got {r.status_code}"))

        return results

    results = asyncio.run(run())
    passed = sum(1 for r in results if r)
    print(f"\nRESULTADO FIX COACH: {passed}/{len(results)} PASS")
    return passed == len(results)


if __name__ == "__main__":
    seed()
    try:
        ok = main()
    finally:
        print("[cleanup] ...")
        cleanup()
    sys.exit(0 if ok else 1)
