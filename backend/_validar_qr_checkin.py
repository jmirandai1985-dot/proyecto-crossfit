"""
Validación dirigida del check-in por QR (autoescaneo del alumno) sobre TEST.

Misma estrategia que _fase1_validation_pg.py: corre IN-PROCESS (httpx ASGI),
siembra un tenant aislado (prefijo TEST_QR_CHECKIN), verifica que la BD sea
la branch TEST y limpia todo al final (try/finally).

Cubre (según diseño aprobado, ventana = hora_inicio - 60min <= ahora < hora_fin):
  1) rol coach/admin NO puede auto check-in            -> 403
  2) reserva con clase que ya terminó (fuera ventana)   -> sin_reserva
  3) reserva en curso (única)                           -> ok (via qr_alumno)
  4) repetir el check-in (ya marcada)                   -> ya_marcado (idempotente)
  5) dos reservas simultáneas en ventana                -> ambiguo (no marca)
  6) GET /api/v1/tenants/me (admin) devuelve public_id
  7) GET /api/v1/tenants/{public_id}/qr.svg -> 200, contenido SVG con el link

Correr: ENVIRONMENT=test python _validar_qr_checkin.py
"""
import os
import sys
import random
import uuid
import asyncio
from datetime import datetime, timedelta

os.environ["ENVIRONMENT"] = "test"
os.environ["SENTRY_DSN"] = ""

from sqlalchemy import text as sa_text  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.utils.santiago import ahora_santiago  # noqa: E402

from httpx import ASGITransport, AsyncClient  # noqa: E402

if "polished-term" not in settings.DATABASE_URL:
    print("FATAL: settings.DATABASE_URL NO apunta a la branch TEST (polished-term).")
    sys.exit(2)
print("BD_TEST:", settings.DATABASE_URL.split("@")[-1].split("/")[0])

BASE = random.randint(9_000_000, 9_990_000)
TID = BASE
UID_ALUMNO = BASE + 10
UID_COACH = BASE + 11
UID_ADMIN = BASE + 12
SUB = f"test-qr-checkin-{BASE}"
PREFIJO = "TEST_QR_CHECKIN"

engine = create_engine(settings.DATABASE_URL)

RESULTS = []


def record(nombre, esperado, obtenido, ok, extra=""):
    RESULTS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {nombre} | esperado={esperado} obtenido={obtenido} {extra}")


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _seed_base():
    """Tenant aislado + usuarios admin/coach/alumno (roles reales en BD)."""
    now = datetime.now()
    with engine.begin() as c:
        c.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, public_id, activo, created_at) "
            "VALUES (:id, :nom, :sub, :pid, TRUE, :ca)"),
            {"id": TID, "nom": f"{PREFIJO} Tenant", "sub": SUB,
             "pid": str(uuid.uuid4()), "ca": fmt(now)})
        c.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_ALUMNO, "tid": TID, "rut": "QR000001", "nom": f"{PREFIJO} Alumno",
              "mail": f"qr_alumno_{BASE}@test.com", "rol": "alumno"},
             {"id": UID_COACH, "tid": TID, "rut": "QR000002", "nom": f"{PREFIJO} Coach",
              "mail": f"qr_coach_{BASE}@test.com", "rol": "coach"},
             {"id": UID_ADMIN, "tid": TID, "rut": "QR000003", "nom": f"{PREFIJO} Admin",
              "mail": f"qr_admin_{BASE}@test.com", "rol": "administrador"}])


def _ref_ids():
    """IDs existentes de horarios/disciplinas (tenant 1) para las clases de prueba."""
    with engine.connect() as c:
        hid = c.execute(sa_text("SELECT id FROM horarios WHERE tenant_id = 1 LIMIT 1")).scalar()
        did = c.execute(sa_text("SELECT id FROM disciplinas WHERE tenant_id = 1 LIMIT 1")).scalar()
    if not hid or not did:
        raise SystemExit("FATAL: TEST sin horarios/disciplinas de tenant 1 para anclar clases")
    return hid, did


