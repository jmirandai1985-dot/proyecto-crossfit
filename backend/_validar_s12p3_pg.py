"""
Validación runtime de S12 (historicoIngresos desde transacciones_financieras)
y P3 (alta de alumno por admin crea suscripcion 'Prueba' activa + desbloqueo
al pagar) contra Postgres real.

Tenants de prueba marcados TEST_AUDIT_ADMIN (subdomain test-audit-admin-*,
correo test_audit_admin_*, rut TAA*). Cleanup doble pasada tolerante a FKs.
"""
import os
import sys
import random
import asyncio
from datetime import datetime, timezone, timedelta

os.environ["SENTRY_DSN"] = ""

from sqlalchemy import text as sa_text  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.database import engine  # noqa: E402

PREFIX = "TEST_AUDIT_ADMIN"
BASE = random.randint(5_000_000, 5_999_000)

TENANT_A = BASE          # tenant A: S12 (reportes + transacciones)
TENANT_B = BASE + 1      # tenant B: P3 (alta de alumno por admin)
UID_A_ADMIN = BASE + 10
UID_A_ALUMNO = BASE + 11
UID_B_ADMIN = BASE + 20
PLAN_A = BASE + 30
PLAN_PAGO = BASE + 31
SUS_A = BASE + 40

TIDS = f"{TENANT_A},{TENANT_B}"

SUBDOMAIN_A = f"test-audit-admin-s12-{BASE}"
SUBDOMAIN_B = f"test-audit-admin-s12-{BASE}b"
CORREO = {
    UID_A_ADMIN: f"test_audit_admin_a_{BASE}@test.com",
    UID_A_ALUMNO: f"test_audit_admin_alumno_a_{BASE}@test.com",
    UID_B_ADMIN: f"test_audit_admin_b_{BASE}@test.com",
}
RUT = {
    UID_A_ADMIN: "TAA501", UID_A_ALUMNO: "TAA502", UID_B_ADMIN: "TAA503",
}
NOMBRE = {
    UID_A_ADMIN: "TEST_AUDIT_ADMIN Admin A", UID_A_ALUMNO: "TEST_AUDIT_ADMIN Alumno A",
    UID_B_ADMIN: "TEST_AUDIT_ADMIN Admin B",
}

MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
         'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def inicio_mes(offset=0):
    """Primer instante del mes actual + offset (mismo criterio que _inicio_fin_mes)."""
    ahora = datetime.now(timezone.utc)
    ini_actual = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = ini_actual.year * 12 + (ini_actual.month - 1) + offset
    return ini_actual.replace(year=total // 12, month=total % 12 + 1, day=1)


def dia_mes(offset, dia=15):
    """Fecha (date) a mitad de mes para sembrar transacciones dentro del rango."""
    ini = inicio_mes(offset)
    try:
        return ini.replace(day=dia).date()
    except ValueError:
        return ini.replace(day=28).date()


def label_mes(offset):
    ini = inicio_mes(offset)
    return f"{MESES[ini.month - 1]} {ini.year}"


def seed():
    """Crea datos de prueba en UNA transacción (all-or-nothing)."""
    now = datetime.now(timezone.utc)
    fex = fmt(now + timedelta(days=30))
    tx = [
        # Mes actual: 2 ingresos + 1 egreso -> neto 70000
        (BASE + 200, "ingreso", 50000, dia_mes(0)),
        (BASE + 201, "ingreso", 30000, dia_mes(0)),
        (BASE + 202, "egreso", 10000, dia_mes(0)),
        # Mes -1: 20000
        (BASE + 203, "ingreso", 20000, dia_mes(-1)),
        # Mes -2: vacio -> 0
        # Mes -3: 40000
        (BASE + 204, "ingreso", 40000, dia_mes(-3)),
        # Mes -4: vacio -> 0
        # Mes -5: 10000
        (BASE + 205, "ingreso", 10000, dia_mes(-5)),
    ]
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            [{"id": TENANT_A, "nom": "TEST_AUDIT_ADMIN Box A S12", "sub": SUBDOMAIN_A, "ca": fmt(now)},
             {"id": TENANT_B, "nom": "TEST_AUDIT_ADMIN Box B P3", "sub": SUBDOMAIN_B, "ca": fmt(now)}])
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_A_ADMIN, "tid": TENANT_A, "rut": RUT[UID_A_ADMIN], "nom": NOMBRE[UID_A_ADMIN],
              "mail": CORREO[UID_A_ADMIN], "rol": "administrador"},
             {"id": UID_A_ALUMNO, "tid": TENANT_A, "rut": RUT[UID_A_ALUMNO], "nom": NOMBRE[UID_A_ALUMNO],
              "mail": CORREO[UID_A_ALUMNO], "rol": "alumno"},
             {"id": UID_B_ADMIN, "tid": TENANT_B, "rut": RUT[UID_B_ADMIN], "nom": NOMBRE[UID_B_ADMIN],
              "mail": CORREO[UID_B_ADMIN], "rol": "administrador"}])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, :nom, :cred, FALSE, :precio, 30, TRUE)"),
            [{"id": PLAN_A, "tid": TENANT_A, "nom": "TEST_AUDIT_ADMIN Plan A", "cred": 16, "precio": 50000},
             {"id": PLAN_PAGO, "tid": TENANT_B, "nom": "TEST_AUDIT_ADMIN Pago", "cred": 16, "precio": 50000}])
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', 16, 16, :fi, :fe)"),
            {"id": SUS_A, "tid": TENANT_A, "uid": UID_A_ALUMNO, "pid": PLAN_A,
             "fi": fmt(now), "fe": fex})
        conn.execute(sa_text(
            "INSERT INTO transacciones_financieras (id, tenant_id, tipo, categoria, monto, "
            "descripcion, fecha, created_at) "
            "VALUES (:id, :tid, :tipo, 'membresia', :monto, :desc, :fecha, :ca)"),
            [{"id": i, "tid": TENANT_A, "tipo": t, "monto": m, "desc": "TEST_AUDIT_ADMIN tx", "fecha": f, "ca": fmt(now)}
             for i, t, m, f in tx])


