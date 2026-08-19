"""Harness de validacion Fase 1 - SQLite local (no depende de la BD de test)."""
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./_fase1_validation.db"
os.environ["JWT_SECRET_KEY"] = "fase1_validation_secret_no_placeholder_1234567890"
os.environ["SENTRY_DSN"] = ""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.database as db_module
from app.main import app
from app.core.security import create_access_token

DB_FILE = "_fase1_validation.db"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

engine = create_engine(f"sqlite:///{DB_FILE}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

db_module.engine = engine
db_module.SessionLocal = SessionLocal

DDL = """
CREATE TABLE tenants (
  id INTEGER PRIMARY KEY, nombre TEXT, subdomain TEXT, activo INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE usuarios (
  id INTEGER PRIMARY KEY, tenant_id INTEGER, rut TEXT, nombre TEXT, telefono TEXT,
  correo TEXT, password_hash TEXT, rol TEXT, activo INTEGER, estado TEXT,
  cambiar_password_al_login INTEGER, peso_kg REAL, estatura_cm INTEGER, genero TEXT,
  fecha_nacimiento TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE planes (
  id INTEGER PRIMARY KEY, tenant_id INTEGER, nombre TEXT, creditos INTEGER,
  es_ilimitado INTEGER, genero TEXT, es_estudiante INTEGER,
  requiere_certificado_estudiante INTEGER, precio_clp INTEGER, duracion_dias INTEGER,
  activo INTEGER, primera_clase_tomada INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE movimientos (
  id INTEGER PRIMARY KEY, tenant_id INTEGER, nombre TEXT, descripcion TEXT,
  categoria TEXT, activo INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE historial_rm (
  id INTEGER PRIMARY KEY, tenant_id INTEGER, alumno_id INTEGER, movimiento_id INTEGER,
  peso_kg REAL, tipo_rm TEXT, valor_extra TEXT, repeticiones INTEGER, series INTEGER,
  minutos INTEGER, vueltas INTEGER, km REAL, calorias INTEGER, fecha TEXT,
  notas TEXT, nivel_calculado TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE suscripciones (
  id INTEGER PRIMARY KEY, tenant_id INTEGER, usuario_id INTEGER, plan_id INTEGER,
  estado TEXT, creditos_totales INTEGER, creditos_disponibles INTEGER,
  fecha_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP, fecha_expiracion TIMESTAMP, voucher_url TEXT,
  aprobado_por INTEGER, es_compra_emergencia INTEGER, puede_comprar_emergencia INTEGER,
  fecha_compra_emergencia TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE notificaciones (
  id INTEGER PRIMARY KEY, alumno_id INTEGER, tipo TEXT, mensaje TEXT,
  leida INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE solicitudes_planes (
  id INTEGER PRIMARY KEY, tenant_id INTEGER, alumno_id INTEGER, plan_id INTEGER,
  estado TEXT, voucher_url TEXT, certificado_estudiante_url TEXT,
  comentario_admin TEXT, aprobado_por INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE auditoria (
  id INTEGER PRIMARY KEY, tenant_id INTEGER, usuario_id INTEGER, accion TEXT,
  entidad TEXT, entidad_id INTEGER, detalle TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
now = datetime.now(timezone.utc)
hace_48h = now - timedelta(hours=48)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def seed():
    with engine.begin() as conn:
        for stmt in DDL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.exec_driver_sql(stmt)
        conn.exec_driver_sql(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) VALUES "
            "(1, 'Box A', 'boxa', 1, ?), (2, 'Box B', 'boxb', 1, ?)",
            (fmt(now), fmt(now)))
        conn.exec_driver_sql(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) VALUES "
            "(101, 1, '11111111-1', 'Alumno A', 'a@test.cl', 'x', 'alumno', 1, 'activo'),"
            "(102, 1, '22222222-2', 'Alumno B', 'b@test.cl', 'x', 'alumno', 1, 'activo'),"
            "(103, 1, '33333333-3', 'Coach 1', 'coach@test.cl', 'x', 'coach', 1, 'activo'),"
            "(104, 1, '44444444-4', 'Admin 1', 'admin@test.cl', 'x', 'administrador', 1, 'activo'),"
            "(105, 2, '55555555-5', 'Alumno OtroBox', 'otro@test.cl', 'x', 'alumno', 1, 'activo')")
        conn.exec_driver_sql(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, precio_clp, duracion_dias, activo) VALUES "
            "(1, 1, 'Plan 30', 16, 0, 50000, 30, 1)")
        conn.exec_driver_sql(
            "INSERT INTO movimientos (id, tenant_id, nombre, categoria, activo) VALUES (1, 1, 'Back Squat', 'fuerza', 1)")
        conn.exec_driver_sql(
            "INSERT INTO historial_rm (id, tenant_id, alumno_id, movimiento_id, peso_kg, tipo_rm, fecha, created_at, updated_at) VALUES "
            f"(1001, 1, 102, 1, 100.0, 'peso', '2026-08-10', '{fmt(hace_48h)}', '{fmt(hace_48h)}'),"
            f"(1002, 1, 101, 1, 120.0, 'peso', '2026-08-10', '{fmt(hace_48h)}', '{fmt(hace_48h)}')")
        conn.exec_driver_sql(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, creditos_totales, creditos_disponibles, "
            "fecha_inicio, fecha_expiracion, puede_comprar_emergencia) VALUES "
            f"(1, 1, 101, 1, 'activo', 16, 9, '{fmt(now)}', '{fmt(now + timedelta(days=20))}', 1)")
        conn.exec_driver_sql(
            "INSERT INTO notificaciones (id, alumno_id, tipo, mensaje, leida, created_at) VALUES "
            f"(1, 101, 'aprobado', 'para A', 0, '{fmt(now)}'),"
            f"(2, 102, 'aprobado', 'para B', 0, '{fmt(now)}')")


def token(user_id, tenant_id, rol):
    return create_access_token({
        "usuario_id": user_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"u{user_id}@test.cl", "nombre": f"u{user_id}",
    })
from httpx import ASGITransport, AsyncClient

RESULTS = []


def record(caso, esperado, obtenido, ok, detalle=""):
    RESULTS.append(ok)
    estado = "PASS" if ok else "FAIL"
    print(f"[{estado}] {caso}\n      esperado={esperado} obtenido={obtenido} {detalle}")


async def run_tests():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        hA = {"Authorization": f"Bearer {token(101, 1, 'alumno')}"}
        hB = {"Authorization": f"Bearer {token(102, 1, 'alumno')}"}
        hCoach = {"Authorization": f"Bearer {token(103, 1, 'coach')}"}

        # Caso 1: borrar historial_rm de otro alumno -> 403
        r = await c.delete("/api/v1/historial-rm/1001?tenant_id=1", headers=hA)
        record("DELETE /historial-rm de otro alumno", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # Caso 2: editar historial_rm de otro alumno -> 403
        r = await c.put("/api/v1/historial-rm/1001?tenant_id=1",
                        json={"peso_kg": 200}, headers=hA)
        record("PUT /historial-rm de otro alumno", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # Caso 3: editar PR propio con created_at > 24h -> 403 con mensaje
        r = await c.put("/api/v1/historial-rm/1002?tenant_id=1",
                        json={"peso_kg": 200}, headers=hA)
        ok3 = r.status_code == 403 and "24" in r.text
        record("PUT /historial-rm propio >24h", "403+msj ventana", r.status_code,
               ok3, r.text[:120])

        # Caso 4: mi-membresia con alumno_id ajeno -> 200 y datos propios
        r = await c.get("/api/v1/membresias/mi-membresia",
                        params={"tenant_id": 2, "alumno_id": 102}, headers=hA)
        body = r.json()
        ok4 = r.status_code == 200 and body.get("activa") is True
        record("GET /mi-membresia (alumno_id ajeno ignorado)", "200 propia",
               f"{r.status_code} activa={body.get('activa')}", ok4)

        # Caso 5: membresia-activa con alumno_id ajeno -> 200 y datos propios
        r = await c.get("/api/v1/planes/membresia-activa",
                        params={"tenant_id": 2, "alumno_id": 102}, headers=hA)
        body = r.json()
        ok5 = r.status_code == 200 and body.get("activa") is True
        record("GET /planes/membresia-activa (alumno_id ajeno ignorado)", "200 propia",
               f"{r.status_code} activa={body.get('activa')}", ok5)

        # Caso 6: notificaciones de otro alumno sin staff -> 403
        r = await c.get("/api/v1/notificaciones", params={"alumno_id": 102}, headers=hA)
        record("GET /notificaciones de otro alumno (sin staff)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # positivo: propias -> 200 y solo las propias
        r = await c.get("/api/v1/notificaciones", params={"alumno_id": 101}, headers=hA)
        data = r.json() if r.status_code == 200 else []
        ok_pos = r.status_code == 200 and all(n["alumno_id"] == 101 for n in data) and len(data) == 1
        record("GET /notificaciones propias", "200 solo A", f"{r.status_code} n={len(data)}",
               ok_pos)

        # staff puede ver las de otro (coach) -> 200
        r = await c.get("/api/v1/notificaciones", params={"alumno_id": 102}, headers=hCoach)
        record("GET /notificaciones de otro (coach)", 200, r.status_code,
               r.status_code == 200, r.text[:60])
        # Caso 7: solicitudes/solicitar con alumno_id ajeno sin staff -> 403
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": 2, "alumno_id": 102, "plan_id": 1,
                               "voucher_url": "/static/uploads/x.jpg"}, headers=hA)
        record("POST /solicitudes/solicitar (alumno ajeno, no staff)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # positivo: alumno propio -> 201
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": 1, "alumno_id": 101, "plan_id": 1,
                               "voucher_url": "/static/uploads/x.jpg"}, headers=hA)
        record("POST /solicitudes/solicitar (propio)", 201, r.status_code,
               r.status_code == 201, r.text[:80])
        limpiar_solicitudes()

        # staff en nombre de alumno del box -> 201
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": 1, "alumno_id": 101, "plan_id": 1}, headers=hCoach)
        record("POST /solicitudes/solicitar (coach por alumno)", 201, r.status_code,
               r.status_code == 201, r.text[:80])
        limpiar_solicitudes()

        # staff con alumno de OTRO tenant -> 403
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": 2, "alumno_id": 105, "plan_id": 1}, headers=hCoach)
        record("POST /solicitudes/solicitar (coach, alumno de otro box)", 403, r.status_code,
               r.status_code == 403, r.text[:80])

        # Caso 8: POST /auditoria fue RETIRADO (Tarea 1) -> 405
        r = await c.post("/api/v1/auditoria",
                         json={"tenant_id": 1, "accion": "CREATE", "entidad": "x"})
        record("POST /auditoria retirado (405)", 405, r.status_code,
               r.status_code == 405, r.text[:60])

        # Tarea 1: auditoría INTERNA — aprobar comprobante genera entrada
        hAdmin = {"Authorization": f"Bearer {token(104, 1, 'administrador')}"}
        # crear una solicitud como alumno propio (201)
        r = await c.post("/api/v1/solicitudes/solicitar",
                         json={"tenant_id": 1, "alumno_id": 101, "plan_id": 1,
                               "voucher_url": "/static/uploads/v.jpg"}, headers=hA)
        sol_id = r.json().get("id") if r.status_code == 201 else None
        limpiar_solicitudes(sol_id)
        # aprobar como admin
        r = await c.put(f"/api/v1/solicitudes/{sol_id}/aprobar", headers=hAdmin)
        with engine.connect() as conn:
            n = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM auditoria WHERE entidad='solicitud_plan' "
                "AND accion='UPDATE' AND entidad_id=?", (sol_id,)).scalar()
        ok_aud_sol = r.status_code == 200 and n == 1
        record("Tarea1: aprobar comprobante -> entrada auditoria",
               "200 + 1 fila", f"{r.status_code} filas={n}", ok_aud_sol)

        # Tarea 1: auditoría INTERNA — editar rol de usuario genera entrada
        r = await c.put("/api/v1/usuarios/102", json={"rol": "coach"}, headers=hAdmin)
        with engine.connect() as conn:
            n2 = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM auditoria WHERE entidad='usuario' "
                "AND accion='UPDATE' AND entidad_id=102", ()).scalar()
        ok_aud_rol = r.status_code == 200 and n2 == 1
        record("Tarea1: editar rol -> entrada auditoria",
               "200 + 1 fila", f"{r.status_code} filas={n2}", ok_aud_rol)

        # Extra: GET /historial-rm lista solo los propios para alumno
        r = await c.get("/api/v1/historial-rm", params={"tenant_id": 1}, headers=hA)
        data = r.json() if r.status_code == 200 else []
        ok_extra = r.status_code == 200 and all(x["alumno_id"] == 101 for x in data)
        record("GET /historial-rm (alumno sin filtro -> solo propios)", "solo 101",
               f"{r.status_code} ids={[x['id'] for x in data]}", ok_extra)

        # Extra: GET /historial-rm?alumno_id=otro -> 403
        r = await c.get("/api/v1/historial-rm", params={"tenant_id": 1, "alumno_id": 102}, headers=hA)
        record("GET /historial-rm (alumno_id ajeno)", 403, r.status_code,
               r.status_code == 403, r.text[:80])


def limpiar_solicitudes(keep_id=None):
    with engine.begin() as conn:
        if keep_id:
            conn.exec_driver_sql("DELETE FROM solicitudes_planes WHERE id != ?", (keep_id,))
        else:
            conn.exec_driver_sql("DELETE FROM solicitudes_planes")


def main():
    seed()
    asyncio.run(run_tests())
    total = len(RESULTS)
    passed = sum(1 for x in RESULTS if x)
    print(f"\nRESULTADO: {passed}/{total} PASS")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()



