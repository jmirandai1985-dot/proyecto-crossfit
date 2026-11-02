"""
creditos_gratis (Fase 5): confirmación del premio de créditos — integración.

Cubre el flujo que TOCA créditos llamando directo al service (sin TestClient),
contra la rama TEST:

  * confirmar `creditos_gratis` suma `valor_premio` a `creditos_totales` y
    `creditos_disponibles` de la suscripción vigente;
  * plan ilimitado (créditos NULL) → no-op, con `aviso` para el admin;
  * sin suscripción vigente → `status="pendiente"` (no falla ni se pierde).

    ENVIRONMENT=test py -3.12 -m pytest tests/test_creditos_gratis.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import promociones_referidos_service as promos_svc  # noqa: E402
# El flush ORM de `Suscripcion` resuelve su FK `pago_id -> pagos.id`: registrar
# el modelo evita `NoReferencedTableError` en tests sin TestClient.
from app.models.pago import Pago  # noqa: F401, E402

TENANT_ID = 1


@pytest.fixture()
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    session = SessionLocal()
    yield session
    session.close()


def _sufijo():
    return f"{datetime.now():%Y%m%d%H%M%S%f}"


def _crear_usuario(db, sufijo):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                              rol, activo, estado, created_at)
        VALUES (:t, :r, 'Alumno creditos_gratis', :c, 'x', 'alumno', true,
                'activo', :alta)
        RETURNING id
    """), {"t": TENANT_ID, "r": f"97{sufijo[-8:]}-9",
           "c": f"creditosgratis.{sufijo}@test.local",
           "alta": datetime.now(timezone.utc)}).scalar()


def _crear_plan(db, sufijo, creditos, es_ilimitado):
    return db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado,
                            precio_clp, duracion_dias, activo, es_comercial)
        VALUES (:t, :n, :c, :i, 30000, 30, true, true)
        RETURNING id
    """), {"t": TENANT_ID, "n": f"Plan cg {sufijo}", "c": creditos,
           "i": es_ilimitado}).scalar()


def _crear_suscripcion(db, usuario_id, plan_id, creditos, dias=10):
    ahora = datetime.now(timezone.utc)
    return db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                   creditos_totales, creditos_disponibles,
                                   fecha_inicio, fecha_expiracion)
        VALUES (:t, :u, :p, 'activo', :ct, :cd, :ini, :fin)
        RETURNING id
    """), {"t": TENANT_ID, "u": usuario_id, "p": plan_id,
           "ct": creditos, "cd": creditos, "ini": ahora,
           "fin": ahora + timedelta(days=dias)}).scalar()


def _crear_promocion(db, sufijo, valor):
    return db.execute(text("""
        INSERT INTO promociones_referidos (tenant_id, nombre,
            umbral_referidos_convertidos, periodo, tipo_premio, valor_premio,
            activo)
        VALUES (:t, :n, 1, 'mensual', 'creditos_gratis', :v, true)
        RETURNING id
    """), {"t": TENANT_ID, "n": f"Créditos gratis {sufijo}",
           "v": valor}).scalar()


def _crear_deteccion(db, promocion_id, usuario_id, valor):
    return db.execute(text("""
        INSERT INTO promociones_referidos_detectadas (
            promocion_id, usuario_id, periodo_cumplido, nombre_promocion,
            umbral_referidos_convertidos, tipo_premio, valor_premio, estado)
        VALUES (:p, :u, :per, 'Créditos gratis', 1, 'creditos_gratis', :v,
                'pendiente_confirmacion')
        RETURNING id
    """), {"p": promocion_id, "u": usuario_id,
           "per": datetime.now().strftime('%Y-%m'), "v": valor}).scalar()


def _admin_id(db):
    fila = db.execute(text(
        "SELECT id FROM usuarios WHERE tenant_id = :t AND rol = 'administrador' "
        "AND estado = 'activo' ORDER BY id LIMIT 1"), {"t": TENANT_ID}).first()
    return int(fila.id) if fila else None


