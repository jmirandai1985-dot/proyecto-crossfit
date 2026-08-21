"""
Validación runtime de los fixes S1 (IDOR voucher) y S2 (cross-tenant en
aprobar/rechazar) contra Postgres real.

Aísla todo en 2 tenants de prueba marcados TEST_AUDIT_ADMIN (subdomain
test-audit-admin-*, correo test_audit_admin_*, rut TAA*) y limpia al final
(try/finally, doble pasada tolerante a FKs + borrado de archivos subidos).
NO imprime connection string ni credenciales.
"""
import os
import sys
import base64
import random
import asyncio
from datetime import datetime, timezone

os.environ["SENTRY_DSN"] = ""  # evitar envíos a Sentry durante la validación

from sqlalchemy import text as sa_text  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.database import engine  # noqa: E402

PREFIX = "TEST_AUDIT_ADMIN"  # marcador inconfundible (también para borrado manual)
BASE = random.randint(7_000_000, 7_999_000)

TENANT_A = BASE           # tenant A (box A)
TENANT_B = BASE + 1       # tenant B (box B)
UID_A_ADMIN = BASE + 10
UID_A_ALUMNO = BASE + 11
UID_A_COACH = BASE + 12
UID_B_ADMIN = BASE + 20
UID_B_ALUMNO = BASE + 21
PLAN_A = BASE + 30
PLAN_B = BASE + 31

TIDS = f"{TENANT_A},{TENANT_B}"

SUBDOMAIN_A = f"test-audit-admin-{BASE}"
SUBDOMAIN_B = f"test-audit-admin-{BASE}b"
CORREO = {
    UID_A_ADMIN: f"test_audit_admin_a_{BASE}@test.com",
    UID_A_ALUMNO: f"test_audit_admin_alumno_a_{BASE}@test.com",
    UID_A_COACH: f"test_audit_admin_coach_a_{BASE}@test.com",
    UID_B_ADMIN: f"test_audit_admin_b_{BASE}@test.com",
    UID_B_ALUMNO: f"test_audit_admin_alumno_b_{BASE}@test.com",
}
RUT = {
    UID_A_ADMIN: "TAA001", UID_A_ALUMNO: "TAA002", UID_A_COACH: "TAA003",
    UID_B_ADMIN: "TAA004", UID_B_ALUMNO: "TAA005",
}
NOMBRE = {
    UID_A_ADMIN: "TEST_AUDIT_ADMIN Admin A", UID_A_ALUMNO: "TEST_AUDIT_ADMIN Alumno A",
    UID_A_COACH: "TEST_AUDIT_ADMIN Coach A", UID_B_ADMIN: "TEST_AUDIT_ADMIN Admin B",
    UID_B_ALUMNO: "TEST_AUDIT_ADMIN Alumno B",
}

UPLOAD_DIR = os.path.realpath(os.path.join(
    os.path.dirname(__file__), "app", "static", "uploads"))
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
VOUCHER_FILES = []  # rutas absolutas de vouchers subidos (para cleanup)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def seed():
    """Crea tenants/usuarios/planes de prueba en UNA transacción (all-or-nothing)."""
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            [{"id": TENANT_A, "nom": "TEST_AUDIT_ADMIN Box A", "sub": SUBDOMAIN_A, "ca": fmt(now)},
             {"id": TENANT_B, "nom": "TEST_AUDIT_ADMIN Box B", "sub": SUBDOMAIN_B, "ca": fmt(now)}])
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_A_ADMIN, "tid": TENANT_A, "rut": RUT[UID_A_ADMIN], "nom": NOMBRE[UID_A_ADMIN],
              "mail": CORREO[UID_A_ADMIN], "rol": "administrador"},
             {"id": UID_A_ALUMNO, "tid": TENANT_A, "rut": RUT[UID_A_ALUMNO], "nom": NOMBRE[UID_A_ALUMNO],
              "mail": CORREO[UID_A_ALUMNO], "rol": "alumno"},
             {"id": UID_A_COACH, "tid": TENANT_A, "rut": RUT[UID_A_COACH], "nom": NOMBRE[UID_A_COACH],
              "mail": CORREO[UID_A_COACH], "rol": "coach"},
             {"id": UID_B_ADMIN, "tid": TENANT_B, "rut": RUT[UID_B_ADMIN], "nom": NOMBRE[UID_B_ADMIN],
              "mail": CORREO[UID_B_ADMIN], "rol": "administrador"},
             {"id": UID_B_ALUMNO, "tid": TENANT_B, "rut": RUT[UID_B_ALUMNO], "nom": NOMBRE[UID_B_ALUMNO],
              "mail": CORREO[UID_B_ALUMNO], "rol": "alumno"}])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, :nom, 16, FALSE, 50000, 30, TRUE)"),
            [{"id": PLAN_A, "tid": TENANT_A, "nom": "TEST_AUDIT_ADMIN Plan A"},
             {"id": PLAN_B, "tid": TENANT_B, "nom": "TEST_AUDIT_ADMIN Plan B"}])


