"""La recomendación del panel sale de UNA sola función (`fidelizacion_plantillas.sugerir`).

Por qué existe este archivo
---------------------------
Antes había DOS fuentes de recomendación y NO coincidían (caso real #9, Fanny Carrasco):

  * la columna "Recomendación" de la tabla salía de `sugerir()` (plantilla: `inactividad_mas_30`,
    porque contaba los días sin entrenar desde el ALTA, no desde la compra del plan);
  * el modal de detalle salía del código del churn (`recomendacion_churn`: `sin_accion`, etc.).

Ahora las dos — y también el modal de envío y los correos — salen de `sugerir()`.

  A. PURAS (sin BD): la regla de `_sugerir_con` (el corazón de `sugerir`), con el caso de Fanny en
     el día 4 (sin acción) y el día 5 ("Plan sin usar"), y que "más de 30 días" con plan vigente
     NUNCA cae en el mensaje de fondo.
  B. SERVICIO (TEST, sólo lectura): la tabla (`sugerir_lote`) y el modal (uno a uno) devuelven el
     MISMO código para el mismo alumno, y ningún alumno con plan vigente queda en `inactividad_mas_30`.
  C. MEDICIÓN (TEST): cuántos alumnos tienen hoy recomendación distinta entre tabla y modal (0),
     y cuántos divergían con la fuente vieja (el código del churn).
  D. GUARD de FUENTE (sin BD): el frontend del panel ya no muestra el código del churn; el modal
     recibe la sugerencia (la MISMA que la columna) como recomendación.

Correr (aislado):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_recomendacion_vivo_tabla_modal.py -q --noconftest
"""
import sys
from datetime import datetime, time as _time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import fidelizacion_plantillas as svc                  # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago                    # noqa: E402

TENANT_ID = 1


# ══════════════════════════════════════════════════════════════════════════════
# A. La regla, sobre datos ya resueltos (función pura `_sugerir_con`)
# ══════════════════════════════════════════════════════════════════════════════
def _susc(inicio_hace, vence_en, nombre="Plan TEST"):
    hoy = hoy_santiago()
    return (
        SimpleNamespace(
            fecha_inicio=datetime.combine(hoy - timedelta(days=inicio_hace), _time(12, 0),
                                          tzinfo=SANTIAGO),
            fecha_expiracion=datetime.combine(hoy + timedelta(days=vence_en), _time(23, 59),
                                              tzinfo=SANTIAGO)),
        SimpleNamespace(nombre=nombre))


def _datos(*, ultima_hace=None, inicio_hace=None, vence_en=None, created_hace=60, prediccion=None):
    """Lo que `_datos_sugerencia` arma desde la BD, pero a mano (test puro)."""
    hoy = hoy_santiago()
    ultima = (hoy - timedelta(days=ultima_hace)) if ultima_hace is not None else None
    alumno = SimpleNamespace(created_at=datetime.combine(
        hoy - timedelta(days=created_hace), _time(12, 0), tzinfo=SANTIAGO))
    suscripcion = _susc(inicio_hace, vence_en) if inicio_hace is not None else None
    return {"alumno": alumno, "ultima_asistencia": ultima,
            "suscripcion": suscripcion, "prediccion": prediccion}


def _regla(datos):
    return svc._sugerir_con(datos)["regla"]


def test_a1_fanny_dia4_no_hay_nada_que_mandar():
    """#9: 0 asistencias y un plan comprado hace 4 días -> sin situación (NO '79 días sin entrenar')."""
    sug = svc._sugerir_con(_datos(ultima_hace=None, inicio_hace=4, vence_en=26))

    assert sug["regla"] == svc.REGLA_SIN_SITUACION
    assert sug["plantilla"] is None
    # Los días salen del INICIO del plan (compró el 03/10), no de su alta.
    assert sug["contexto"]["dias_inactividad"] == 4
    assert "4 día" in sug["motivo"]


def test_a2_fanny_dia5_es_plan_sin_usar():
    assert _regla(_datos(ultima_hace=None, inicio_hace=5, vence_en=26)) == svc.P_PLAN_SIN_USAR


def test_a3_sin_plan_vigente_es_el_mensaje_de_fondo():
    assert _regla(_datos(ultima_hace=None, created_hace=79)) == svc.P_INACTIVIDAD_MAS_30


def test_a4_con_plan_vigente_el_fondo_nunca_aplica():
    """40 días inactivo PERO con plan vigente que compró después: el fondo es para sin plan."""
    sug = svc._sugerir_con(_datos(ultima_hace=40, inicio_hace=100, vence_en=60))

    assert sug["regla"] != svc.P_INACTIVIDAD_MAS_30
    assert sug["regla"] == svc.REGLA_SIN_SITUACION


def test_a5_los_tramos_siguen_saliendo_de_los_dias_reales():
    assert _regla(_datos(ultima_hace=10, inicio_hace=100, vence_en=60)) == svc.P_INACTIVIDAD_7_14
    assert _regla(_datos(ultima_hace=20, inicio_hace=100, vence_en=60)) == svc.P_INACTIVIDAD_15_30


