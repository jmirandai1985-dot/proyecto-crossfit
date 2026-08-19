"""
Validación Fase 1 contra Postgres real (Neon).

Aísla todo en un tenant de prueba (subdominio/correos/RUT únicos) y limpia
al final (try/finally). NO imprime connection string ni credenciales.
Requisito: backend/.env con DATABASE_URL válida.
"""
import os
import sys
import random
import asyncio
from datetime import datetime, timezone, timedelta

os.environ["SENTRY_DSN"] = ""  # evitar envíos a Sentry durante la validación

from sqlalchemy import text as sa_text  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.database import engine  # noqa: E402

PREFIX = "TEST_VALIDACION"  # marcador inconfundible (también para borrado manual)
BASE = random.randint(8_000_000, 8_999_000)

TENANT_ID = BASE
TENANT2_ID = BASE + 1
UID_A = BASE + 100   # alumno A (tenant 1)
UID_B = BASE + 101   # alumno B (tenant 1)
UID_COACH = BASE + 102
UID_ADMIN = BASE + 103
UID_OTRO = BASE + 104  # alumno en tenant 2
PLAN_ID = BASE + 200
MOV_ID = BASE + 201
RM_B_ID = BASE + 300
RM_A_VIEJO_ID = BASE + 301

TID_LIST = (TENANT_ID, TENANT2_ID)
UID_LIST = (UID_A, UID_B, UID_COACH, UID_ADMIN, UID_OTRO)

# Identificadores con prefijo inconfundible para limpieza manual posterior
SUBDOMAIN = f"test-validacion-fase1-{BASE}"
SUBDOMAIN2 = f"test-validacion-fase1-{BASE}b"
CORREO = {
    UID_A: f"test_validacion_alumno_a_{BASE}@test.com",
    UID_B: f"test_validacion_alumno_b_{BASE}@test.com",
    UID_COACH: f"test_validacion_coach_{BASE}@test.com",
    UID_ADMIN: f"test_validacion_admin_{BASE}@test.com",
    UID_OTRO: f"test_validacion_otro_{BASE}@test.com",
}
RUT = {
    UID_A: "TV000001", UID_B: "TV000002", UID_COACH: "TV000003",
    UID_ADMIN: "TV000004", UID_OTRO: "TV000005",
}
NOMBRE = {
    UID_A: "TEST_VALIDACION Alumno A", UID_B: "TEST_VALIDACION Alumno B",
    UID_COACH: "TEST_VALIDACION Coach", UID_ADMIN: "TEST_VALIDACION Admin",
    UID_OTRO: "TEST_VALIDACION OtroBox",
}


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def seed():
    """Crea los datos de prueba en UNA transacción (all-or-nothing).

    Si algo falla a mitad, engine.begin() hace rollback completo y no queda
    nada parcial. Los identificadores llevan el prefijo TEST_VALIDACION.
    """
    now = datetime.now(timezone.utc)
    hace48 = now - timedelta(hours=48)
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT_ID, "nom": "TEST_VALIDACION Tenant A (Fase1)", "sub": SUBDOMAIN, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            {"id": TENANT2_ID, "nom": "TEST_VALIDACION Tenant B (Fase1)", "sub": SUBDOMAIN2, "ca": fmt(now)})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [{"id": UID_A, "tid": TENANT_ID, "rut": RUT[UID_A], "nom": NOMBRE[UID_A],
              "mail": CORREO[UID_A], "rol": "alumno"},
             {"id": UID_B, "tid": TENANT_ID, "rut": RUT[UID_B], "nom": NOMBRE[UID_B],
              "mail": CORREO[UID_B], "rol": "alumno"},
             {"id": UID_COACH, "tid": TENANT_ID, "rut": RUT[UID_COACH], "nom": NOMBRE[UID_COACH],
              "mail": CORREO[UID_COACH], "rol": "coach"},
             {"id": UID_ADMIN, "tid": TENANT_ID, "rut": RUT[UID_ADMIN], "nom": NOMBRE[UID_ADMIN],
              "mail": CORREO[UID_ADMIN], "rol": "administrador"}])
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', 'alumno', TRUE, 'activo')"),
            {"id": UID_OTRO, "tid": TENANT2_ID, "rut": RUT[UID_OTRO], "nom": NOMBRE[UID_OTRO], "mail": CORREO[UID_OTRO]})
        conn.execute(sa_text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) "
            "VALUES (:id, :tid, 'TEST_VALIDACION Plan PG', 16, FALSE, 50000, 30, TRUE)"),
            {"id": PLAN_ID, "tid": TENANT_ID})
        conn.execute(sa_text(
            "INSERT INTO movimientos (id, tenant_id, nombre, categoria, activo) "
            "VALUES (:id, :tid, 'TEST_VALIDACION Back Squat', 'fuerza', TRUE)"),
            {"id": MOV_ID, "tid": TENANT_ID})
        conn.execute(sa_text(
            "INSERT INTO historial_rm (id, tenant_id, alumno_id, movimiento_id, peso_kg, tipo_rm, fecha, created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :mid, :peso, 'peso', '2026-08-10', :ca, :ua)"),
            [{"id": RM_B_ID, "tid": TENANT_ID, "aid": UID_B, "mid": MOV_ID, "peso": 100.0, "ca": fmt(hace48), "ua": fmt(hace48)},
             {"id": RM_A_VIEJO_ID, "tid": TENANT_ID, "aid": UID_A, "mid": MOV_ID, "peso": 120.0, "ca": fmt(hace48), "ua": fmt(hace48)}])
        conn.execute(sa_text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, creditos_disponibles, "
            "fecha_inicio, fecha_expiracion, puede_comprar_emergencia) "
            "VALUES (:id, :tid, :uid, :pid, 'activo', 16, 9, :fi, :fe, TRUE)"),
            {"id": BASE + 400, "tid": TENANT_ID, "uid": UID_A, "pid": PLAN_ID,
             "fi": fmt(now), "fe": fmt(now + timedelta(days=20))})
        conn.execute(sa_text(
            "INSERT INTO notificaciones (id, alumno_id, tipo, mensaje, leida, created_at) "
            "VALUES (:id, :aid, 'aprobado', :msg, FALSE, :ca)"),
            [{"id": BASE + 500, "aid": UID_A, "msg": "TEST_VALIDACION para A PG", "ca": fmt(now)},
             {"id": BASE + 501, "aid": UID_B, "msg": "TEST_VALIDACION para B PG", "ca": fmt(now)}])


