"""Verificación ajustes cobertura de emergencia.

Caso: coach A (sin disciplina asignada) cubre una clase con modo_emergencia=true.
Se verifica: operación permitida (200), clase.coach_id -> coach A,
cobertura_emergencia con coach_original_id correcto, y notificación in-app al
admin (tipo='emergencia'). Datos TEST_VALIDACION_EMERG + cleanup.
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
UID_ADMIN = BASE + 100
UID_COACH_A = BASE + 101       # sustituto (no asignado a DISC_X)
UID_COACH_ORIG = BASE + 102    # coach titular
UID_ALUMNO = BASE + 103
DISC_X = BASE + 200
HORARIO = BASE + 300
CLASE_X = BASE + 400
RES = BASE + 500

SUB = f"test-validacion-emerg-{BASE}"


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
            {"id": TENANT_ID, "nom": "TEST_VALIDACION_EMERG Tenant", "sub": SUB, "ca": now()})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [
                {"id": UID_ADMIN, "tid": TENANT_ID, "rut": "TV000401", "nom": "EM Admin",
                 "mail": f"test_validacion_emerg_admin_{BASE}@test.com", "rol": "administrador"},
                {"id": UID_COACH_A, "tid": TENANT_ID, "rut": "TV000402", "nom": "EM CoachA",
                 "mail": f"test_validacion_emerg_coacha_{BASE}@test.com", "rol": "coach"},
                {"id": UID_COACH_ORIG, "tid": TENANT_ID, "rut": "TV000403", "nom": "EM CoachOrig",
                 "mail": f"test_validacion_emerg_orig_{BASE}@test.com", "rol": "coach"},
                {"id": UID_ALUMNO, "tid": TENANT_ID, "rut": "TV000404", "nom": "EM Alumno",
                 "mail": f"test_validacion_emerg_alumno_{BASE}@test.com", "rol": "alumno"},
            ])
        conn.execute(sa_text(
            "INSERT INTO disciplinas (id, tenant_id, nombre, activo, requiere_coach) "
            "VALUES (:id, :tid, :nom, TRUE, TRUE)"),
            {"id": DISC_X, "tid": TENANT_ID, "nom": "EM Disc X"})
        conn.execute(sa_text(
            "INSERT INTO horarios (id, tenant_id, disciplina_id, dia_semana, hora_inicio, hora_fin, "
            "cupo_maximo, activo, created_at) VALUES (:id, :tid, :did, 2, '10:00', '11:00', 16, TRUE, :ca)"),
            {"id": HORARIO, "tid": TENANT_ID, "did": DISC_X, "ca": now()})
        conn.execute(sa_text(
            "INSERT INTO clases (id, tenant_id, fecha, hora_inicio, hora_fin, disciplina_id, coach_id, "
            "cupo_maximo, asistentes_confirmados, cancelada, horario_base_id, created_at, updated_at) "
            "VALUES (:id, :tid, :f, '10:00', '11:00', :did, :cid, 16, 0, FALSE, :hb, :ca, :ua)"),
            {"id": CLASE_X, "tid": TENANT_ID, "f": "2026-08-20", "did": DISC_X,
             "cid": UID_COACH_ORIG, "hb": HORARIO, "ca": now(), "ua": now()})
        conn.execute(sa_text(
            "INSERT INTO reservas (id, tenant_id, alumno_id, clase_id, estado, tokens_gastados, "
            "fecha_reserva, created_at, updated_at) VALUES (:id, :tid, :aid, :cid, 'confirmada', 1, :fr, :ca, :ua)"),
            {"id": RES, "tid": TENANT_ID, "aid": UID_ALUMNO, "cid": CLASE_X,
             "fr": now(), "ca": now(), "ua": now()})


def cleanup():
    tl = str(TENANT_ID)
    sub = ("(SELECT id FROM usuarios WHERE correo LIKE 'test_validacion_emerg_%' "
           f"OR rut LIKE 'TV%' OR tenant_id IN ({tl}))")
    pasos = [
        ("notificaciones", f"DELETE FROM notificaciones WHERE alumno_id IN {sub}"),
        ("notificaciones_enviadas", f"DELETE FROM notificaciones_enviadas WHERE alumno_id IN {sub}"),
        ("reservas", f"DELETE FROM reservas WHERE tenant_id IN ({tl})"),
        ("cobertura_emergencia", f"DELETE FROM cobertura_emergencia WHERE tenant_id IN ({tl})"),
        ("clases", f"DELETE FROM clases WHERE tenant_id IN ({tl})"),
        ("horarios", f"DELETE FROM horarios WHERE tenant_id IN ({tl})"),
        ("coach_disciplinas", f"DELETE FROM coach_disciplinas WHERE tenant_id IN ({tl})"),
        ("disciplinas", f"DELETE FROM disciplinas WHERE tenant_id IN ({tl})"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tl}) OR correo LIKE 'test_validacion_emerg_%'"),
        ("tenants", f"DELETE FROM tenants WHERE id IN ({tl}) OR subdomain LIKE 'test-validacion-emerg-%'"),
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
            hCA = {"Authorization": f"Bearer {token(UID_COACH_A, 'coach')}"}

            # Coach A (no asignado a DISC_X) cubre la clase en emergencia
            r = await c.put(f"/api/v1/reservas/{RES}/asistencia?modo_emergencia=true",
                            json={"asistio": True}, headers=hCA)
            results.append(check("EMERG: operación en modo emergencia permitida -> 200",
                                 r.status_code == 200, f"got {r.status_code} {r.text[:80]}"))

        with engine.connect() as conn:
            # clase.coach_id actualizado al sustituto
            cl = conn.execute(sa_text(
                "SELECT coach_id FROM clases WHERE id=:id"), {"id": CLASE_X}).fetchone()
            results.append(check("AJUSTE2: clase.coach_id = coach sustituto",
                                 cl and cl.coach_id == UID_COACH_A, f"coach_id={cl.coach_id if cl else None}"))

            # cobertura_emergencia con coach_original_id correcto
            ce = conn.execute(sa_text(
                "SELECT coach_id, usuario_id, coach_original_id, clase_id, disciplina_id, accion "
                "FROM cobertura_emergencia WHERE tenant_id=:t"),
                {"t": TENANT_ID}).fetchone()
            ok_ce = (ce is not None and ce.coach_id == UID_COACH_A
                     and ce.usuario_id == UID_COACH_A
                     and ce.coach_original_id == UID_COACH_ORIG
                     and ce.clase_id == CLASE_X and ce.accion == "marcar_asistencia")
            results.append(check("AJUSTE2: cobertura_emergencia con original/sustituto correctos",
                                 ok_ce, f"row={tuple(ce) if ce else None}"))

            # notificación in-app al admin
            nf = conn.execute(sa_text(
                "SELECT alumno_id, tipo, mensaje FROM notificaciones "
                "WHERE alumno_id=:aid AND tipo='emergencia'"),
                {"aid": UID_ADMIN}).fetchall()
            ok_nf = len(nf) == 1 and "EM CoachA" in nf[0].mensaje and f"clase #{CLASE_X}" in nf[0].mensaje
            results.append(check("AJUSTE1: notificación in-app al admin con coach/clase",
                                 ok_nf, f"notif={[(x.tipo, x.mensaje[:60]) for x in nf]}"))

        return results

    results = asyncio.run(run())
    passed = sum(1 for r in results if r)
    print(f"\nRESULTADO EMERGENCIA: {passed}/{len(results)} PASS")
    return passed == len(results)


if __name__ == "__main__":
    seed()
    try:
        ok = main()
    finally:
        print("[cleanup] ...")
        cleanup()
    sys.exit(0 if ok else 1)