def _borrar_vouchers():
    """Borra los archivos de voucher subidos por el harness."""
    for p in list(VOUCHER_FILES):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception as e:
            print(f"[cleanup] aviso: no se pudo borrar {p}: {str(e)[:80]}")


def cleanup():
    """Borra datos de prueba: doble pasada tolerante a FKs + archivos subidos."""
    _borrar_vouchers()
    sub_alumnos = (
        f"(SELECT id FROM usuarios WHERE correo LIKE 'test_audit_admin_%' "
        f"OR rut LIKE 'TAA%' OR tenant_id IN ({TIDS}))"
    )
    PASOS_CLEANUP = [
        ("notificaciones", f"DELETE FROM notificaciones WHERE alumno_id IN {sub_alumnos}"),
        ("notificaciones_enviadas", f"DELETE FROM notificaciones_enviadas WHERE alumno_id IN {sub_alumnos}"),
        ("solicitudes_planes", f"DELETE FROM solicitudes_planes WHERE tenant_id IN ({TIDS}) "
                              f"OR alumno_id IN {sub_alumnos}"),
        ("transacciones_financieras", f"DELETE FROM transacciones_financieras WHERE tenant_id IN ({TIDS})"),
        ("cobertura_emergencia", f"DELETE FROM cobertura_emergencia WHERE tenant_id IN ({TIDS})"),
        ("auditoria", f"DELETE FROM auditoria WHERE tenant_id IN ({TIDS})"),
        ("clases", f"DELETE FROM clases WHERE tenant_id IN ({TIDS})"),
        ("horarios", f"DELETE FROM horarios WHERE tenant_id IN ({TIDS})"),
        ("coach_disciplinas", f"DELETE FROM coach_disciplinas WHERE tenant_id IN ({TIDS})"),
        ("retencion_alumnos", f"DELETE FROM retencion_alumnos WHERE tenant_id IN ({TIDS})"),
        ("historial_rm", f"DELETE FROM historial_rm WHERE tenant_id IN ({TIDS})"),
        ("suscripciones", f"DELETE FROM suscripciones WHERE tenant_id IN ({TIDS})"),
        ("wods", f"DELETE FROM wods WHERE tenant_id IN ({TIDS})"),
        ("asistencias", f"DELETE FROM asistencias WHERE tenant_id IN ({TIDS})"),
        ("pedidos", f"DELETE FROM pedidos WHERE tenant_id IN ({TIDS}) "
                    f"OR alumno_id IN {sub_alumnos}"),
        ("productos", f"DELETE FROM productos WHERE tenant_id IN ({TIDS})"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({TIDS}) "
                    f"OR correo LIKE 'test_audit_admin_%' OR rut LIKE 'TAA%'"),
        ("movimientos", f"DELETE FROM movimientos WHERE tenant_id IN ({TIDS})"),
        ("planes", f"DELETE FROM planes WHERE tenant_id IN ({TIDS})"),
        ("tenants", f"DELETE FROM tenants WHERE id IN ({TIDS}) "
                    f"OR subdomain LIKE 'test-audit-admin-%'"),
    ]

    def _tablas_existentes():
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'")).fetchall()
            return {r[0] for r in rows}

    def _pasada(tablas):
        with engine.begin() as conn:
            for tabla, sql in PASOS_CLEANUP:
                if tabla in tablas:
                    conn.execute(sa_text(sql))

    try:
        tablas = _tablas_existentes()
        _pasada(tablas)
        _pasada(tablas)  # segunda pasada: captura FKs creadas por la primera
        print("[cleanup] OK - datos de prueba eliminados")
    except Exception as e:
        print("[cleanup] FALLO - quedan filas identificables con el prefijo "
              f"{PREFIX} (subdomain test-audit-admin-*, rut TAA*, correo test_audit_admin_*)")
        print("[cleanup]   detalle:", str(e)[:200])