def resumen_creacion():
    """Resumen de registros que crea el harness (para revisión previa)."""
    print("=" * 72)
    print("RESUMEN DE REGISTROS QUE CREA EL HARNESS (base REAL)")
    print("Marcador de identificación:", PREFIX, "| subdomain:", SUBDOMAIN)
    print("-" * 72)
    print("  SEED (1 transacción, all-or-nothing):")
    print("    tenants           : 2   (ids %s, %s)" % (TENANT_ID, TENANT2_ID))
    print("    usuarios          : 5   (ids %s..%s, rol alumno/coach/administrador)" % (UID_A, UID_OTRO))
    print("    planes            : 1   (tenant 1)")
    print("    movimientos       : 1   (tenant 1)")
    print("    historial_rm      : 2   (1 de alumno B, 1 de alumno A con created_at 48h)")
    print("    suscripciones     : 1   (activa para alumno A, 16/9 tokens)")
    print("    notificaciones    : 2   (alumno A y alumno B)")
    print("  VÍA HTTP (dentro del tenant de prueba; se limpian):")
    print("    solicitudes_planes: hasta 3 (creadas y borradas durante el flujo)")
    print("    suscripciones     : +1   (generada al aprobar comprobante)")
    print("    notificaciones    : +1   (generada al aprobar comprobante)")
    print("    transacciones_fin. : +1   (auto-generada al aprobar)")
    print("    auditoria         : +2   (aprobar comprobante + editar rol)")
    print("    clases            : 0    (el tenant no tiene horarios_base)")
    print("-" * 72)
    print("CLEANUP: doble pasada por marcadores (ids + prefijo) en finally,")
    print("        más limpieza previa al inicio. Si fallara, quedan filas")
    print("        identificables con:", PREFIX, "/ test-validacion- / TV%")
    print("=" * 72)
