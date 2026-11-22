"""`ticket_promedio.por_plan` incluye las compras EN COLA (referencia 'solicitud_plan').

Escenario (integración contra la MISMA rama TEST que ve la API):

  1. Plan A con una suscripción PAGADA vigente para un alumno (la regla de la
     cola exige que el alumno ya tenga un plan pagado "corriendo").
  2. Compra del plan B aprobada mientras el plan A sigue vigente:
     la solicitud queda `en_cola` y la transacción se registra con
     `referencia_tipo='solicitud_plan'` y `referencia_id = solicitudes_planes.id`.
  3. `GET /api/v1/kpis/financiero`: el plan B debe aparecer con esa compra y la
     suma de `por_plan[].ingreso_total` debe coincidir con el global.
  4. Compra NORMAL del mismo plan B (otro alumno, sin plan vigente): la
     transacción usa `referencia_tipo='suscripcion'`. El plan B debe quedar con
     n=2, ingreso_total=suma y ticket=promedio (regresión de doble conteo).

Antes del fix, el paso 3 fallaba: el `LEFT JOIN` filtraba
`t.referencia_tipo = 'suscripcion'` y la compra en cola quedaba fuera del
desglose por plan aunque sí estaba en el global.

Correr (Jebbus; requiere la rama TEST de Neon, escribe y limpia):
    cd backend
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_kpis_por_plan_cola.py -q --noconftest
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Sin `app.main`, el ORM necesita TODAS las tablas registradas (FKs del mapper).
import app.models  # noqa: E402,F401
from app.core.config import is_test_db_url, settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models.plan import Plan  # noqa: E402
from app.models.solicitud_plan import SolicitudPlan  # noqa: E402
from app.models.suscripcion import EstadoSuscripcion, Suscripcion  # noqa: E402
from app.models.transaccion_financiera import TransaccionFinanciera  # noqa: E402
from app.models.usuario import RolUsuario, Usuario  # noqa: E402

PRECIO_A = 30000
PRECIO_B = 40000


# ── Infraestructura (misma que test_matricula_cobro_integracion.py) ──────────
@pytest.fixture(scope="module")
def db():
    """Sesión contra la rama TEST (falla cerrado si la URL no es de test)."""
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (in-process, sin uvicorn)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _sufijo() -> str:
    return f"{datetime.now():%Y%m%d%H%M%S%f}"


def _crear_box(db, *, matricula_activa=False, monto=None) -> dict:
    """Box temporal con su admin (el admin tiene que existir: `aprobado_por` es FK)."""
    sufijo = _sufijo()
    tenant_id = db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo,
                             matricula_activa, matricula_monto_clp,
                             matricula_activada_en, created_at)
        VALUES (:n, :s, :p, true, :act, :monto,
                CASE WHEN :act THEN now() ELSE NULL END, now())
        RETURNING id
    """), {"n": f"Box kpi cola {sufijo}", "s": f"box-kpi-cola-{sufijo}",
           "p": str(uuid.uuid4()), "act": bool(matricula_activa),
           "monto": monto}).scalar()
    admin = _crear_usuario(db, tenant_id, "administrador",
                           f"kpi.admin.{sufijo}@test.local")
    db.commit()
    return {"tenant_id": tenant_id, "admin_id": admin.id, "sufijo": sufijo}


def _crear_usuario(db, tenant_id: int, rol: str, correo: str) -> Usuario:
    usuario = Usuario(
        tenant_id=tenant_id,
        rut=f"9{uuid.uuid4().hex[:8]}-9",
        nombre=f"KPI {rol} {correo[:10]}",
        correo=correo,
        password_hash="no-se-usa-en-este-test",
        rol=RolUsuario(rol),
        activo=True,
        estado="activo",
    )
    db.add(usuario)
    db.flush()
    return usuario