def resumen_creacion():
    print("=" * 72)
    print("RESUMEN DE REGISTROS QUE CREA EL HARNESS (base REAL)")
    print("Marcador:", PREFIX, "| subdomain:", SUBDOMAIN_A, "/", SUBDOMAIN_B)
    print("-" * 72)
    print("  SEED (1 transacción, all-or-nothing):")
    print("    tenants      : 2   (box A y box B)")
    print("    usuarios     : 5   (admin+alumno+coach en A; admin+alumno en B)")
    print("    planes       : 2   (1 por box)")
    print("  VÍA HTTP (se limpian):")
    print("    vouchers     : 2   (archivos PNG reales subidos a static/uploads)")
    print("    solicitudes  : 2   (pending, una por box)")
    print("    al aprobar   : +1 suscripción, +1 notificación, +1 transacción, +1 auditoría")
    print("-" * 72)


def token(user_id, tenant_id, rol):
    return create_access_token({
        "usuario_id": user_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"u{user_id}@t.cl", "nombre": f"u{user_id}",
    })


RESULTS = []


def record(caso, esperado, obtenido, ok, detalle=""):
    RESULTS.append(ok)
    estado = "PASS" if ok else "FAIL"
    print(f"[{estado}] {caso}\n      esperado={esperado} obtenido={obtenido} {detalle}")


