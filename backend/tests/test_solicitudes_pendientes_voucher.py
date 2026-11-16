"""
Solicitudes de plan: la cola del admin sólo lista las que TIENEN comprobante.

RÉPLICA DE LA PARTE I DE PEDIDOS (commit 656ef8b) para membresías: cuando el alumno
toca "Pagar con tarjeta", el backend crea la `SolicitudPlan` en `pending` ANTES de
redirigir a Mercado Pago (`origen_pago='mercadopago'`, sin voucher). Si el alumno
abandona el pago, esa solicitud queda huérfana hasta que `expirar_pendientes`
(backend/app/services/pagos.py) la cierra a los 30 min (o hasta que el alumno
apriete "Cancelar" en la pantalla de retorno, `POST /pagos/{id}/cancelar`): NO
es un comprobante que el admin deba revisar.

CONTRATO QUE SE PRUEBA ACÁ:
  GET /solicitudes/pendientes?solo_con_voucher=true
    * NO trae la solicitud ONLINE sin voucher (la cola "En revisión");
    * SÍ trae la solicitud CON comprobante (transferencia, validación manual).
  GET /solicitudes/pendientes (sin el flag)
    * SÍ trae la ONLINE: el filtro es opt-in, para no romper a otros consumidores.
  GET /admin/pendientes/resumen
    * `solicitudes` cuenta sólo la que tiene comprobante, igual que `pedidos`.

Requiere la API/BD de TEST (TestClient contra `app.main`, sin uvicorn). Todo el
escenario vive en un box TEMPORAL que se borra al final.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_solicitudes_pendientes_voucher.py -q
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import SessionLocal

API = "/api/v1"


@pytest.fixture(scope="module")
def cliente():
    """TestClient del app real (sin servidor y sin correr el lifespan)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def box():
    """Box temporal: tenant + admin + 1 alumno + 1 plan + 2 solicitudes `pending`.

    Una CON comprobante (transferencia) y otra SIN voucher (`origen_pago='mercadopago'`),
    como las deja el checkout online antes de redirigir a Mercado Pago.
    """
    from app.models.plan import Plan
    from app.models.solicitud_plan import SolicitudPlan

    db = SessionLocal()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(timezone.utc)
    tenant = None
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
            {"n": f"Box Solicitudes TEST {sufijo}",
             "s": f"box-solicitudes-{sufijo}",
             "pub": str(uuid.uuid4()), "alta": alta}).scalar()
        admin = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Admin Solicitudes TEST', :c, 'x', 'administrador',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"5{sufijo[-7:]}-1",
             "c": f"solicitudes.admin.{sufijo}@test.local", "alta": alta}).scalar()
        alumno = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Alumno Solicitudes TEST', :c, 'x', 'alumno',
                    true, 'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": f"5{sufijo[-7:]}-2",
             "c": f"solicitudes.alumno.{sufijo}@test.local", "alta": alta}).scalar()

        plan = Plan(tenant_id=tenant, nombre=f"Plan Solicitudes TEST {sufijo}",
                    precio_clp=20000)
        db.add(plan)
        db.flush()

        con_voucher = SolicitudPlan(
            tenant_id=tenant, alumno_id=alumno, plan_id=plan.id,
            estado="pending", voucher_url="test://voucher.png")
        online = SolicitudPlan(
            tenant_id=tenant, alumno_id=alumno, plan_id=plan.id,
            estado="pending", voucher_url=None, origen_pago="mercadopago")
        db.add_all([con_voucher, online])
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise

    datos = {
        "db": db, "tenant_id": tenant,
        "con_voucher_id": con_voucher.id, "online_id": online.id,
        "admin": {"Authorization": "Bearer " + create_access_token({
            "usuario_id": admin, "tenant_id": tenant, "rol": "administrador",
            "correo": "solicitudes@test.local"})},
    }
    try:
        yield datos
    finally:
        db.rollback()
        # De la hoja al tronco y cada DELETE en su savepoint: si una FK inesperada
        # rechaza uno, el resto se limpia igual y el box no queda en la BD de TEST.
        for tabla in ("solicitudes_planes", "planes", "usuarios"):
            try:
                with db.begin_nested():
                    db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"),
                               {"t": tenant})
            except Exception:
                pass
        try:
            with db.begin_nested():
                db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
        except Exception:
            pass
        db.commit()
        db.close()


# ═══════════════════════════════════════════════════════════════════
# Parte I (Solicitudes de plan) — `pending` SIN voucher fuera de la cola
# ═══════════════════════════════════════════════════════════════════

def test_sol_online_sin_voucher_fuera_de_la_cola_pero_visible_sin_filtro(box, cliente):
    """La intención de pago online no contamina la cola "En revisión", pero sigue viva.

    Confirma las dos caras del contrato:
      * NO aparece en `GET /solicitudes/pendientes?solo_con_voucher=true` (la cola);
      * SÍ aparece en `GET /solicitudes/pendientes` sin el flag (compatibilidad).
    """
    # La cola del admin (solo_con_voucher) muestra la del comprobante y oculta la online.
    r = cliente.get(f"{API}/solicitudes/pendientes", headers=box["admin"],
                    params={"solo_con_voucher": "true"})
    assert r.status_code == 200, r.text[:200]
    ids = [s["id"] for s in r.json()]
    assert box["con_voucher_id"] in ids, "la pending CON comprobante sí debe estar en la cola"
    assert box["online_id"] not in ids, \
        "la pending SIN voucher (pago online) no debe estar en la cola"

    # Sin el filtro, el listado genérico sí la trae (el flag es el que filtra).
    r_sin = cliente.get(f"{API}/solicitudes/pendientes", headers=box["admin"])
    assert r_sin.status_code == 200, r_sin.text[:200]
    online = next((s for s in r_sin.json() if s["id"] == box["online_id"]), None)
    assert online is not None, \
        "sin `solo_con_voucher` el listado genérico sigue trayendo el pago online"
    assert online["voucher_url"] is None
    assert online["origen_pago"] == "mercadopago"


def test_sol_online_sin_voucher_no_suma_en_el_resumen_de_pendientes(box, cliente):
    """El badge `solicitudes` del menú/Pendientes no cuenta la intención de pago."""
    r = cliente.get(f"{API}/admin/pendientes/resumen", headers=box["admin"])
    assert r.status_code == 200, r.text[:200]
    assert r.json()["solicitudes"] == 1, (
        "sólo la solicitud CON comprobante requiere acción del admin: la online no suma")