def _crear_plan(db, tenant_id: int, nombre: str, *, precio,
                duracion=30, genero="masculino", comercial=True) -> Plan:
    plan = Plan(
        tenant_id=tenant_id, nombre=nombre, creditos=10, es_ilimitado=False,
        precio_clp=precio, duracion_dias=duracion, activo=True,
        es_comercial=comercial, es_estudiante=False,
        requiere_certificado_estudiante=False, genero=genero,
    )
    db.add(plan)
    db.flush()
    return plan


def _crear_suscripcion(db, tenant_id: int, alumno_id: int, plan_id: int,
                       estado: str, *, dias=30) -> Suscripcion:
    ahora = datetime.now(timezone.utc)
    suscripcion = Suscripcion(
        tenant_id=tenant_id, usuario_id=alumno_id, plan_id=plan_id,
        # La columna es un ENUM nativo: se normaliza al miembro del enum.
        estado=EstadoSuscripcion(estado),
        fecha_inicio=ahora - timedelta(days=1),
        fecha_expiracion=ahora + timedelta(days=dias),
        creditos_totales=10, creditos_disponibles=10,
    )
    db.add(suscripcion)
    db.flush()
    return suscripcion


def _token(usuario_id: int, tenant_id: int, rol: str) -> dict:
    token = create_access_token({
        "usuario_id": usuario_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"kpi.{rol}@test.local",
    })
    return {"Authorization": "Bearer " + token}


def _limpiar(db, tenant_id: int) -> None:
    """Borra el box temporal en el orden que exigen las FKs sin CASCADE."""
    db.rollback()
    try:
        ids = {"t": tenant_id}
        db.execute(text(
            "DELETE FROM notificaciones WHERE alumno_id IN "
            "(SELECT id FROM usuarios WHERE tenant_id = :t)"), ids)
        db.execute(text(
            "DELETE FROM notificaciones_enviadas WHERE alumno_id IN "
            "(SELECT id FROM usuarios WHERE tenant_id = :t)"), ids)
        db.execute(text("DELETE FROM solicitudes_planes WHERE tenant_id = :t"), ids)
        db.execute(text("DELETE FROM tenants WHERE id = :t"), ids)
        db.commit()
    except Exception as error:  # pragma: no cover - best-effort de limpieza
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el box {tenant_id}: {error}\n")


def _solicitar(cliente, token, tenant_id, alumno_id, plan_id):
    return cliente.post("/api/v1/solicitudes/solicitar", json={
        "tenant_id": tenant_id, "alumno_id": alumno_id, "plan_id": plan_id,
        "voucher_url": "test://voucher.png",
    }, headers=token)


def _aprobar(cliente, admin, solicitud_id):
    return cliente.put(f"/api/v1/solicitudes/{solicitud_id}/aprobar",
                       headers=admin)