async def run_tests():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        hA_alumno = {"Authorization": f"Bearer {token(UID_A_ALUMNO, TENANT_A, 'alumno')}"}
        hA_admin = {"Authorization": f"Bearer {token(UID_A_ADMIN, TENANT_A, 'administrador')}"}
        hA_coach = {"Authorization": f"Bearer {token(UID_A_COACH, TENANT_A, 'coach')}"}
        hB_alumno = {"Authorization": f"Bearer {token(UID_B_ALUMNO, TENANT_B, 'alumno')}"}
        hB_admin = {"Authorization": f"Bearer {token(UID_B_ADMIN, TENANT_B, 'administrador')}"}

        # ── SETUP: subir vouchers reales y crear solicitudes ──
        rA = await c.post("/api/v1/upload/voucher",
                          files={"file": ("voucher_taa_a.png", PNG_1X1, "image/png")},
                          headers=hA_alumno)
        urlA = rA.json().get("url") if rA.status_code == 201 else None
        record("setup: subir voucher A", 201, rA.status_code,
               rA.status_code == 201 and bool(urlA), rA.text[:100])
        if urlA:
            VOUCHER_FILES.append(os.path.join(UPLOAD_DIR, os.path.basename(urlA)))

        rB = await c.post("/api/v1/upload/voucher",
                          files={"file": ("voucher_taa_b.png", PNG_1X1, "image/png")},
                          headers=hB_alumno)
        urlB = rB.json().get("url") if rB.status_code == 201 else None
        record("setup: subir voucher B", 201, rB.status_code,
               rB.status_code == 201 and bool(urlB), rB.text[:100])
        if urlB:
            VOUCHER_FILES.append(os.path.join(UPLOAD_DIR, os.path.basename(urlB)))

        if not urlA or not urlB:
            raise SystemExit("setup falló: no se pudieron subir los vouchers")

        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": TENANT_A, "alumno_id": UID_A_ALUMNO,
                               "plan_id": PLAN_A, "voucher_url": urlA}, headers=hA_alumno)
        solA_id = r.json().get("id") if r.status_code == 201 else None
        record("setup: solicitud A (pending)", 201, r.status_code,
               r.status_code == 201 and bool(solA_id), r.text[:100])

        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": TENANT_B, "alumno_id": UID_B_ALUMNO,
                               "plan_id": PLAN_B, "voucher_url": urlB}, headers=hB_alumno)
        solB_id = r.json().get("id") if r.status_code == 201 else None
        record("setup: solicitud B (pending)", 201, r.status_code,
               r.status_code == 201 and bool(solB_id), r.text[:100])

        if not solA_id or not solB_id:
            raise SystemExit("setup falló: no se crearon las solicitudes")

        # ── S1: IDOR voucher (cross-tenant debe fallar 403) ──
        r = await c.get(f"/api/v1/solicitudes/{solB_id}/voucher", headers=hA_alumno)
        record("S1: alumno A -> voucher solicitud de B", 403, r.status_code,
               r.status_code == 403, r.text[:80])
        r = await c.get(f"/api/v1/solicitudes/{solB_id}/voucher", headers=hA_admin)
        record("S1: admin A -> voucher solicitud de B", 403, r.status_code,
               r.status_code == 403, r.text[:80])
        r = await c.get(f"/api/v1/solicitudes/{solB_id}/voucher", headers=hA_coach)
        record("S1: coach A -> voucher solicitud de B", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # ── S1: positivos (dueño o staff del mismo box) ──
        r = await c.get(f"/api/v1/solicitudes/{solA_id}/voucher", headers=hA_alumno)
        record("S1: dueño alumno A -> su voucher", 200, r.status_code,
               r.status_code == 200, r.text[:40])
        r = await c.get(f"/api/v1/solicitudes/{solA_id}/voucher", headers=hA_admin)
        record("S1: admin A -> voucher mismo box", 200, r.status_code,
               r.status_code == 200, r.text[:40])
        r = await c.get(f"/api/v1/solicitudes/{solA_id}/voucher", headers=hA_coach)
        record("S1: coach A -> voucher mismo box", 200, r.status_code,
               r.status_code == 200, r.text[:40])
        r = await c.get(f"/api/v1/solicitudes/{solB_id}/voucher", headers=hB_alumno)
        record("S1: dueño alumno B -> su voucher", 200, r.status_code,
               r.status_code == 200, r.text[:40])

        # ── S2: aprobar/rechazar cross-tenant debe fallar 404 y NO mutar ──
        r = await c.put(f"/api/v1/solicitudes/{solB_id}/aprobar", headers=hA_admin)
        record("S2: admin A aprueba solicitud de B", 404, r.status_code,
               r.status_code == 404, r.text[:80])
        r = await c.put(f"/api/v1/solicitudes/{solB_id}/rechazar", headers=hA_admin)
        record("S2: admin A rechaza solicitud de B", 404, r.status_code,
               r.status_code == 404, r.text[:80])
        with engine.connect() as conn:
            estB = conn.execute(sa_text(
                "SELECT estado FROM solicitudes_planes WHERE id=:i"), {"i": solB_id}).scalar()
        record("S2: solicitud B intacta tras intentos ajenos", "pending", estB,
               estB == "pending")

        r = await c.put(f"/api/v1/solicitudes/{solA_id}/aprobar", headers=hB_admin)
        record("S2: admin B aprueba solicitud de A", 404, r.status_code,
               r.status_code == 404, r.text[:80])
        r = await c.put(f"/api/v1/solicitudes/{solA_id}/rechazar", headers=hB_admin)
        record("S2: admin B rechaza solicitud de A", 404, r.status_code,
               r.status_code == 404, r.text[:80])
        with engine.connect() as conn:
            estA = conn.execute(sa_text(
                "SELECT estado FROM solicitudes_planes WHERE id=:i"), {"i": solA_id}).scalar()
        record("S2: solicitud A intacta tras intentos ajenos", "pending", estA,
               estA == "pending")

        # ── S2: positivos (admin del MISMO box) ──
        r = await c.put(f"/api/v1/solicitudes/{solA_id}/aprobar", headers=hA_admin)
        with engine.connect() as conn:
            estA2 = conn.execute(sa_text(
                "SELECT estado FROM solicitudes_planes WHERE id=:i"), {"i": solA_id}).scalar()
            nSus = conn.execute(sa_text(
                "SELECT COUNT(*) FROM suscripciones WHERE tenant_id=:t "
                "AND usuario_id=:u AND estado='activo'"),
                {"t": TENANT_A, "u": UID_A_ALUMNO}).scalar()
        record("S2: admin A aprueba solicitud propia", "200+approved+sus",
               f"{r.status_code} est={estA2} sus={nSus}",
               r.status_code == 200 and estA2 == "approved" and nSus >= 1, r.text[:80])

        r = await c.put(f"/api/v1/solicitudes/{solB_id}/rechazar", headers=hB_admin)
        with engine.connect() as conn:
            estB2 = conn.execute(sa_text(
                "SELECT estado FROM solicitudes_planes WHERE id=:i"), {"i": solB_id}).scalar()
        record("S2: admin B rechaza solicitud propia", "200+rejected",
               f"{r.status_code} est={estB2}",
               r.status_code == 200 and estB2 == "rejected", r.text[:80])


def verificar_cero_leftovers():
    """Cuenta filas identificables y archivos de voucher restantes (debe ser 0)."""
    sub_alumnos = (
        f"(SELECT id FROM usuarios WHERE correo LIKE 'test_audit_admin_%' "
        f"OR rut LIKE 'TAA%' OR tenant_id IN ({TIDS}))"
    )
    checks = [
        ("tenants", f"SELECT COUNT(*) FROM tenants WHERE id IN ({TIDS}) "
                   f"OR subdomain LIKE 'test-audit-admin-%'"),
        ("usuarios", f"SELECT COUNT(*) FROM usuarios WHERE tenant_id IN ({TIDS}) "
                    f"OR correo LIKE 'test_audit_admin_%' OR rut LIKE 'TAA%'"),
        ("planes", f"SELECT COUNT(*) FROM planes WHERE tenant_id IN ({TIDS})"),
        ("solicitudes_planes", f"SELECT COUNT(*) FROM solicitudes_planes "
                              f"WHERE tenant_id IN ({TIDS}) OR alumno_id IN {sub_alumnos}"),
        ("suscripciones", f"SELECT COUNT(*) FROM suscripciones WHERE tenant_id IN ({TIDS})"),
        ("notificaciones", f"SELECT COUNT(*) FROM notificaciones WHERE alumno_id IN {sub_alumnos}"),
        ("notificaciones_enviadas", f"SELECT COUNT(*) FROM notificaciones_enviadas "
                                   f"WHERE alumno_id IN {sub_alumnos}"),
        ("transacciones_financieras", f"SELECT COUNT(*) FROM transacciones_financieras "
                                     f"WHERE tenant_id IN ({TIDS})"),
        ("auditoria", f"SELECT COUNT(*) FROM auditoria WHERE tenant_id IN ({TIDS})"),
        ("archivos_voucher", None),
    ]
    total = 0
    with engine.connect() as conn:
        for nombre, sql in checks:
            if sql is None:
                n = sum(1 for p in VOUCHER_FILES if os.path.exists(p))
            else:
                try:
                    n = conn.execute(sa_text(sql)).scalar() or 0
                except Exception as e:
                    print(f"[leftovers] {nombre}: no verificable ({str(e)[:80]})")
                    continue
            print(f"[leftovers] {nombre}: {n}")
            total += n
    return total == 0


def main():
    resumen_creacion()
    print("[setup] Limpieza previa de posibles leftovers...")
    cleanup()
    print("[setup] Creando datos de prueba (1 transacción, all-or-nothing)...")
    seed()
    try:
        asyncio.run(run_tests())
    except SystemExit:
        raise
    except Exception as e:
        print("[run] ERROR durante la ejecución:", str(e)[:300])
    finally:
        print("[teardown] Limpieza final...")
        cleanup()
    ok = verificar_cero_leftovers()
    total = len(RESULTS)
    passed = sum(1 for x in RESULTS if x)
    print(f"\nRESULTADO (Postgres real): {passed}/{total} PASS | "
          f"leftovers={'0' if ok else '>0 (ver detalle arriba)'}")
    sys.exit(0 if (passed == total and ok) else 1)


if __name__ == "__main__":
    main()
