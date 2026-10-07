"""Categoría "Plan sin usar": compró un plan vigente y todavía no estrenó ninguna clase.

Una sola definición (`churn_service.es_plan_sin_usar`) la comparten el populate del BI, el
servido EN VIVO de `GET /kpis/churn` y la plantilla/sugerencia de Fidelización: la
recomendación del churn, el `contexto` de la plantilla y la regla de `sugerir` no pueden
divergir (si divergen, la fila dice una cosa y el correo propone otra).

  A. PURAS (sin BD): la aritmética de `es_plan_sin_usar` (margen mínimo, "nunca asistió",
     "última asistencia anterior al inicio del plan") y el orden de `recomendacion_churn`
     (plan_sin_usar va ANTES que las señales del modelo, DESPUÉS de "sin plan").
  B. SERVICIO contra TEST (escribe y RESTAURA): un alumno con plan vigente y 0 asistencias se
     detecta por `plan_sin_usar`/`plan_sin_usar_lote` y `sugerir` propone la plantilla
     "plan_sin_usar" (no inactividad).

Correr (aislado):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_plan_sin_usar.py -q --noconftest
"""
import sys
from datetime import date, datetime, time as _time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import churn_service                                    # noqa: E402
from app.services import fidelizacion_plantillas as svc                    # noqa: E402
from app.utils.santiago import SANTIAGO                                    # noqa: E402

TENANT_ID = 1


# ══════════════════════════════════════════════════════════════════════════════
# A. Puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_es_plan_sin_usar_puro():
    hoy = date(2026, 11, 10)
    inicio = date(2026, 10, 31)                 # el plan arrancó hace 10 días
    # nunca asistió -> sin usar
    assert churn_service.es_plan_sin_usar(True, inicio, None, hoy) is True
    # última asistencia ANTES del inicio (venía de otro plan) -> sin usar
    assert churn_service.es_plan_sin_usar(True, inicio, date(2026, 10, 1), hoy) is True
    # asistió DESPUÉS del inicio -> lo estrenó
    assert churn_service.es_plan_sin_usar(True, inicio, date(2026, 11, 5), hoy) is False
    # sin plan vigente -> nunca
    assert churn_service.es_plan_sin_usar(False, inicio, None, hoy) is False
    # sin fecha de inicio -> dato incompleto: no afirmamos nada
    assert churn_service.es_plan_sin_usar(True, None, None, hoy) is False


def test_a2_margen_minimo_del_plan():
    hoy = date(2026, 11, 10)
    # arrancó hace 4 días (< margen 5): todavía no es "sin usar"
    assert churn_service.es_plan_sin_usar(True, date(2026, 11, 6), None, hoy) is False
    # justo el margen (5 días): ya cuenta
    assert churn_service.es_plan_sin_usar(True, date(2026, 11, 5), None, hoy) is True
    assert churn_service.DIAS_MINIMOS_PLAN_SIN_USAR == 5


def test_a3_recomendacion_plan_sin_usar_gana_sobre_las_senales():
    """Con plan + sin estrenar gana `plan_sin_usar`, aunque venza lejos y el riesgo sea ALTO."""
    txt, cod = churn_service.recomendacion_churn(
        "ALTO", True, 30, 0, 0, es_plan_sin_usar=True)
    assert cod == "plan_sin_usar"
    assert txt == churn_service.RECO_PLAN_SIN_USAR


def test_a4_sin_plan_gana_sobre_plan_sin_usar():
    """Sin plan vigente manda la #1 ("sin plan"): no puede haber "plan sin usar" sin plan."""
    _, cod = churn_service.recomendacion_churn(
        "ALTO", False, None, 0, 0, es_plan_sin_usar=True)
    assert cod == "sin_plan"


def test_a5_sin_el_flag_no_aparece_plan_sin_usar():
    _, cod = churn_service.recomendacion_churn(
        "ALTO", True, 30, 0, 0, es_plan_sin_usar=False)
    assert cod != "plan_sin_usar"


def test_a6_el_codigo_esta_en_el_catalogo():
    assert "plan_sin_usar" in churn_service.RECO_CODIGOS


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
    """Alumno con UN plan vigente (vence en 20 días) y CERO asistencias: 'plan sin usar'."""
    from app.utils.santiago import hoy_santiago
    hoy = hoy_santiago()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    correo = f"psu.{sufijo}@test.local"
    plan_nombre = f"Plan Sin Usar TEST {sufijo}"
    alumno_id = plan_id = None
    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Plan Sin Usar (prueba)', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"97{sufijo[-8:]}-9", "c": correo,
             "alta": datetime.combine(hoy - timedelta(days=40), _time(12, 0), tzinfo=SANTIAGO)}
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
             "i": datetime.combine(hoy - timedelta(days=10), _time(12, 0), tzinfo=SANTIAGO),
             "f": datetime.combine(hoy + timedelta(days=20), _time(12, 0), tzinfo=SANTIAGO)})
        db.commit()
        yield {"alumno_id": alumno_id, "correo": correo, "plan_id": plan_id}
    finally:
        db.rollback()
        try:
            db.execute(text("DELETE FROM predictions_churn WHERE usuario_id = :a"),
                       {"a": alumno_id})
            db.execute(text("DELETE FROM asistencias WHERE usuario_id = :a"), {"a": alumno_id})
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


def test_b1_plan_sin_usar_se_detecta(db, escenario):
    """El servicio (y el lote del panel) reconocen el plan pagado y sin estrenar."""
    alumno = _alumno(db, escenario)
    fila = churn_service.plan_sin_usar(db, alumno)
    assert fila is not None
    assert fila[1].nombre                       # (Suscripcion, Plan): el plan trae nombre
    lote = churn_service.plan_sin_usar_lote(db, TENANT_ID, [alumno.id])
    assert alumno.id in lote


def test_b2_sugerir_propone_la_plantilla_plan_sin_usar(db, escenario):
    """La regla #2 de `sugerir` gana sobre inactividad (el plan vence lejos): misma definición."""
    alumno = _alumno(db, escenario)
    sug = svc.sugerir(db, alumno)
    assert sug["plantilla"] == svc.P_PLAN_SIN_USAR
    assert sug["contexto"].get("plan_sin_usar") is True