def _creditos_de(db, suscripcion_id):
    return db.execute(text(
        "SELECT creditos_totales, creditos_disponibles FROM suscripciones "
        "WHERE id = :s"), {"s": suscripcion_id}).first()


def _limpiar(db, usuario_id, plan_id, promocion_id):
    db.execute(text(
        "DELETE FROM promociones_referidos_detectadas WHERE usuario_id = :u"),
        {"u": usuario_id})
    db.execute(text("DELETE FROM promociones_referidos WHERE id = :p"),
               {"p": promocion_id})
    db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :u"),
               {"u": usuario_id})
    if plan_id is not None:
        db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
    db.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": usuario_id})


def test_confirmar_creditos_gratis_suma_al_plan_vigente(db):
    admin_id = _admin_id(db)
    if admin_id is None:
        pytest.skip("TEST no tiene un administrador activo en el box 1")

    sufijo = _sufijo()
    usuario = _crear_usuario(db, sufijo)
    plan = _crear_plan(db, sufijo, creditos=10, es_ilimitado=False)
    suscripcion = _crear_suscripcion(db, usuario, plan, creditos=4)
    promocion = _crear_promocion(db, sufijo, valor=5)
    deteccion = _crear_deteccion(db, promocion, usuario, valor=5)
    db.commit()

    try:
        resultado = promos_svc.confirmar_deteccion(
            db, tenant_id=TENANT_ID, deteccion_id=deteccion,
            admin_id=admin_id)
        db.commit()

        assert resultado["status"] == "confirmado"
        assert resultado["creditos_otorgados"] == 5
        assert resultado["aviso"] is None

        guardada = _creditos_de(db, suscripcion)
        assert int(guardada.creditos_totales) == 9
        assert int(guardada.creditos_disponibles) == 9
    finally:
        db.rollback()
        _limpiar(db, usuario, plan, promocion)
        db.commit()


def test_confirmar_creditos_gratis_en_ilimitado_no_op_con_aviso(db):
    admin_id = _admin_id(db)
    if admin_id is None:
        pytest.skip("TEST no tiene un administrador activo en el box 1")

    sufijo = _sufijo()
    usuario = _crear_usuario(db, sufijo)
    plan = _crear_plan(db, sufijo, creditos=0, es_ilimitado=True)
    suscripcion = _crear_suscripcion(db, usuario, plan, creditos=None)
    promocion = _crear_promocion(db, sufijo, valor=5)
    deteccion = _crear_deteccion(db, promocion, usuario, valor=5)
    db.commit()

    try:
        resultado = promos_svc.confirmar_deteccion(
            db, tenant_id=TENANT_ID, deteccion_id=deteccion,
            admin_id=admin_id)
        db.commit()

        assert resultado["status"] == "confirmado"
        assert resultado["creditos_otorgados"] is None
        assert "Plan ilimitado" in (resultado["aviso"] or "")

        guardada = _creditos_de(db, suscripcion)
        assert guardada.creditos_totales is None
        assert guardada.creditos_disponibles is None
    finally:
        db.rollback()
        _limpiar(db, usuario, plan, promocion)
        db.commit()


def test_confirmar_creditos_gratis_sin_plan_queda_pendiente(db):
    admin_id = _admin_id(db)
    if admin_id is None:
        pytest.skip("TEST no tiene un administrador activo en el box 1")

    sufijo = _sufijo()
    usuario = _crear_usuario(db, sufijo)
    promocion = _crear_promocion(db, sufijo, valor=5)
    deteccion = _crear_deteccion(db, promocion, usuario, valor=5)
    db.commit()

    try:
        resultado = promos_svc.confirmar_deteccion(
            db, tenant_id=TENANT_ID, deteccion_id=deteccion,
            admin_id=admin_id)
        db.commit()

        assert resultado["status"] == "pendiente"
        estado = db.execute(text(
            "SELECT estado::text FROM promociones_referidos_detectadas "
            "WHERE id = :d"), {"d": deteccion}).scalar()
        assert estado == "pendiente_confirmacion"
    finally:
        db.rollback()
        _limpiar(db, usuario, None, promocion)
        db.commit()
