"""
P0-4 (auditoría panel Alumno) — dinero: snapshot del precio, producto activo y
voucher obligatorio.

Reproducido en TEST el 2026-09-24, ANTES del fix:
  - POST /pedidos sin `voucher_url` -> 201 con `voucher_url: null` (pedido sin
    comprobante de pago).
  - POST /pedidos de `poleras` (producto con activo=false) -> 201: se podía
    comprar un producto retirado del catálogo con solo conocer el id.
  - Aprobar una solicitud a 44.000 con el plan subido a 99.000 entre la
    solicitud y la aprobación -> la transacción financiera quedó en 99.000
    (precio al APROBAR) en vez de 44.000 (precio al SOLICITAR).

Corre contra la API real en localhost:8000 (ENVIRONMENT=test).
"""
import os

import pytest
import requests

from tests.conftest import BASE, TENANT_ID, get_admin_token

ALUMNO_PEDIDO = 2  # alumno real de TEST sin solicitudes pendientes


def _h_admin():
    return {"Authorization": f"Bearer {get_admin_token()}"}


def _productos(activo):
    r = requests.get(f"{BASE}/productos",
                     params={"activo": str(activo).lower(), "limit": 50},
                     headers=_h_admin(), timeout=20)
    if r.status_code != 200:
        return []
    return r.json() or []


def _pedido(producto_id, **extra):
    body = {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_PEDIDO,
            "producto_id": producto_id, "cantidad": 1}
    body.update(extra)
    return requests.post(f"{BASE}/pedidos", headers=_h_admin(), json=body, timeout=20)


# ═══════════════════════════════════════════════════════════════════
# B-03 — el comprobante es obligatorio
# ═══════════════════════════════════════════════════════════════════

def test_p04_pedido_sin_voucher_es_rechazado():
    """Sin `voucher_url` el POST debe ser 422 (antes: 201 con voucher_url=null)."""
    disponibles = [p for p in _productos(True) if (p.get("stock") or 0) > 0]
    if not disponibles:
        pytest.skip("TEST no tiene productos activos con stock")
    r = _pedido(disponibles[0]["id"])
    assert r.status_code == 422, f"status {r.status_code}: {r.text[:200]}"


# ═══════════════════════════════════════════════════════════════════
# B-02 — no se compran productos desactivados
# ═══════════════════════════════════════════════════════════════════

def test_p04_no_se_puede_comprar_producto_inactivo():
    """Un producto con activo=false debe dar 400 (antes: 201)."""
    inactivos = [p for p in _productos(False) if (p.get("stock") or 0) > 0]
    if not inactivos:
        pytest.skip("TEST no tiene productos inactivos con stock")
    r = _pedido(inactivos[0]["id"], voucher_url="/privado/vouchers/test.png")
    assert r.status_code == 400, f"status {r.status_code}: {r.text[:200]}"
    assert "no está disponible" in (r.json().get("detail") or "")


# ═══════════════════════════════════════════════════════════════════
# S-01 — la aprobación usa el precio de la SOLICITUD (snapshot)
# ═══════════════════════════════════════════════════════════════════

def test_p04_aprobacion_registra_el_precio_de_la_solicitud():
    """Si el precio del plan sube entre la solicitud y la aprobación, el ingreso
    registrado debe ser el de la SOLICITUD (snapshot), no el nuevo."""
    if os.getenv("ENVIRONMENT") != "test":
        pytest.skip("toca la BD de TEST (cambia el precio del plan)")
    from sqlalchemy import text as _text
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        plan = db.execute(_text(
            "SELECT id, precio_clp FROM planes WHERE activo = true AND precio_clp > 0 "
            "ORDER BY id LIMIT 1")).first()
        if not plan:
            pytest.skip("TEST no tiene planes pagos")
        plan_id, precio_original = plan[0], plan[1]
        alumno_id = db.execute(_text(
            "SELECT id FROM usuarios WHERE rol='alumno' AND id NOT IN "
            "(SELECT alumno_id FROM solicitudes_planes WHERE estado='pending') "
            "ORDER BY id LIMIT 1")).scalar()
        if not alumno_id:
            pytest.skip("no hay alumno sin solicitud pendiente")
    finally:
        db.close()

    r = requests.post(f"{BASE}/solicitudes/solicitar", headers=_h_admin(),
                      json={"tenant_id": TENANT_ID, "alumno_id": alumno_id,
                            "plan_id": plan_id,
                            "voucher_url": "/privado/vouchers/test.png"},
                      timeout=20)
    if r.status_code != 201:
        pytest.skip(f"no se pudo crear la solicitud: {r.status_code} {r.text[:120]}")
    solicitud_id = r.json()["id"]

    try:
        db = SessionLocal()
        try:
            snapshot = db.execute(_text(
                "SELECT precio_clp_snapshot FROM solicitudes_planes WHERE id=:i"),
                {"i": solicitud_id}).scalar()
            assert snapshot == precio_original, (
                f"la solicitud no guardó el snapshot: {snapshot} != {precio_original}")
            # El admin sube el precio DESPUÉS de la solicitud
            db.execute(_text("UPDATE planes SET precio_clp = :p WHERE id = :i"),
                       {"p": precio_original + 50000, "i": plan_id})
            db.commit()
        finally:
            db.close()

        r = requests.put(f"{BASE}/solicitudes/{solicitud_id}/aprobar",
                         headers=_h_admin(), timeout=20)
        assert r.status_code == 200, f"aprobar: {r.status_code} {r.text[:200]}"

        db = SessionLocal()
        try:
            sus = db.execute(_text(
                "SELECT id FROM suscripciones WHERE usuario_id=:u ORDER BY id DESC LIMIT 1"),
                {"u": alumno_id}).scalar()
            monto = db.execute(_text(
                "SELECT monto FROM transacciones_financieras "
                "WHERE referencia_tipo='suscripcion' AND referencia_id=:r"),
                {"r": sus}).scalar()
            assert monto is not None, "no se registró la transacción del plan aprobado"
            assert int(monto) == precio_original, (
                f"el ingreso quedó con el precio de la APROBACIÓN ({monto}) en vez "
                f"del de la SOLICITUD ({precio_original})")
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            db.execute(_text("UPDATE planes SET precio_clp = :p WHERE id = :i"),
                       {"p": precio_original, "i": plan_id})
            db.commit()
        finally:
            db.close()
