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

from tests.conftest import ALUMNO_ID, BASE, TENANT_ID, get_admin_token

# Alumno creado por el seed de la suite (999). El seed resetea TEST, así que no
# se puede usar un id fijo arbitrario: el path de staff exige que el alumno
# destino pertenezca al box.
ALUMNO_PEDIDO = ALUMNO_ID

# Alumno DEDICADO (lo crea el seed) para el test que APRUEBA un plan: aprobar
# crea una suscripción ACTIVA, y si se usara el 999 quedaría con 2 activas.
# Con 2 activas, GET /planes/membresia-activa y POST /reservas eligen la fila por
# "más créditos y vence más tarde": al descontar un crédito en una, la lectura
# cambia a la otra y el saldo pareciera no bajar → rompía
# test_panel_alumno::test_07 ("Crédito no se descontó: 50 -> 50").
# Ver LOG_AISLAMIENTO_TESTS.md (mismo criterio que el 1010 de los tests de admin).
ALUMNO_PLAN = 1012


def _h_admin():
    return {"Authorization": f"Bearer {get_admin_token()}"}


def _pedido(producto_id, **extra):
    body = {"tenant_id": TENANT_ID, "alumno_id": ALUMNO_PEDIDO,
            "producto_id": producto_id, "cantidad": 1}
    body.update(extra)
    return requests.post(f"{BASE}/pedidos", headers=_h_admin(), json=body, timeout=20)


def _crear_producto(nombre, activo=True, stock=5, precio=1000):
    """Crea su propio producto (no depende del seed) y devuelve su id."""
    r = requests.post(
        f"{BASE}/productos", headers=_h_admin(),
        data={"nombre": nombre, "precio": precio, "stock": stock,
              "activo": str(activo).lower()},
        timeout=20)
    if r.status_code != 201:
        pytest.skip(f"no se pudo crear el producto de prueba: {r.status_code} {r.text[:120]}")
    pid = r.json()["id"]
    # Limpieza: lo desactivamos al terminar (el catálogo del Bazar es compartido).
    return pid


def _desactivar_producto(pid):
    try:
        requests.delete(f"{BASE}/productos/{pid}", headers=_h_admin(), timeout=20)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# B-03 — el comprobante es obligatorio
# ═══════════════════════════════════════════════════════════════════

def test_p04_pedido_sin_voucher_es_rechazado():
    """Sin `voucher_url` el POST debe ser 422 (antes: 201 con voucher_url=null)."""
    pid = _crear_producto("TEST P04 B03", activo=True)
    try:
        r = _pedido(pid)
        assert r.status_code == 422, f"status {r.status_code}: {r.text[:200]}"
        # Control: con voucher el pedido sí se crea (no rompimos el flujo normal)
        r2 = _pedido(pid, voucher_url="/privado/vouchers/test.png")
        assert r2.status_code == 201, f"con voucher: {r2.status_code} {r2.text[:200]}"
    finally:
        _desactivar_producto(pid)


# ═══════════════════════════════════════════════════════════════════
# B-02 — no se compran productos desactivados
# ═══════════════════════════════════════════════════════════════════

def test_p04_no_se_puede_comprar_producto_inactivo():
    """Un producto con activo=false debe dar 400 (antes: 201)."""
    pid = _crear_producto("TEST P04 B02", activo=False)
    try:
        r = _pedido(pid, voucher_url="/privado/vouchers/test.png")
        assert r.status_code == 400, f"status {r.status_code}: {r.text[:200]}"
        assert "no está disponible" in (r.json().get("detail") or "")
    finally:
        _desactivar_producto(pid)


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
            "SELECT id, precio_clp FROM planes ORDER BY id LIMIT 1")).first()
        if not plan:
            pytest.skip("TEST no tiene planes")
        plan_id, precio_original = plan[0], plan[1]
        # El seed de la suite deja los planes a precio 0: se le asigna un precio
        # para poder probar el snapshot (se restaura al final del test).
        precio_esperado = precio_original or 44000
        if precio_esperado != precio_original:
            db.execute(_text("UPDATE planes SET precio_clp = :p WHERE id = :i"),
                       {"p": precio_esperado, "i": plan_id})
            db.commit()
        # Alumno DEDICADO (1012, con membresía propia solo en este test). Se
        # limpian sus solicitudes PENDIENTES para que POST /solicitar no choque
        # con el "ya tienes una solicitud pendiente" (limpieza TEST-only).
        alumno_id = ALUMNO_PLAN
        db.execute(_text(
            "DELETE FROM solicitudes_planes WHERE alumno_id = :u AND estado = 'pending'"),
            {"u": alumno_id})
        db.commit()
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
            assert snapshot == precio_esperado, (
                f"la solicitud no guardó el snapshot: {snapshot} != {precio_esperado}")
            # El admin sube el precio DESPUÉS de la solicitud
            db.execute(_text("UPDATE planes SET precio_clp = :p WHERE id = :i"),
                       {"p": precio_esperado + 50000, "i": plan_id})
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
            assert int(monto) == precio_esperado, (
                f"el ingreso quedó con el precio de la APROBACIÓN ({monto}) en vez "
                f"del de la SOLICITUD ({precio_esperado})")
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