# ── El test ──────────────────────────────────────────────────────────────────
def test_por_plan_incluye_compra_en_cola_y_no_duplica(cliente, db):
    box = _crear_box(db, matricula_activa=False)
    tenant = box["tenant_id"]
    sufijo = box["sufijo"]
    nombre_a = f"Plan A {sufijo}"
    nombre_b = f"Plan B {sufijo}"
    try:
        admin = _token(box["admin_id"], tenant, "administrador")
        plan_a = _crear_plan(db, tenant, nombre_a, precio=PRECIO_A)
        plan_b = _crear_plan(db, tenant, nombre_b, precio=PRECIO_B)
        plan_a_id, plan_b_id = plan_a.id, plan_b.id

        alumno_cola = _crear_usuario(db, tenant, "alumno",
                                     f"kpi.cola.{sufijo}@test.local")
        alumno_cola_id = alumno_cola.id
        # Plan A pagado y vigente: la compra de B tiene que quedar EN COLA.
        _crear_suscripcion(db, tenant, alumno_cola_id, plan_a_id, "activo")
        db.commit()

        # ── (b) Compra en cola al plan B ────────────────────────────────────
        token_cola = _token(alumno_cola_id, tenant, "alumno")
        creada = _solicitar(cliente, token_cola, tenant, alumno_cola_id,
                            plan_b_id)
        assert creada.status_code == 201, creada.text
        sol_cola_id = creada.json()["id"]

        aprobada = _aprobar(cliente, admin, sol_cola_id)
        assert aprobada.status_code == 200, aprobada.text
        assert aprobada.json().get("estado") == "en_cola", aprobada.text

        db.rollback()
        sol_cola = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == sol_cola_id).one()
        assert sol_cola.estado == "en_cola"
        tx_cola = db.query(TransaccionFinanciera).filter(
            TransaccionFinanciera.tenant_id == tenant,
            TransaccionFinanciera.referencia_tipo == "solicitud_plan",
            TransaccionFinanciera.referencia_id == sol_cola_id,
        ).one()
        assert tx_cola.tipo == "ingreso"
        assert tx_cola.categoria == "membresia"
        assert tx_cola.monto == PRECIO_B

        # ── (c-d) El KPI por plan incluye la compra en cola UNA vez ─────────
        kpi = cliente.get("/api/v1/kpis/financiero", headers=admin)
        assert kpi.status_code == 200, kpi.text
        data = kpi.json()["ticket_promedio"]
        por_plan = {fila["plan"]: fila for fila in data["por_plan"]}
        assert nombre_a in por_plan and nombre_b in por_plan, por_plan

        fila_a = por_plan[nombre_a]
        fila_b = por_plan[nombre_b]
        assert fila_b["n_transacciones"] == 1, por_plan
        assert fila_b["ingreso_total"] == float(PRECIO_B), por_plan
        assert fila_b["ticket_promedio"] == float(PRECIO_B), por_plan
        assert fila_a["n_transacciones"] == 0, por_plan
        assert fila_a["ingreso_total"] == 0.0, por_plan
        assert (sum(f["ingreso_total"] for f in data["por_plan"])
                == data["ingreso_total"]), (
            "la suma del desglose por plan tiene que cuadrar con el global")

        # ── (e) Compra NORMAL al mismo plan B (otro alumno, sin plan) ───────
        alumno_normal = _crear_usuario(db, tenant, "alumno",
                                       f"kpi.normal.{sufijo}@test.local")
        alumno_normal_id = alumno_normal.id
        db.commit()

        token_normal = _token(alumno_normal_id, tenant, "alumno")
        creada2 = _solicitar(cliente, token_normal, tenant, alumno_normal_id,
                             plan_b_id)
        assert creada2.status_code == 201, creada2.text
        sol_normal_id = creada2.json()["id"]

        aprobada2 = _aprobar(cliente, admin, sol_normal_id)
        assert aprobada2.status_code == 200, aprobada2.text
        assert aprobada2.json().get("estado") != "en_cola", aprobada2.text

        db.rollback()
        sol_normal = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == sol_normal_id).one()
        assert sol_normal.estado == "approved"
        susc_normal = db.query(Suscripcion).filter(
            Suscripcion.tenant_id == tenant,
            Suscripcion.usuario_id == alumno_normal_id,
            Suscripcion.plan_id == plan_b_id,
        ).one()
        tx_normal = db.query(TransaccionFinanciera).filter(
            TransaccionFinanciera.tenant_id == tenant,
            TransaccionFinanciera.referencia_tipo == "suscripcion",
            TransaccionFinanciera.referencia_id == susc_normal.id,
        ).one()
        assert tx_normal.categoria == "membresia"
        assert tx_normal.monto == PRECIO_B

        kpi2 = cliente.get("/api/v1/kpis/financiero", headers=admin)
        assert kpi2.status_code == 200, kpi2.text
        data2 = kpi2.json()["ticket_promedio"]
        por_plan2 = {fila["plan"]: fila for fila in data2["por_plan"]}
        fila_b2 = por_plan2[nombre_b]
        assert fila_b2["n_transacciones"] == 2, por_plan2
        assert fila_b2["ingreso_total"] == float(PRECIO_B * 2), por_plan2
        assert fila_b2["ticket_promedio"] == float(PRECIO_B), por_plan2
        assert (sum(f["ingreso_total"] for f in data2["por_plan"])
                == data2["ingreso_total"]), (
            "la compra normal no puede duplicar la de cola")
    finally:
        _limpiar(db, tenant)