def cleanup():
    """Limpieza robusta por marcadores (ids + prefijo), idempotente, doble pasada.

    Borra por ids de tenant/usuario Y por prefijos (test-validacion-, TV, correos
    test_validacion_) para recuperar también leftovers de una corrida anterior
    que haya muerto a mitad de camino. Se ejecuta antes del seed y en finally.
    """
    tids = ", ".join(str(t) for t in TID_LIST)

    # Subquery de alumnos de prueba: la corrida actual (ids) MÁS cualquier
    # leftover de corridas previas detectado por prefijos. Esto evita el FK
    # violation al borrar usuarios por prefijo sin haber borrado antes sus
    # notificaciones/solicitudes (bug visto el 19/08/2026).
    sub_alumnos = (
        f"(SELECT id FROM usuarios WHERE correo LIKE 'test_validacion_%' "
        f"OR rut LIKE 'TV%' OR tenant_id IN ({tids}))"
    )

    # Pasos de borrado en orden seguro de FKs. Cada paso declara su tabla para
    # poder omitir la que no exista en esta BD (schema divergido: ver AUDIT.md §3.1).
    PASOS_CLEANUP = [
        ("notificaciones", f"DELETE FROM notificaciones WHERE alumno_id IN {sub_alumnos}"),
        ("notificaciones_enviadas", f"DELETE FROM notificaciones_enviadas WHERE alumno_id IN {sub_alumnos}"),
        ("solicitudes_planes", f"DELETE FROM solicitudes_planes WHERE tenant_id IN ({tids}) "
                              f"OR alumno_id IN {sub_alumnos}"),
        ("transacciones_financieras", f"DELETE FROM transacciones_financieras WHERE tenant_id IN ({tids})"),
        ("cobertura_emergencia", f"DELETE FROM cobertura_emergencia WHERE tenant_id IN ({tids})"),
        ("auditoria", f"DELETE FROM auditoria WHERE tenant_id IN ({tids})"),
        ("clases", f"DELETE FROM clases WHERE tenant_id IN ({tids})"),
        ("horarios", f"DELETE FROM horarios WHERE tenant_id IN ({tids})"),
        ("coach_disciplinas", f"DELETE FROM coach_disciplinas WHERE tenant_id IN ({tids})"),
        ("retencion_alumnos", f"DELETE FROM retencion_alumnos WHERE tenant_id IN ({tids})"),
        ("historial_rm", f"DELETE FROM historial_rm WHERE tenant_id IN ({tids})"),
        ("suscripciones", f"DELETE FROM suscripciones WHERE tenant_id IN ({tids})"),
        ("wods", f"DELETE FROM wods WHERE tenant_id IN ({tids})"),
        ("asistencias", f"DELETE FROM asistencias WHERE tenant_id IN ({tids})"),
        ("pedidos", f"DELETE FROM pedidos WHERE tenant_id IN ({tids}) "
                    f"OR alumno_id IN {sub_alumnos}"),
        ("productos", f"DELETE FROM productos WHERE tenant_id IN ({tids})"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tids}) "
                    f"OR correo LIKE 'test_validacion_%' OR rut LIKE 'TV%'"),
        ("movimientos", f"DELETE FROM movimientos WHERE tenant_id IN ({tids})"),
        ("planes", f"DELETE FROM planes WHERE tenant_id IN ({tids})"),
        ("tenants", f"DELETE FROM tenants WHERE id IN ({tids}) "
                    f"OR subdomain LIKE 'test-validacion-%'"),
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
        faltantes = [t for t, _ in PASOS_CLEANUP if t not in tablas]
        if faltantes:
            print("[cleanup] aviso: tablas inexistentes en esta BD "
                  f"(DELETE omitido): {', '.join(faltantes)}")
        print("[cleanup] OK - datos de prueba eliminados")
    except Exception as e:
        print("[cleanup] FALLO - quedan filas identificables con el prefijo "
              f"{PREFIX} (subdomain test-validacion-*, rut TV*, correo test_validacion_*)")
        print("[cleanup]   detalle:", str(e)[:200])


def token(user_id, tenant_id, rol):
    return create_access_token({
        "usuario_id": user_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"u{user_id}@t.cl", "nombre": f"u{user_id}",
    })


from httpx import ASGITransport, AsyncClient  # noqa: E402

RESULTS = []


def record(caso, esperado, obtenido, ok, detalle=""):
    RESULTS.append(ok)
    estado = "PASS" if ok else "FAIL"
    print(f"[{estado}] {caso}\n      esperado={esperado} obtenido={obtenido} {detalle}")