def _crear_clase(cid, hid, did, inicio_dt, fin_dt, tid=TID):
    with engine.begin() as c:
        c.execute(sa_text(
            "INSERT INTO clases (id, tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, "
            "hora_fin, cupo_maximo, asistentes_confirmados, cancelada, created_at, updated_at) "
            "VALUES (:id, :tid, :hid, :did, :fecha, :hi, :hf, 20, 0, FALSE, :ca, :ca)"),
            {"id": cid, "tid": tid, "hid": hid, "did": did,
             "fecha": inicio_dt.date(), "hi": inicio_dt.time(), "hf": fin_dt.time(),
             "ca": fmt(datetime.now())})


def _crear_reserva(rid, cid, uid, estado="confirmada", asistio=False):
    with engine.begin() as c:
        c.execute(sa_text(
            "INSERT INTO reservas (id, tenant_id, clase_id, alumno_id, estado, tokens_gastados, "
            "asistio, created_at, updated_at) "
            "VALUES (:id, :tid, :cid, :uid, :estado, 1, :asistio, :ca, :ca)"),
            {"id": rid, "tid": TID, "cid": cid, "uid": uid, "estado": estado,
             "asistio": asistio, "ca": fmt(datetime.now())})


def _token(uid):
    return create_access_token({"usuario_id": uid, "tenant_id": TID,
                                "rol": "x", "nombre": "qr", "correo": "x@test.com"})


