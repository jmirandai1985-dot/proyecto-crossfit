"""Verificación de los 4 fixes del flujo de alumno nuevo.

Crea datos con prefijo TEST_VALIDACION_FIX en un tenant aislado, valida los 4
fixes por HTTP (ASGITransport sobre la app real) y limpia todo al final.
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
UID_PRUEBA = BASE + 100
UID_PAGO = BASE + 101
UID_ADMIN = BASE + 102
PLAN_PRUEBA = BASE + 200
PLAN_PAGO = BASE + 201
PROD = BASE + 300

SUB = f"test-validacion-fix-{BASE}"
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
            {"id": TENANT_ID, "nom": "TEST_VALIDACION_FIX Tenant", "sub": SUB, "ca": now()})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [
                {"id": UID_PRUEBA, "tid": TENANT_ID, "rut": "TV000101", "nom": "TEST_VALIDACION_FIX Prueba",
                 "mail": f"test_validacion_fix_prueba_{BASE}@test.com", "rol": "alumno"},
                {"id": UID_PAGO, "tid": TENANT_ID, "rut": "TV000102", "nom": "TEST_VALIDACION_FIX Pago",
                 "mail": f"test_validacion_fix_pago_{BASE}@test.com", "rol": "alumno"},
                {"id": UID_ADMIN, "tid": TENANT_ID, "rut": "TV000103", "nom": "TEST_VALIDACION_FIX Admin",
                 "mail": f"test_validacion_fix_admin_{BASE}@test.com", "rol": "administrador"},
            ])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, :nom, :cred, FALSE, :precio, 30, TRUE)"),
            [
                {"id": PLAN_PRUEBA, "tid": TENANT_ID, "nom": "Prueba", "cred": 1, "precio": 0},
                {"id": PLAN_PAGO, "tid": TENANT_ID, "nom": "Plan Pago TEST FIX", "cred": 16, "precio": 50000},
            ])
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion, puede_comprar_emergencia) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', :cred, :cred, :fi, :fe, TRUE)"),
            [
                {"id": BASE + 400, "tid": TENANT_ID, "uid": UID_PRUEBA, "pid": PLAN_PRUEBA, "cred": 1,
                 "fi": now(), "fe": now()},
                {"id": BASE + 401, "tid": TENANT_ID, "uid": UID_PAGO, "pid": PLAN_PAGO, "cred": 16,
                 "fi": now(), "fe": now()},
            ])
        conn.execute(sa_text(
            "INSERT INTO productos (id, tenant_id, nombre, precio, stock, activo) "
            "VALUES (:id, :tid, :nom, :precio, 10, TRUE)"),
            {"id": PROD, "tid": TENANT_ID, "nom": "TEST_VALIDACION_FIX Producto", "precio": 15000})

def cleanup():
    tlist = ", ".join(str(t) for t in TIDS)
    sub = ("(SELECT id FROM usuarios WHERE correo LIKE 'test_validacion_fix_%' "
           f"OR rut LIKE 'TV%' OR tenant_id IN ({tlist}))")
    pasos = [
        ("notificaciones", f"DELETE FROM notificaciones WHERE alumno_id IN {sub}"),
        ("solicitudes_planes", f"DELETE FROM solicitudes_planes WHERE tenant_id IN ({tlist}) OR alumno_id IN {sub}"),
        ("transacciones_financieras", f"DELETE FROM transacciones_financieras WHERE tenant_id IN ({tlist})"),
        ("auditoria", f"DELETE FROM auditoria WHERE tenant_id IN ({tlist})"),
        ("historial_rm", f"DELETE FROM historial_rm WHERE tenant_id IN ({tlist})"),
        ("suscripciones", f"DELETE FROM suscripciones WHERE tenant_id IN ({tlist})"),
        ("pedidos", f"DELETE FROM pedidos WHERE tenant_id IN ({tlist}) OR alumno_id IN {sub}"),
        ("productos", f"DELETE FROM productos WHERE tenant_id IN ({tlist})"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tlist}) OR correo LIKE 'test_validacion_fix_%'"),
        ("movimientos", f"DELETE FROM movimientos WHERE tenant_id IN ({tlist})"),
        ("planes", f"DELETE FROM planes WHERE tenant_id IN ({tlist})"),
        ("tenants", f"DELETE FROM tenants WHERE id IN ({tlist}) OR subdomain LIKE 'test-validacion-fix-%'"),
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
            hP = {"Authorization": f"Bearer {token(UID_PRUEBA, 'alumno')}"}
            hPag = {"Authorization": f"Bearer {token(UID_PAGO, 'alumno')}"}
            hA = {"Authorization": f"Bearer {token(UID_ADMIN, 'administrador')}"}

            # 0. es_prueba inicial
            r = await c.get("/api/v1/alumnos/me/es-prueba", headers=hP)
            results.append(check("es_prueba(alumno Prueba) = true",
                                 r.status_code == 200 and r.json()["es_prueba"] is True, f"got {r.status_code}"))
            r = await c.get("/api/v1/alumnos/me/es-prueba", headers=hPag)
            results.append(check("es_prueba(alumno Pago) = false",
                                 r.status_code == 200 and r.json()["es_prueba"] is False, f"got {r.status_code}"))

            # FIX 1: acceso limitado en backend
            r = await c.get("/api/v1/historial-rm", headers=hP)
            results.append(check("FIX1: GET /historial-rm alumno Prueba -> 403",
                                 r.status_code == 403, f"got {r.status_code}"))
            r = await c.get("/api/v1/historial-rm", headers=hPag)
            results.append(check("FIX1: GET /historial-rm alumno Pago -> 200",
                                 r.status_code == 200, f"got {r.status_code}"))
            r = await c.get("/api/v1/productos", headers=hP)
            results.append(check("FIX1: GET /productos alumno Prueba -> 403",
                                 r.status_code == 403, f"got {r.status_code}"))

            # FIX 2: bazar alumno con acceso completo
            r = await c.post("/api/v1/pedidos", json={
                "tenant_id": TENANT_ID, "alumno_id": UID_PAGO,
                "producto_id": PROD, "cantidad": 1, "estado": "pendiente",
                "voucher_url": "/static/uploads/x.jpg",
            }, headers=hPag)
            results.append(check("FIX2: POST /pedidos alumno Pago -> 201",
                                 r.status_code == 201, f"got {r.status_code} {r.text[:80]}"))
            r = await c.post("/api/v1/pedidos", json={
                "tenant_id": TENANT_ID, "alumno_id": UID_PRUEBA,
                "producto_id": PROD, "cantidad": 1,
            }, headers=hP)
            results.append(check("FIX2: POST /pedidos alumno Prueba -> 403",
                                 r.status_code == 403, f"got {r.status_code}"))

            # FIX 3 + FIX 4: solicitud del alumno Prueba, aprobar admin
            r = await c.post("/api/v1/solicitudes/solicitar", json={
                "tenant_id": TENANT_ID, "alumno_id": UID_PRUEBA,
                "plan_id": PLAN_PAGO, "voucher_url": "/static/uploads/v.jpg",
            }, headers=hP)
            results.append(check("solicitar plan (alumno Prueba) -> 201",
                                 r.status_code == 201, f"got {r.status_code} {r.text[:80]}"))
            sol_id = r.json().get("id") if r.status_code == 201 else None
            if sol_id:
                r = await c.put(f"/api/v1/solicitudes/{sol_id}/aprobar", headers=hA)
                results.append(check("aprobar solicitud (admin) -> 200",
                                     r.status_code == 200, f"got {r.status_code} {r.text[:80]}"))

        # Verificaciones directas en BD (FIX 3 y FIX 4)
        with engine.connect() as conn:
            sus = conn.execute(sa_text(
                "SELECT id, estado, plan_id FROM suscripciones "
                "WHERE usuario_id=:uid AND plan_id=:pid"),
                {"uid": UID_PRUEBA, "pid": PLAN_PRUEBA}).fetchall()
            ok3 = bool(sus) and all(s.estado == "vencido" for s in sus)
            results.append(check("FIX3: suscripcion Prueba quedó 'vencido' tras aprobar",
                                 ok3, f"estados={[s.estado for s in sus]}"))
            tx = conn.execute(sa_text(
                "SELECT id, tipo, categoria, monto, referencia_tipo, referencia_id "
                "FROM transacciones_financieras WHERE tenant_id=:t"),
                {"t": TENANT_ID}).fetchall()
            results.append(check(
                "FIX4: transacciones_financieras registrada al aprobar",
                len(tx) == 1 and tx[0].tipo == "ingreso"
                and tx[0].referencia_tipo == "suscripcion",
                f"tx={[(t.referencia_tipo, t.monto) for t in tx]}"))

        # FIX 3: es_prueba ahora false vía endpoint
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            r = await c.get("/api/v1/alumnos/me/es-prueba", headers=hP)
            results.append(check("FIX3: es_prueba(alumno) = false tras aprobar",
                                 r.status_code == 200 and r.json()["es_prueba"] is False,
                                 f"got {r.status_code}"))

        return results

    results = asyncio.run(run())
    passed = sum(1 for r in results if r)
    print(f"\nRESULTADO FIXES: {passed}/{len(results)} PASS")
    return passed == len(results)


if __name__ == "__main__":
    seed()
    try:
        ok = main()
    finally:
        print("[cleanup] ...")
        cleanup()
    sys.exit(0 if ok else 1)
