"""Días para vencer el plan: UNA sola función (días de Chile, suscripción vigente).

Caso real #165 (Josefa Muñoz Martínez): su plan vence en 3 días, pero la SITUACIÓN
(columna "Motivo", snapshot del BI) decía "plan vence en 7 días" y la RECOMENDACIÓN
(calculada en vivo) decía "Su plan vence en 3 día(s)". Eran DOS rutas de cálculo: la
situación venía de un snapshot viejo de `kpis_populate` y la recomendación de
`fidelizacion_plantillas`. Ahora las dos salen de `app.services.plan_vencimiento` y el
nº de la situación se refresca EN VIVO al servir el panel, así nunca discrepan.

  A. PURAS (sin BD): la aritmética en días CALENDARIO de Chile (0 = vence hoy, nunca
     negativo, hora de Chile) y el refresco del fragmento "plan vence en N días".
  B. SERVICIO contra TEST (escribe y RESTAURA): el escenario de #165 — una suscripción
     vigente a 3 días — da el MISMO nº en la función, en la recomendación (plantilla) y
     en el lote que usa el panel.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_dias_vencimiento_unico.py -q --noconftest
"""
import sys
from datetime import datetime, time as _time, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import fidelizacion_plantillas as svc                    # noqa: E402
from app.services import plan_vencimiento as pv                            # noqa: E402
from app.utils.santiago import SANTIAGO, fecha_chile                       # noqa: E402

TENANT_ID = 1
DIAS = 3
HOY = datetime(2026, 10, 6, tzinfo=SANTIAGO).date()   # el "hoy" del caso #165


def _vence(dias, hora=23, minuto=59, segundo=59):
    """El día de vencimiento a `dias` días de HOY (hora de Chile)."""
    return datetime.combine(HOY + timedelta(days=dias),
                            _time(hora, minuto, segundo), tzinfo=SANTIAGO)


# ══════════════════════════════════════════════════════════════════════════════
# A. Puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_dias_calendario_de_chile():
    """HOY 2026-10-06, el plan vence 2026-10-09 -> 3 días (el caso #165)."""
    assert pv.dias_hasta(_vence(3), HOY) == 3


def test_a2_el_dia_de_vencimiento_cuenta_cero_y_nunca_negativo():
    assert pv.dias_hasta(_vence(0), HOY) == 0
    assert pv.dias_hasta(_vence(-2), HOY) == 0     # ya vencido: 0, nunca "-2 días"


def test_a3_sin_fecha_es_none():
    assert pv.dias_hasta(None, HOY) is None


def test_a4_usa_el_dia_de_chile_no_de_utc():
    """2026-10-09 23:59 en Chile == 2026-10-10 02:59 UTC: sigue siendo el 09 -> 3 días."""
    assert fecha_chile(_vence(3)) == datetime(2026, 10, 9).date()
    utc = datetime(2026, 10, 10, 2, 59, 59, tzinfo=timezone.utc)
    assert pv.dias_hasta(utc, HOY) == 3


def test_a5_refrescar_dias_reemplaza_el_numero():
    m = "20 días sin asistir · plan vence en 7 días"
    assert pv.refrescar_dias_plan(m, 3) == "20 días sin asistir · plan vence en 3 días"


def test_a6_refrescar_dias_singular_y_bordes():
    assert pv.refrescar_dias_plan("plan vence en 5 días", 1) == "plan vence en 1 día"
    # Sin fragmento, o sin un nº vigente, el texto queda IGUAL (no se inventa nada).
    assert pv.refrescar_dias_plan("7 días sin asistir", 3) == "7 días sin asistir"
    assert pv.refrescar_dias_plan("plan vence en 7 días", None) == "plan vence en 7 días"
    assert pv.refrescar_dias_plan(None, 3) is None


def test_a7_situacion_y_recomendacion_comparten_la_misma_funcion():
    """Los tres puntos (situación heurística/ML y recomendación) referencian EL MISMO objeto."""
    import ml.features as ml_features
    import app.api.v1.kpis as kpis
    import app.api.v1.kpis_populate as populate
    assert svc.dias_hasta is pv.dias_hasta
    assert kpis.plan_vencimiento.dias_hasta is pv.dias_hasta
    assert populate.plan_vencimiento.dias_hasta is pv.dias_hasta
    assert ml_features.dias_hasta is pv.dias_hasta


# ══════════════════════════════════════════════════════════════════════════════
# B. Servicio contra TEST (escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(usa ENVIRONMENT=test)")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def escenario(db):
    """Alumno temporal con UNA suscripción vigente que vence en DIAS días (caso #165)."""
    from app.utils.santiago import hoy_santiago
    hoy = hoy_santiago()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    correo = f"vencimiento.{sufijo}@test.local"
    plan_nombre = f"Plan Vencimiento TEST {sufijo}"
    alumno_id = plan_id = None
    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Josefa Munoz (prueba)', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"98{sufijo[-8:]}-9", "c": correo,
             "alta": datetime.combine(hoy - timedelta(days=90), _time(12, 0), tzinfo=SANTIAGO)}
        ).scalar()

        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 12, false, 33000, 30, true, true) RETURNING id"""),
            {"t": TENANT_ID, "n": plan_nombre}).scalar()

        db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, CAST('activo' AS estado_suscripcion), 12, 12, :i, :f)"""),
            {"t": TENANT_ID, "u": alumno_id, "p": plan_id,
             "i": datetime.combine(hoy - timedelta(days=27), _time(12, 0), tzinfo=SANTIAGO),
             "f": datetime.combine(hoy + timedelta(days=DIAS), _time(12, 0), tzinfo=SANTIAGO)})
        db.commit()
        yield {"alumno_id": alumno_id, "correo": correo, "plan_id": plan_id}
    finally:
        db.rollback()
        try:
            db.execute(text("DELETE FROM predictions_churn WHERE usuario_id = :a"),
                       {"a": alumno_id})
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                       {"a": alumno_id})
            if plan_id:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
            if alumno_id:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"\n[WARN] limpieza: {e}")


def _alumno(db, escenario):
    from app.models.usuario import Usuario
    return db.query(Usuario).filter(Usuario.id == escenario["alumno_id"]).first()


def test_b1_todas_las_superficies_dan_el_mismo_numero(db, escenario):
    """El nº del plan vigente es 3 en la función, en la recomendación Y en el lote del panel."""
    alumno = _alumno(db, escenario)
    assert pv.dias_para_vencer_plan(db, alumno) == DIAS

    sug = svc.sugerir(db, alumno)
    assert sug["motivo"] == f"Su plan vence en {DIAS} día(s)."
    assert sug["contexto"]["dias_para_vencer"] == DIAS

    lote = pv.dias_para_vencer_lote(db, TENANT_ID, [alumno.id])
    assert lote[alumno.id] == DIAS


def test_b2_la_situacion_se_refresca_al_mismo_numero(db, escenario):
    """El snapshot viejo ("7 días") se corrige al nº VIGENTE ("3 días") al servir el panel."""
    dias = pv.dias_para_vencer_lote(db, TENANT_ID, [escenario["alumno_id"]]).get(
        escenario["alumno_id"])
    assert dias == DIAS
    viejo = "20 días sin asistir · plan vence en 7 días"
    assert pv.refrescar_dias_plan(viejo, dias) == "20 días sin asistir · plan vence en 3 días"
    # Y el panel usa ESA función (no una copia).
    import app.api.v1.kpis as kpis
    assert kpis.plan_vencimiento.refrescar_dias_plan(viejo, dias) == \
        "20 días sin asistir · plan vence en 3 días"