def cleanup():
    """Borra datos de prueba: doble pasada tolerante a FKs."""
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
        ("disciplinas", f"DELETE FROM disciplinas WHERE tenant_id IN ({TIDS})"),
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
        _pasada(tablas)
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
    print("    tenants         : 2   (A=S12 reportes, B=P3 alta admin)")
    print("    usuarios        : 3   (admin+alumno en A; admin en B)")
    print("    planes          : 2   (1 por box)")
    print("    suscripciones   : 1   (alumno A activa)")
    print("    transacciones   : 6   (mes actual +50k/+30k/-10k; -1:+20k; -3:+40k; -5:+10k)")
    print("  VÍA HTTP (se limpian):")
    print("    alumno nuevo    : 1   (alta por admin en B -> suscripcion Prueba)")
    print("    coach nuevo     : 1   (alta por admin en B -> sin suscripcion)")
    print("    suscripcion paga: 1   (B -> expira la Prueba del alumno)")
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
        hA_admin = {"Authorization": f"Bearer {token(UID_A_ADMIN, TENANT_A, 'administrador')}"}
        hB_admin = {"Authorization": f"Bearer {token(UID_B_ADMIN, TENANT_B, 'administrador')}"}

        # ══════════ S12: historicoIngresos desde transacciones_financieras ══════════
        r = await c.get("/api/v1/reportes/", params={"tenant_id": TENANT_A}, headers=hA_admin)
        data = r.json() if r.status_code == 200 else {}
        hist = data.get("historicoIngresos", [])
        esperado_hist = [
            {"mes": label_mes(-5), "ingresos": 10000},
            {"mes": label_mes(-4), "ingresos": 0},
            {"mes": label_mes(-3), "ingresos": 40000},
            {"mes": label_mes(-2), "ingresos": 0},
            {"mes": label_mes(-1), "ingresos": 20000},
            {"mes": label_mes(0), "ingresos": 70000},
        ]
        ok_hist = (r.status_code == 200 and hist == esperado_hist)
        record("S12: GET /reportes/ historicoIngresos 6 meses", esperado_hist, hist, ok_hist,
               r.text[:80] if r.status_code != 200 else "")
        record("S12: ingresos_mes consistente (neto mes actual)", 70000,
               data.get("ingresoMensual"),
               r.status_code == 200 and data.get("ingresoMensual") == 70000)
        record("S12: historicoMembresias sigue funcionando (6 items)", 6,
               len(data.get("historicoMembresias", [])),
               r.status_code == 200 and len(data.get("historicoMembresias", [])) == 6)

        # ══════════ P3: alta de alumno por admin crea suscripcion Prueba ══════════
        rut_alumno = "TAA6011"
        correo_alumno = f"test_audit_admin_p3_{BASE}@test.com"
        r = await c.post("/api/v1/usuarios/",
                         json={"tenant_id": TENANT_B, "rut": rut_alumno,
                               "nombre": "TEST_AUDIT_ADMIN P3 Alumno",
                               "correo": correo_alumno, "rol": "alumno",
                               "password": "tmp12345"},
                         headers=hB_admin)
        nuevo_id = r.json().get("id") if r.status_code == 201 else None
        record("P3: admin alta alumno (POST /usuarios)", 201, r.status_code,
               r.status_code == 201 and bool(nuevo_id), r.text[:100])

        with engine.connect() as conn:
            sus = conn.execute(sa_text(
                "SELECT s.estado, s.creditos_totales, s.creditos_disponibles, p.nombre "
                "FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
                "WHERE s.usuario_id=:u AND s.tenant_id=:t"),
                {"u": nuevo_id, "t": TENANT_B}).fetchone()
        ok_sus = (sus is not None and sus[0] == "activo" and sus[1] == 1
                  and sus[2] == 1 and sus[3] == "Prueba")
        record("P3: suscripcion Prueba activa (1/1 token)", "activo/1/1/Prueba",
               f"{sus[0]}/{sus[1]}/{sus[2]}/{sus[3]}" if sus else None, ok_sus)

        hNuevo = {"Authorization": f"Bearer {token(nuevo_id, TENANT_B, 'alumno')}"}
        r = await c.get("/api/v1/alumnos/me/es-prueba", headers=hNuevo)
        record("P3: alumno queda en modo prueba (es-prueba)", True,
               r.json().get("es_prueba") if r.status_code == 200 else r.status_code,
               r.status_code == 200 and r.json().get("es_prueba") is True, r.text[:80])
        r = await c.get("/api/v1/productos", headers=hNuevo)
        record("P3: gate real bloquea secciones de pago (productos)", 403,
               r.status_code, r.status_code == 403, r.text[:80])

        # ══════════ P3b: pagar expira la Prueba y desbloquea ══════════
        fexp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        r = await c.post("/api/v1/suscripciones",
                         json={"tenant_id": TENANT_B, "usuario_id": nuevo_id,
                               "plan_id": PLAN_PAGO, "fecha_expiracion": fexp},
                         headers=hB_admin)
        record("P3b: admin crea suscripcion paga", 201, r.status_code,
               r.status_code == 201, r.text[:100])
        with engine.connect() as conn:
            estado_prueba = conn.execute(sa_text(
                "SELECT s.estado FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
                "WHERE s.usuario_id=:u AND p.nombre='Prueba'"),
                {"u": nuevo_id}).scalar()
        record("P3b: suscripcion Prueba expirada (vencido)", "vencido", estado_prueba,
               estado_prueba == "vencido")
        r = await c.get("/api/v1/alumnos/me/es-prueba", headers=hNuevo)
        record("P3b: alumno desbloqueado (es-prueba False)", False,
               r.json().get("es_prueba") if r.status_code == 200 else r.status_code,
               r.status_code == 200 and r.json().get("es_prueba") is False, r.text[:80])
        r = await c.get("/api/v1/productos", headers=hNuevo)
        record("P3b: acceso completo tras pagar (productos 200)", 200,
               r.status_code, r.status_code == 200, r.text[:80])

        # ══════════ P3: alta de COACH por admin NO crea suscripcion ══════════
        r = await c.post("/api/v1/usuarios/",
                         json={"tenant_id": TENANT_B, "rut": "TAA6022",
                               "nombre": "TEST_AUDIT_ADMIN P3 Coach",
                               "correo": f"test_audit_admin_coach3_{BASE}@test.com",
                               "rol": "coach", "password": "tmp12345"},
                         headers=hB_admin)
        coach_id = r.json().get("id") if r.status_code == 201 else None
        with engine.connect() as conn:
            n_sus_coach = conn.execute(sa_text(
                "SELECT COUNT(*) FROM suscripciones WHERE usuario_id=:u"),
                {"u": coach_id}).scalar()
        record("P3: alta de coach no crea suscripcion", 0, n_sus_coach,
               r.status_code == 201 and n_sus_coach == 0, r.text[:80])


def verificar_cero_leftovers():
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
        ("suscripciones", f"SELECT COUNT(*) FROM suscripciones WHERE tenant_id IN ({TIDS})"),
        ("transacciones_financieras", f"SELECT COUNT(*) FROM transacciones_financieras "
                                     f"WHERE tenant_id IN ({TIDS})"),
        ("auditoria", f"SELECT COUNT(*) FROM auditoria WHERE tenant_id IN ({TIDS})"),
        ("notificaciones_enviadas", f"SELECT COUNT(*) FROM notificaciones_enviadas "
                                   f"WHERE alumno_id IN {sub_alumnos}"),
    ]
    total = 0
    with engine.connect() as conn:
        for nombre, sql in checks:
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
