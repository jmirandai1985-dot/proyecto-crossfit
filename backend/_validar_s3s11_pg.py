"""
Validación runtime de los fixes S3 (comprar-emergencia tenant del token) y
S11 (PUT /clases: coach solo se auto-asigna; tercer coach solo admin) contra
Postgres real.

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
BASE = random.randint(6_000_000, 6_999_000)

TENANT_A = BASE
TENANT_B = BASE + 1
UID_A_ADMIN = BASE + 10
UID_A_ALUMNO = BASE + 11
UID_A_ALUMNO2 = BASE + 12
UID_COACH_X = BASE + 13
UID_COACH_Y = BASE + 14
UID_B_ADMIN = BASE + 20
UID_B_ALUMNO = BASE + 21
PLAN_A = BASE + 30
PLAN_B = BASE + 31
SUS_A = BASE + 40
SUS_A2 = BASE + 41
SUS_B = BASE + 42
DISC_A = BASE + 50
CLASE_A = BASE + 60
HORARIO_A = BASE + 61

TIDS = f"{TENANT_A},{TENANT_B}"

SUBDOMAIN_A = f"test-audit-admin-s3-{BASE}"
SUBDOMAIN_B = f"test-audit-admin-s3-{BASE}b"
CORREO = {
    UID_A_ADMIN: f"test_audit_admin_a_{BASE}@test.com",
    UID_A_ALUMNO: f"test_audit_admin_alumno_a_{BASE}@test.com",
    UID_A_ALUMNO2: f"test_audit_admin_alumno_a2_{BASE}@test.com",
    UID_COACH_X: f"test_audit_admin_coach_x_{BASE}@test.com",
    UID_COACH_Y: f"test_audit_admin_coach_y_{BASE}@test.com",
    UID_B_ADMIN: f"test_audit_admin_b_{BASE}@test.com",
    UID_B_ALUMNO: f"test_audit_admin_alumno_b_{BASE}@test.com",
}
RUT = {
    UID_A_ADMIN: "TAA101", UID_A_ALUMNO: "TAA102", UID_A_ALUMNO2: "TAA103",
    UID_COACH_X: "TAA104", UID_COACH_Y: "TAA105",
    UID_B_ADMIN: "TAA106", UID_B_ALUMNO: "TAA107",
}
NOMBRE = {
    UID_A_ADMIN: "TEST_AUDIT_ADMIN Admin A", UID_A_ALUMNO: "TEST_AUDIT_ADMIN Alumno A",
    UID_A_ALUMNO2: "TEST_AUDIT_ADMIN Alumno A2", UID_COACH_X: "TEST_AUDIT_ADMIN Coach X",
    UID_COACH_Y: "TEST_AUDIT_ADMIN Coach Y", UID_B_ADMIN: "TEST_AUDIT_ADMIN Admin B",
    UID_B_ALUMNO: "TEST_AUDIT_ADMIN Alumno B",
}


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def seed():
    """Crea datos de prueba en UNA transacción (all-or-nothing)."""
    now = datetime.now(timezone.utc)
    fex = fmt(now + timedelta(days=20))
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            [{"id": TENANT_A, "nom": "TEST_AUDIT_ADMIN Box A S3", "sub": SUBDOMAIN_A, "ca": fmt(now)},
             {"id": TENANT_B, "nom": "TEST_AUDIT_ADMIN Box B S3", "sub": SUBDOMAIN_B, "ca": fmt(now)}])
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_A_ADMIN, "tid": TENANT_A, "rut": RUT[UID_A_ADMIN], "nom": NOMBRE[UID_A_ADMIN],
              "mail": CORREO[UID_A_ADMIN], "rol": "administrador"},
             {"id": UID_A_ALUMNO, "tid": TENANT_A, "rut": RUT[UID_A_ALUMNO], "nom": NOMBRE[UID_A_ALUMNO],
              "mail": CORREO[UID_A_ALUMNO], "rol": "alumno"},
             {"id": UID_A_ALUMNO2, "tid": TENANT_A, "rut": RUT[UID_A_ALUMNO2], "nom": NOMBRE[UID_A_ALUMNO2],
              "mail": CORREO[UID_A_ALUMNO2], "rol": "alumno"},
             {"id": UID_COACH_X, "tid": TENANT_A, "rut": RUT[UID_COACH_X], "nom": NOMBRE[UID_COACH_X],
              "mail": CORREO[UID_COACH_X], "rol": "coach"},
             {"id": UID_COACH_Y, "tid": TENANT_A, "rut": RUT[UID_COACH_Y], "nom": NOMBRE[UID_COACH_Y],
              "mail": CORREO[UID_COACH_Y], "rol": "coach"},
             {"id": UID_B_ADMIN, "tid": TENANT_B, "rut": RUT[UID_B_ADMIN], "nom": NOMBRE[UID_B_ADMIN],
              "mail": CORREO[UID_B_ADMIN], "rol": "administrador"},
             {"id": UID_B_ALUMNO, "tid": TENANT_B, "rut": RUT[UID_B_ALUMNO], "nom": NOMBRE[UID_B_ALUMNO],
              "mail": CORREO[UID_B_ALUMNO], "rol": "alumno"}])
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, :nom, :cred, FALSE, 50000, 30, TRUE)"),
            [{"id": PLAN_A, "tid": TENANT_A, "nom": "TEST_AUDIT_ADMIN Plan A", "cred": 16},
             {"id": PLAN_B, "tid": TENANT_B, "nom": "TEST_AUDIT_ADMIN Plan B", "cred": 20}])
        # Suscripciones: A y A2 con 0 créditos (habilitan compra de emergencia);
        # B con 16 créditos (no debería tocarse).
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, "
            "creditos_disponibles, fecha_inicio, fecha_expiracion, puede_comprar_emergencia, es_compra_emergencia) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', :tot, :disp, :fi, :fe, TRUE, FALSE)"),
            [{"id": SUS_A, "tid": TENANT_A, "uid": UID_A_ALUMNO, "pid": PLAN_A,
              "tot": 16, "disp": 0, "fi": fmt(now), "fe": fex},
             {"id": SUS_A2, "tid": TENANT_A, "uid": UID_A_ALUMNO2, "pid": PLAN_A,
              "tot": 16, "disp": 0, "fi": fmt(now), "fe": fex},
             {"id": SUS_B, "tid": TENANT_B, "uid": UID_B_ALUMNO, "pid": PLAN_B,
              "tot": 20, "disp": 16, "fi": fmt(now), "fe": fex}])
        # Disciplina + clase (coach actual = Coach Y; Coach X NO está en la disciplina).
        conn.execute(sa_text(
            "INSERT INTO disciplinas (id, tenant_id, nombre, descripcion, es_open_box, requiere_coach, activo) "
            "VALUES (:id, :tid, :nom, :desc, FALSE, TRUE, TRUE)"),
            {"id": DISC_A, "tid": TENANT_A, "nom": "TEST_AUDIT_ADMIN Disciplina", "desc": "test"})
        conn.execute(sa_text(
            "INSERT INTO horarios (id, tenant_id, disciplina_id, dia_semana, hora_inicio, hora_fin, "
            "cupo_maximo, activo) VALUES (:id, :tid, :did, 1, '18:00', '19:00', 20, TRUE)"),
            {"id": HORARIO_A, "tid": TENANT_A, "did": DISC_A})
        conn.execute(sa_text(
            "INSERT INTO clases (id, tenant_id, horario_base_id, disciplina_id, coach_id, fecha, "
            "hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada) "
            "VALUES (:id, :tid, :hid, :did, :cid, :fecha, :hi, :hf, 20, 0, FALSE)"),
            {"id": CLASE_A, "tid": TENANT_A, "hid": HORARIO_A, "did": DISC_A, "cid": UID_COACH_Y,
             "fecha": now.date().isoformat(), "hi": "18:00", "hf": "19:00"})


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
    print("    tenants      : 2   (box A y box B)")
    print("    usuarios     : 7   (admin+2 alumnos+2 coaches en A; admin+alumno en B)")
    print("    planes       : 2   (1 por box)")
    print("    suscripciones: 3   (A y A2 con 0 créditos; B con 16)")
    print("    disciplina   : 1   (box A)")
    print("    clase        : 1   (box A, coach actual = Coach Y)")
    print("  VÍA HTTP (se limpian):")
    print("    cobertura_emergencia : +2 (auto-asignación coach / admin)")
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
        hA_alumno = {"Authorization": f"Bearer {token(UID_A_ALUMNO, TENANT_A, 'alumno')}"}
        hA_coach = {"Authorization": f"Bearer {token(UID_COACH_X, TENANT_A, 'coach')}"}
        hB_admin = {"Authorization": f"Bearer {token(UID_B_ADMIN, TENANT_B, 'administrador')}"}

        # ── S3: staff NO puede operar sobre suscripciones del box B ──
        r = await c.post("/api/v1/planes/comprar-emergencia",
                         json={"tenant_id": TENANT_B, "alumno_id": UID_B_ALUMNO,
                               "plan_id": PLAN_B}, headers=hA_admin)
        record("S3: admin A -> emergencia alumno B (tenant body ignorado)", 404,
               r.status_code, r.status_code == 404, r.text[:80])
        r = await c.post("/api/v1/planes/comprar-emergencia",
                         json={"tenant_id": TENANT_B, "alumno_id": UID_B_ALUMNO,
                               "plan_id": PLAN_B}, headers=hA_coach)
        record("S3: coach A -> emergencia alumno B (tenant body ignorado)", 404,
               r.status_code, r.status_code == 404, r.text[:80])
        with engine.connect() as conn:
            row = conn.execute(sa_text(
                "SELECT creditos_disponibles, es_compra_emergencia, fecha_compra_emergencia "
                "FROM suscripciones WHERE id=:i"), {"i": SUS_B}).fetchone()
        okB = row[0] == 16 and row[1] is False and row[2] is None
        record("S3: suscripción de B intacta tras intentos", "16/false/null",
               f"{row[0]}/{row[1]}/{row[2]}", okB)

        # ── S3: positivos (tenant del token, aunque el body mienta) ──
        r = await c.post("/api/v1/planes/comprar-emergencia",
                         json={"tenant_id": TENANT_B, "alumno_id": UID_A_ALUMNO,
                               "plan_id": PLAN_A}, headers=hA_alumno)
        with engine.connect() as conn:
            rowA = conn.execute(sa_text(
                "SELECT creditos_disponibles, es_compra_emergencia "
                "FROM suscripciones WHERE id=:i"), {"i": SUS_A}).fetchone()
        record("S3: alumno A (tenant spoofeado) -> su emergencia", "200+actualizada",
               f"{r.status_code} cred={rowA[0]} em={rowA[1]}",
               r.status_code == 200 and rowA[0] == 16 and rowA[1] is True, r.text[:80])
        r = await c.post("/api/v1/planes/comprar-emergencia",
                         json={"tenant_id": TENANT_A, "alumno_id": UID_A_ALUMNO2,
                               "plan_id": PLAN_A}, headers=hA_admin)
        with engine.connect() as conn:
            rowA2 = conn.execute(sa_text(
                "SELECT creditos_disponibles, es_compra_emergencia "
                "FROM suscripciones WHERE id=:i"), {"i": SUS_A2}).fetchone()
        record("S3: admin A -> emergencia alumno A2 (mismo box)", "200+actualizada",
               f"{r.status_code} cred={rowA2[0]} em={rowA2[1]}",
               r.status_code == 200 and rowA2[0] == 16 and rowA2[1] is True, r.text[:80])

        # ── S11: coach NO puede reasignar a un TERCER coach ──
        r = await c.put(f"/api/v1/clases/{CLASE_A}?modo_emergencia=true",
                        json={"coach_id": UID_COACH_Y}, headers=hA_coach)
        record("S11: coach X -> reasigna a coach Y (con emergencia)", 403,
               r.status_code, r.status_code == 403, r.text[:80])
        r = await c.put(f"/api/v1/clases/{CLASE_A}",
                        json={"coach_id": UID_COACH_Y}, headers=hA_coach)
        record("S11: coach X -> reasigna a coach Y (sin emergencia)", 403,
               r.status_code, r.status_code == 403, r.text[:80])
        r = await c.put(f"/api/v1/clases/{CLASE_A}?modo_emergencia=true",
                        json={"coach_id": UID_COACH_X}, headers=hA_coach)
        with engine.connect() as conn:
            coach_clase = conn.execute(sa_text(
                "SELECT coach_id FROM clases WHERE id=:i"), {"i": CLASE_A}).scalar()
            acc_self = conn.execute(sa_text(
                "SELECT COUNT(*) FROM cobertura_emergencia WHERE clase_id=:i "
                "AND accion='asignar_coach_self'"), {"i": CLASE_A}).scalar()
        record("S11: coach X -> auto-asignación permitida", "200+self",
               f"{r.status_code} coach={coach_clase} cov_self={acc_self}",
               r.status_code == 200 and coach_clase == UID_COACH_X and acc_self >= 1,
               r.text[:80])

        # ── S11: admin SÍ reasigna (auditoría asignar_coach_admin) ──
        r = await c.put(f"/api/v1/clases/{CLASE_A}?modo_emergencia=true",
                        json={"coach_id": UID_COACH_Y}, headers=hA_admin)
        with engine.connect() as conn:
            coach_clase2 = conn.execute(sa_text(
                "SELECT coach_id FROM clases WHERE id=:i"), {"i": CLASE_A}).scalar()
            acc_admin = conn.execute(sa_text(
                "SELECT COUNT(*) FROM cobertura_emergencia WHERE clase_id=:i "
                "AND accion='asignar_coach_admin'"), {"i": CLASE_A}).scalar()
        record("S11: admin A -> reasigna a coach Y", "200+admin",
               f"{r.status_code} coach={coach_clase2} cov_admin={acc_admin}",
               r.status_code == 200 and coach_clase2 == UID_COACH_Y and acc_admin >= 1,
               r.text[:80])

        # ── S11: regresión - coach vuelve a auto-asignarse tras admin ──
        r = await c.put(f"/api/v1/clases/{CLASE_A}?modo_emergencia=true",
                        json={"coach_id": UID_COACH_X}, headers=hA_coach)
        with engine.connect() as conn:
            coach_clase3 = conn.execute(sa_text(
                "SELECT coach_id FROM clases WHERE id=:i"), {"i": CLASE_A}).scalar()
        record("S11: coach X -> auto-asignación tras admin", "200+self",
               f"{r.status_code} coach={coach_clase3}",
               r.status_code == 200 and coach_clase3 == UID_COACH_X, r.text[:80])

        # ── S11: regresión - alumno no puede editar clases (403) ──
        r = await c.put(f"/api/v1/clases/{CLASE_A}", json={"coach_id": UID_COACH_X},
                        headers=hA_alumno)
        record("S11: alumno -> PUT /clases (sin rol coach)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # ── S6: POST /registrar es SOLO admin + alumno del box ──
        r = await c.post("/api/v1/notificaciones-enviadas/registrar",
                         params={"alumno_id": UID_A_ALUMNO, "tipo": "bienvenida",
                                 "estado": "enviado"}, headers=hA_alumno)
        record("S6: alumno -> registrar (antes público)", 403, r.status_code,
               r.status_code == 403, r.text[:80])
        r = await c.post("/api/v1/notificaciones-enviadas/registrar",
                         params={"alumno_id": UID_B_ALUMNO, "tipo": "bienvenida",
                                 "estado": "enviado"}, headers=hA_admin)
        record("S6: admin A -> registrar alumno de B", 404, r.status_code,
               r.status_code == 404, r.text[:80])
        r = await c.post("/api/v1/notificaciones-enviadas/registrar",
                         params={"alumno_id": UID_A_ALUMNO, "tipo": "bienvenida",
                                 "estado": "enviado"}, headers=hA_admin)
        record("S6: admin A -> registrar alumno propio", 200, r.status_code,
               r.status_code == 200, r.text[:80])

        # ── S5: el log queda scoped por tenant del admin ──
        A_USERS = (UID_A_ADMIN, UID_A_ALUMNO, UID_A_ALUMNO2, UID_COACH_X, UID_COACH_Y)
        rA = await c.get("/api/v1/notificaciones-enviadas", params={"limit": 100},
                         headers=hA_admin)
        dataA = rA.json() if rA.status_code == 200 else {"total": -1}
        rB = await c.get("/api/v1/notificaciones-enviadas", params={"limit": 100},
                         headers=hB_admin)
        dataB = rB.json() if rB.status_code == 200 else {"total": -1}
        itemsA = dataA.get("items", [])
        record("S5: admin A ve SOLO su log (tenant A)", ">=1 y todos de A",
               f"total={dataA.get('total')} ids={[x['alumno_id'] for x in itemsA]}",
               dataA.get("total", 0) >= 1
               and all(x["alumno_id"] in A_USERS for x in itemsA)
               and any(x["tipo"] == "bienvenida" and x["alumno_id"] == UID_A_ALUMNO
                       for x in itemsA),
               rA.text[:80])
        record("S5: admin B NO ve el log de A", 0, str(dataB.get("total")),
               dataB.get("total") == 0, rB.text[:80])


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
        ("disciplinas", f"SELECT COUNT(*) FROM disciplinas WHERE tenant_id IN ({TIDS})"),
        ("horarios", f"SELECT COUNT(*) FROM horarios WHERE tenant_id IN ({TIDS})"),
        ("clases", f"SELECT COUNT(*) FROM clases WHERE tenant_id IN ({TIDS})"),
        ("cobertura_emergencia", f"SELECT COUNT(*) FROM cobertura_emergencia WHERE tenant_id IN ({TIDS})"),
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