async def run_checks():
    public_id = None
    with engine.connect() as c:
        public_id = c.execute(sa_text("SELECT public_id FROM tenants WHERE id=:i"), {"i": TID}).scalar()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as cli:
        hAdmin = {"Authorization": "Bearer " + _token(UID_ADMIN)}
        hCoach = {"Authorization": "Bearer " + _token(UID_COACH)}
        hAlu = {"Authorization": "Bearer " + _token(UID_ALUMNO)}

        # 1) coach/admin NO pueden auto check-in
        for tag, h in (("coach", hCoach), ("admin", hAdmin)):
            r = await cli.post(f"/api/v1/asistencia/qr/{public_id}/check-in", headers=h)
            record(f"QR rol {tag} -> 403", 403, r.status_code, r.status_code == 403)

        now = ahora_santiago()
        hid, did = _ref_ids()

        # 2) clase YA TERMINADA (hace 3h) -> sin_reserva
        c_out = BASE + 100
        inicio_out = now - timedelta(hours=3)
        _crear_clase(c_out, hid, did, inicio_out, inicio_out + timedelta(hours=1))
        r_out = BASE + 110
        _crear_reserva(r_out, c_out, UID_ALUMNO)
        r = await cli.post(f"/api/v1/asistencia/qr/{public_id}/check-in", headers=hAlu)
        data = r.json()
        record("QR sin reserva en ventana -> sin_reserva", "sin_reserva",
               data.get("estado"), data.get("estado") == "sin_reserva")

        # 3) clase EN CURSO (única en ventana) -> ok
        c_in = BASE + 200
        inicio_in = now + timedelta(minutes=20)
        _crear_clase(c_in, hid, did, inicio_in, inicio_in + timedelta(hours=1))
        r_in = BASE + 210
        _crear_reserva(r_in, c_in, UID_ALUMNO)
        r = await cli.post(f"/api/v1/asistencia/qr/{public_id}/check-in", headers=hAlu)
        data = r.json()
        record("QR clase en curso -> ok", "ok", data.get("estado"),
               data.get("estado") == "ok" and data.get("reserva_id") == r_in)
        # verificación en BD: asistio=True y via='qr_alumno'
        with engine.connect() as c:
            row = c.execute(sa_text(
                "SELECT asistio, asistencia_via, asistencia_marcada_por FROM reservas WHERE id=:i"),
                {"i": r_in}).first()
        record("QR marca en BD (asistio, via=qr_alumno, por=alumno)", "asistio/via",
               f"{row[0]}/{row[1]}/{row[2]}",
               row[0] is True and row[1] == "qr_alumno" and row[2] == UID_ALUMNO)

        # 4) repetir -> ya_marcado (idempotente)
        r = await cli.post(f"/api/v1/asistencia/qr/{public_id}/check-in", headers=hAlu)
        data = r.json()
        record("QR repetido -> ya_marcado", "ya_marcado", data.get("estado"),
               data.get("estado") == "ya_marcado")

        # 5) dos clases simultáneas en ventana -> ambiguo (sin marcar la 2ª)
        c_amb_a = BASE + 300
        c_amb_b = BASE + 301
        ini_a = now + timedelta(minutes=5)
        ini_b = now + timedelta(minutes=8)
        _crear_clase(c_amb_a, hid, did, ini_a, ini_a + timedelta(hours=1))
        _crear_clase(c_amb_b, hid, did, ini_b, ini_b + timedelta(hours=1))
        r_amb_a = BASE + 310
        r_amb_b = BASE + 311
        _crear_reserva(r_amb_a, c_amb_a, UID_ALUMNO)
        _crear_reserva(r_amb_b, c_amb_b, UID_ALUMNO)
        r = await cli.post(f"/api/v1/asistencia/qr/{public_id}/check-in", headers=hAlu)
        data = r.json()
        ok_amb = data.get("estado") == "ambiguo" and set(data.get("reserva_ids", [])) >= {r_amb_a, r_amb_b}
        record("QR dos en curso -> ambiguo", "ambiguo", data.get("estado"), ok_amb)
        with engine.connect() as c:
            marcada_b = c.execute(sa_text(
                "SELECT asistencia_marcada_at FROM reservas WHERE id=:i"), {"i": r_amb_b}).scalar()
        record("QR ambiguo NO marca", "None", marcada_b, marcada_b is None)

        # 6) /tenants/me (admin) devuelve public_id del propio tenant
        r = await cli.get("/api/v1/tenants/me", headers=hAdmin)
        data = r.json()
        record("GET /tenants/me -> public_id correcto", public_id,
               data.get("public_id") if r.status_code == 200 else r.status_code,
               r.status_code == 200 and data.get("public_id") == public_id)

        # 7) GET /tenants/{public_id}/qr.svg -> 200, image/svg+xml y SVG válido.
        #    NOTA: el link viaja codificado en la matriz del QR, no como texto plano.
        r = await cli.get(f"/api/v1/tenants/{public_id}/qr.svg")
        body = r.text
        record("GET qr.svg -> 200 y SVG",
               "image/svg+xml + <svg> + tamaño",
               f"{r.headers.get('content-type', '')} len={len(body)}",
               r.status_code == 200
               and "image/svg+xml" in r.headers.get("content-type", "")
               and "<svg" in body
               and len(body) > 500)


def cleanup():
    with engine.begin() as c:
        c.execute(sa_text("DELETE FROM reservas WHERE tenant_id=:t"), {"t": TID})
        c.execute(sa_text("DELETE FROM clases WHERE tenant_id=:t"), {"t": TID})
        c.execute(sa_text("DELETE FROM usuarios WHERE tenant_id=:t"), {"t": TID})
        c.execute(sa_text("DELETE FROM tenants WHERE id=:t"), {"t": TID})
    print("[cleanup] OK")


def main():
    print("=" * 72)
    print(f"RESUMEN: tenant {PREFIJO} id={TID} subdomain={SUB}")
    print("=" * 72)
    cleanup()  # leftovers de corridas previas del mismo BASE (si los hubiera)
    _seed_base()
    try:
        asyncio.run(run_checks())
    except SystemExit:
        raise
    except Exception as e:
        print("[run] ERROR:", str(e)[:400])
        import traceback
        traceback.print_exc()
    finally:
        cleanup()

    passed = sum(1 for x in RESULTS if x)
    total = len(RESULTS)
    print(f"\nRESULTADO: {passed}/{total} PASS ({'OK' if passed == total else 'FALLO - revisar'})")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