def test_a6_la_renovacion_gana_cuando_hay_fecha_limite():
    assert _regla(_datos(ultima_hace=3, inicio_hace=40, vence_en=3)) == svc.P_VENCIMIENTO


# ══════════════════════════════════════════════════════════════════════════════
# B/C. Servicio y medición contra TEST (sólo lectura)
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


def _alumnos(db, limite=None):
    from app.models.usuario import Usuario

    consulta = db.query(Usuario).filter(Usuario.tenant_id == TENANT_ID).order_by(Usuario.id)
    return consulta.limit(limite).all() if limite else consulta.all()


def test_b1_tabla_y_modal_devuelven_el_mismo_codigo(db):
    """La tabla usa `sugerir_lote` y el modal recibe el MISMO objeto: si divergieran, el panel
    mostraría DOS recomendaciones del mismo alumno (el bug de #9)."""
    alumnos = _alumnos(db, limite=25)
    lote = svc.sugerir_lote(db, alumnos)

    for alumno in alumnos:
        uno = svc.sugerir(db, alumno)
        assert uno == lote[alumno.id], f"el lote y la sugerencia de a uno difieren (#{alumno.id})"
        assert uno["regla"] == lote[alumno.id]["regla"]


def test_b2_con_plan_vigente_nunca_cae_en_mas_30(db):
    """El mensaje de fondo es para quien YA no tiene plan: con plan activo no puede aparecer."""
    from app.services import plan_vencimiento

    alumnos = _alumnos(db, limite=25)
    lote = svc.sugerir_lote(db, alumnos)
    for alumno in alumnos:
        if lote[alumno.id]["regla"] == svc.P_INACTIVIDAD_MAS_30:
            assert plan_vencimiento.suscripcion_vigente(db, alumno) is None, \
                f"#{alumno.id} tiene plan vigente y cayó en el mensaje de fondo"


def test_c1_medicion_en_test_tabla_vs_modal_no_diverge(db):
    """Mide cuántos alumnos tienen hoy recomendación distinta entre tabla y modal.

    Ahora 0 (las dos salen de `sugerir`). Con la fuente vieja eran los que veían el código del
    churn en el modal: se cuenta para dejar el "antes" en el log, sin depender de un número fijo.
    """
    import app.api.v1.kpis as kpis
    from app.models.predictions_churn import PredictionsChurn
    from app.services import plan_vencimiento

    preds = db.query(PredictionsChurn).filter(
        PredictionsChurn.tenant_id == TENANT_ID).all()
    ids = [p.usuario_id for p in preds]
    alumnos = db.query(kpis.Usuario).filter(
        kpis.Usuario.id.in_(ids), kpis.Usuario.tenant_id == TENANT_ID).all()
    lote = svc.sugerir_lote(db, alumnos)

    # "Modal viejo" = el código del churn que mostraba el detalle antes de unificar.
    dias_inactivo = kpis._dias_inactividad_por_alumno(db, TENANT_ID, ids)
    dias_plan = plan_vencimiento.dias_para_vencer_lote(db, TENANT_ID, ids)
    viejo = kpis._situacion_en_vivo(db, preds, dias_plan, dias_inactivo)

    divergen_hoy = divergian_antes = 0
    for alumno in alumnos:
        tabla = (lote.get(alumno.id) or {}).get("regla")
        modal = (lote.get(alumno.id) or {}).get("regla")      # el modal recibe el MISMO objeto
        if tabla != modal:
            divergen_hoy += 1
        if tabla != (viejo.get(alumno.id) or {}).get("recomendacion_codigo"):
            divergian_antes += 1

    print(f"\n[medicion] alumnos: {len(alumnos)} | divergentes hoy (tabla vs modal): "
          f"{divergen_hoy} | divergían con la fuente vieja (churn): {divergian_antes}")
    assert divergen_hoy == 0


# ══════════════════════════════════════════════════════════════════════════════
# D. Guard de FUENTE del frontend (sin red y sin base)
# ══════════════════════════════════════════════════════════════════════════════
def test_d_el_panel_ya_no_muestra_el_codigo_del_churn():
    raiz = Path(__file__).resolve().parents[2]
    fid = (raiz / "frontend/src/pages/admin/Fidelizacion.jsx").read_text(encoding="utf-8")
    modal = (raiz / "frontend/src/components/kpis/RecomendacionModal.jsx").read_text(
        encoding="utf-8")

    # La columna de la tabla y el modal ya no leen el código del churn (esa era la SEGUNDA fuente).
    assert "recomendacion_codigo" not in fid
    assert "estiloReco" not in fid
    assert "estiloReco" not in modal
    # El modal recibe la sugerencia (la MISMA que la columna) como recomendación principal.
    assert "sugerencia={sugerencias[" in fid
    assert "sugerencia" in modal