async def run_tests():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        hA = {"Authorization": f"Bearer {token(UID_A, TENANT_ID, 'alumno')}"}
        hCoach = {"Authorization": f"Bearer {token(UID_COACH, TENANT_ID, 'coach')}"}
        hAdmin = {"Authorization": f"Bearer {token(UID_ADMIN, TENANT_ID, 'administrador')}"}

        # 1) DELETE /historial-rm de otro alumno -> 403
        r = await c.delete(f"/api/v1/historial-rm/{RM_B_ID}?tenant_id=1", headers=hA)
        record("DELETE /historial-rm de otro alumno", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # 2) PUT /historial-rm de otro alumno -> 403
        r = await c.put(f"/api/v1/historial-rm/{RM_B_ID}?tenant_id=1",
                        json={"peso_kg": 200}, headers=hA)
        record("PUT /historial-rm de otro alumno", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # 3) PUT propio con created_at > 24h -> 403 + mensaje ventana
        r = await c.put(f"/api/v1/historial-rm/{RM_A_VIEJO_ID}?tenant_id=1",
                        json={"peso_kg": 200}, headers=hA)
        ok3 = r.status_code == 403 and "24" in r.text
        record("PUT /historial-rm propio >24h", "403+msj ventana", r.status_code,
               ok3, r.text[:120])

        # 4) mi-membresia con alumno_id ajeno -> 200 propia
        r = await c.get("/api/v1/membresias/mi-membresia",
                        params={"tenant_id": 1, "alumno_id": UID_B}, headers=hA)
        body = r.json()
        record("GET /mi-membresia (alumno_id ajeno ignorado)", "200 propia",
               f"{r.status_code} activa={body.get('activa')}",
               r.status_code == 200 and body.get("activa") is True)

        # 5) membresia-activa con alumno_id ajeno -> 200 propia
        r = await c.get("/api/v1/planes/membresia-activa",
                        params={"tenant_id": 1, "alumno_id": UID_B}, headers=hA)
        body = r.json()
        record("GET /planes/membresia-activa (alumno_id ajeno ignorado)", "200 propia",
               f"{r.status_code} activa={body.get('activa')}",
               r.status_code == 200 and body.get("activa") is True)

        # 6) notificaciones de otro alumno sin staff -> 403
        r = await c.get("/api/v1/notificaciones", params={"alumno_id": UID_B}, headers=hA)
        record("GET /notificaciones de otro alumno (sin staff)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # 7) propias -> 200 y solo las propias
        r = await c.get("/api/v1/notificaciones", params={"alumno_id": UID_A}, headers=hA)
        data = r.json() if r.status_code == 200 else []
        record("GET /notificaciones propias", "200 solo A", f"{r.status_code} n={len(data)}",
               r.status_code == 200 and all(n["alumno_id"] == UID_A for n in data) and len(data) == 1)

        # 8) staff puede ver las de otro (coach) -> 200
        r = await c.get("/api/v1/notificaciones", params={"alumno_id": UID_B}, headers=hCoach)
        record("GET /notificaciones de otro (coach)", 200, r.status_code,
               r.status_code == 200, r.text[:60])

        # 9) solicitudes/solicitar con alumno_id ajeno sin staff -> 403
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": 1, "alumno_id": UID_B, "plan_id": PLAN_ID,
                               "voucher_url": "/static/uploads/x.jpg"}, headers=hA)
        record("POST /solicitudes/solicitar (alumno ajeno, no staff)", 403, r.status_code,
               r.status_code == 403, r.text[:80])
        # 10) alumno propio -> 201
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": TENANT_ID, "alumno_id": UID_A, "plan_id": PLAN_ID,
                               "voucher_url": "/static/uploads/x.jpg"}, headers=hA)
        record("POST /solicitudes/solicitar (propio)", 201, r.status_code,
               r.status_code == 201, r.text[:80])
        with engine.begin() as conn:
            conn.execute(sa_text("DELETE FROM solicitudes_planes WHERE tenant_id=:t"), {"t": TENANT_ID})

        # 11) coach por alumno del box -> 201
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": TENANT_ID, "alumno_id": UID_A, "plan_id": PLAN_ID}, headers=hCoach)
        record("POST /solicitudes/solicitar (coach por alumno)", 201, r.status_code,
               r.status_code == 201, r.text[:80])
        with engine.begin() as conn:
            conn.execute(sa_text("DELETE FROM solicitudes_planes WHERE tenant_id=:t"), {"t": TENANT_ID})

        # 12) coach con alumno de OTRO box -> 403
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": TENANT2_ID, "alumno_id": UID_OTRO, "plan_id": PLAN_ID}, headers=hCoach)
        record("POST /solicitudes/solicitar (coach, alumno de otro box)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # 13) POST /auditoria retirado -> 405
        r = await c.post("/api/v1/auditoria",
                         json={"tenant_id": 1, "accion": "CREATE", "entidad": "x"})
        record("POST /auditoria retirado (405)", 405, r.status_code,
               r.status_code == 405, r.text[:60])

        # 14) Tarea 1: aprobar comprobante -> entrada auditoria
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": TENANT_ID, "alumno_id": UID_A, "plan_id": PLAN_ID,
                               "voucher_url": "/static/uploads/v.jpg"}, headers=hA)
        sol_id = r.json().get("id") if r.status_code == 201 else None
        with engine.begin() as conn:
            conn.execute(sa_text("DELETE FROM solicitudes_planes WHERE tenant_id=:t AND id!=:k"),
                         {"t": TENANT_ID, "k": sol_id})
        r = await c.put(f"/api/v1/solicitudes/{sol_id}/aprobar", headers=hAdmin)
        with engine.connect() as conn:
            n = conn.execute(sa_text(
                "SELECT COUNT(*) FROM auditoria WHERE entidad='solicitud_plan' "
                "AND accion='UPDATE' AND entidad_id=:sid"), {"sid": sol_id}).scalar()
        record("Tarea1: aprobar comprobante -> entrada auditoria",
               "200 + 1 fila", f"{r.status_code} filas={n}",
               r.status_code == 200 and n == 1)

        # 15) Tarea 1: editar rol -> entrada auditoria
        r = await c.put(f"/api/v1/usuarios/{UID_B}", json={"rol": "coach"}, headers=hAdmin)
        with engine.connect() as conn:
            n2 = conn.execute(sa_text(
                "SELECT COUNT(*) FROM auditoria WHERE entidad='usuario' "
                "AND accion='UPDATE' AND entidad_id=:uid"), {"uid": UID_B}).scalar()
        record("Tarea1: editar rol -> entrada auditoria",
               "200 + 1 fila", f"{r.status_code} filas={n2}",
               r.status_code == 200 and n2 == 1)

        # 16) GET /historial-rm (alumno sin filtro -> solo propios)
        r = await c.get("/api/v1/historial-rm", params={"tenant_id": 1}, headers=hA)
        data = r.json() if r.status_code == 200 else []
        record("GET /historial-rm (alumno sin filtro -> solo propios)", "solo A",
               f"{r.status_code} ids={[x['id'] for x in data]}",
               r.status_code == 200 and all(x["alumno_id"] == UID_A for x in data))

        # 17) GET /historial-rm?alumno_id=otro -> 403
        r = await c.get("/api/v1/historial-rm", params={"tenant_id": 1, "alumno_id": UID_B}, headers=hA)
        record("GET /historial-rm (alumno_id ajeno)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # 18) Regresión: fidelizacion/coach/{id}/en-riesgo con token COACH (propio) -> 200
        r = await c.get(f"/api/v1/fidelizacion/coach/{UID_COACH}/en-riesgo", headers=hCoach)
        record("REGR: fidelizacion/coach propio (coach token)", 200, r.status_code,
               r.status_code == 200, r.text[:80])

        # 19) Regresión: mismo endpoint con coach_id ajeno -> 403
        r = await c.get(f"/api/v1/fidelizacion/coach/{UID_COACH + 50}/en-riesgo", headers=hCoach)
        record("REGR: fidelizacion/coach ajeno (coach token)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # 20) Regresión: horarios/generar-clases-dia con token COACH -> 200
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = await c.post(f"/api/v1/horarios/generar-clases-dia?fecha={hoy}", headers=hCoach)
        record("REGR: generar-clases-dia (coach token)", 200, r.status_code,
               r.status_code == 200, r.text[:120])


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
    total = len(RESULTS)
    passed = sum(1 for x in RESULTS if x)
    print(f"\nRESULTADO (Postgres real): {passed}/{total} PASS")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()


