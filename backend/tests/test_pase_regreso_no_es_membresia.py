"""Corrección A de la F2: el "Pase de regreso" NO es una membresía — probado contra el dinero.

Qué fija este archivo
---------------------
El pase (beneficio de Fidelización) se materializa como una suscripción para que el alumno pueda
reservar sin pagar. Si contara como membresía inflaría: el MRR (y el ARPU/LTV que salen de él),
la retención y la cohorte de 30 días (un alumno "vuelve" gratis), la cuenta de "alumnos vigentes"
de Reportes y del reporte de mantenimiento, el churn del BI y el dataset del ML.

La exclusión la decide la **COLUMNA** `planes.es_comercial` (migración 037), no el nombre del
plan, a través de UN helper: `shared.estados.sql_plan_comercial()` en SQL y
`app.core.estados.plan_comercial()` en ORM. **El plan "Prueba" sigue con `es_comercial = true`**:
esta corrección no movió ninguna métrica existente (se decidió así a propósito).

  A. PURAS (sin BD): el helper, que el criterio no dependa del NOMBRE del plan, y que los cinco
     consumidores lo usen de verdad (los predicados de `metricas_service` capturando el SQL y las
     consultas de `SQL_REPORTE` del mantenimiento).
  B. CONTRA TEST (escribe y RESTAURA): un alumno con un pase VIGENTE no cambia MRR, retención,
     "vigentes" ni sus features del ML; y el MISMO escenario con `es_comercial = true` SÍ cambia
     (lo que deja afuera al pase es la columna, no su precio).

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_pase_regreso_no_es_membresia.py -q
"""
import sys
from datetime import date, datetime, time as _time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core import estados as app_estados                                # noqa: E402
from app.core.config import settings                                       # noqa: E402
from app.models.plan import Plan                                           # noqa: E402
from app.models.usuario import Usuario                                     # noqa: E402
from app.services import metricas_service as metricas                      # noqa: E402
from maintenance import mantenimiento_cloud as men                         # noqa: E402
from ml import features as ml_features                                     # noqa: E402
from shared import estados                                                 # noqa: E402
from app.utils.santiago import SANTIAGO                                    # noqa: E402

TENANT_ID = 1
PRECIO_PASE = 25000   # a propósito > 0: el precio NO es lo que lo deja afuera
# Las consultas del reporte de mantenimiento que cuentan membresías.
CLAVES_REPORTE = ("mrr", "mrr_mes_anterior", "alumnos_vigentes", "retencion_base",
                  "retencion_siguen")


# ══════════════════════════════════════════════════════════════════════════════
# A. Reglas puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
class _Resultado:
    """Resultado mínimo de `session.execute()`: sólo lo que usan las métricas."""

    def __init__(self, valor):
        self.valor = valor

    def scalar(self):
        return self.valor


class _SesionQueCaptura:
    """Sesión FALSA: guarda el SQL que se ejecutaría y devuelve valores fijos (no toca la base)."""

    def __init__(self, valores=(0,)):
        self.consultas = []
        self.valores = list(valores)

    def execute(self, sentencia, params=None):
        self.consultas.append(str(sentencia))
        return _Resultado(self.valores.pop(0) if self.valores else 0)


def test_a1_el_helper_es_una_sola_definicion():
    """El predicado sale de UN lugar: la columna `planes.es_comercial` (compartida con el job)."""
    assert estados.COLUMNA_ES_COMERCIAL == "es_comercial"
    assert estados.sql_plan_comercial() == "p.es_comercial = true"
    assert estados.sql_plan_comercial("p2") == "p2.es_comercial = true"
    # El espejo ORM (lo que usan el churn y el ML) es la MISMA columna.
    assert str(app_estados.plan_comercial(Plan.es_comercial)) == "planes.es_comercial IS true"
    assert app_estados.COLUMNA_ES_COMERCIAL == estados.COLUMNA_ES_COMERCIAL
    assert app_estados.sql_plan_comercial is estados.sql_plan_comercial


def test_a2_el_criterio_no_mira_el_nombre_del_plan():
    """Renombrar el pase no puede cambiar una métrica (por eso es columna y no una lista)."""
    assert "nombre" not in estados.sql_plan_comercial()
    assert not hasattr(estados, "PLANES_NO_COMERCIALES"), \
        "la exclusión es por columna: una lista de nombres volvería a atar la métrica al copy"


def test_a3_el_mrr_y_la_cohorte_excluyen_el_pase():
    """`metricas_service` (dinero y retención): el pase no suma y tampoco cuenta como retenido."""
    assert estados.sql_plan_comercial("p") in metricas._vigente_sql(":desde")

    sesion = _SesionQueCaptura([0])
    metricas.mrr(sesion, TENANT_ID, date.today())
    assert estados.sql_plan_comercial("p") in sesion.consultas[0]

    # Retención: la base (¿estaba vigente hace 30 días?) y "los que siguen" (¿hoy?), cada una con
    # su propio alias de `planes` (p y p2). Valores fabricados: base 5 y los 5 siguen => 100 %.
    sesion = _SesionQueCaptura([5, 5])
    retencion, base = metricas.retencion_cohorte(
        sesion, TENANT_ID, date.today() - timedelta(days=30), date.today())
    assert (retencion, base) == (100, 5)
    assert estados.sql_plan_comercial("p") in sesion.consultas[0]
    assert estados.sql_plan_comercial("p2") in sesion.consultas[1]


def test_a4_las_consultas_del_reporte_de_mantenimiento_lo_llevan():
    """`SQL_REPORTE` es la definición que corre el Cron Job: ninguna puede quedarse sin el filtro."""
    for clave in CLAVES_REPORTE:
        assert estados.sql_plan_comercial("p") in men.SQL_REPORTE[clave], clave
    assert estados.sql_plan_comercial("p2") in men.SQL_REPORTE["retencion_siguen"]
    # `bajas_mes` no cuenta membresías: no tiene (ni necesita) el filtro.
    assert estados.sql_plan_comercial("p") not in men.SQL_REPORTE["bajas_mes"]


# ══════════════════════════════════════════════════════════════════════════════
# B. Contra TEST (escribe y RESTAURA): el pase vigente y las métricas reales
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def escenario(db):
    """Alumno INACTIVO con un "Pase de regreso" VIGENTE (es_comercial=false, precio > 0).

    El precio es > 0 a propósito: así la contraprueba (marcar el plan como comercial) mueve el
    MRR y se ve que lo que excluía al pase era la COLUMNA, no su precio.
    """
    hoy = date.today()
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    correo = f"pase.regreso.{sufijo}@test.local"
    alumno_id = plan_id = None
    try:
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                  estado, created_at)
            VALUES (:t, :r, 'Alumno Pase TEST', :c, 'x', 'alumno', true, 'activo', :alta)
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"98{sufijo[-8:]}-8", "c": correo,
             "alta": datetime.combine(hoy - timedelta(days=120), _time(12, 0), tzinfo=SANTIAGO)}
        ).scalar()

        # Inactivo: su última asistencia es de hace 45 días.
        db.execute(text("""
            INSERT INTO asistencias (tenant_id, usuario_id, fecha, clase, presente)
            VALUES (:t, :u, :f, 'WOD', true)"""),
            {"t": TENANT_ID, "u": alumno_id, "f": hoy - timedelta(days=45)})

        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 3, false, :p, 7, true, false) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Pase de regreso TEST {sufijo}", "p": PRECIO_PASE}).scalar()

        db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, CAST('activo' AS estado_suscripcion), 3, 3, :i, :f)"""),
            {"t": TENANT_ID, "u": alumno_id, "p": plan_id,
             "i": datetime.combine(hoy - timedelta(days=1), _time(12, 0), tzinfo=SANTIAGO),
             "f": datetime.combine(hoy + timedelta(days=6), _time(12, 0), tzinfo=SANTIAGO)})

        db.commit()
        yield {"alumno_id": alumno_id, "plan_id": plan_id, "correo": correo}
    finally:
        db.rollback()
        try:
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                       {"a": alumno_id})
            if plan_id:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
            db.execute(text("DELETE FROM asistencias WHERE usuario_id = :a"), {"a": alumno_id})
            if alumno_id:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
            db.commit()
        except Exception as e:      # el borrado no debe tapar el fallo real del test
            db.rollback()
            print(f"\n[WARN] no se pudo limpiar el escenario: {e}")


def _vigentes(db) -> int:
    """El conteo de "alumnos vigentes" del reporte de mantenimiento (la consulta REAL)."""
    return int(db.execute(text(men.SQL_REPORTE["alumnos_vigentes"].format(tid=TENANT_ID)))
               .scalar() or 0)


def _base_cohorte(db) -> int:
    """Base de la cohorte de retención de 30 días (la de `metricas_service`)."""
    hoy = date.today()
    return metricas.retencion_cohorte(db, TENANT_ID, hoy - timedelta(days=30), hoy)[1]


def test_b1_un_pase_vigente_no_mueve_el_mrr_ni_los_vigentes(db, escenario):
    """Antes/después con el pase YA vigente: ninguna métrica de dinero o de clientes se mueve."""
    hoy = date.today()
    antes = (metricas.mrr(db, TENANT_ID, hoy), _vigentes(db), _base_cohorte(db))

    # El escenario es el que dice el nombre: existe, está VIGENTE y su plan NO es comercial.
    vigente, comercial = db.execute(text(
        "SELECT ((s.fecha_inicio AT TIME ZONE 'America/Santiago')::date"
        "        <= (now() AT TIME ZONE 'America/Santiago')::date"
        "        AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date"
        "        >= (now() AT TIME ZONE 'America/Santiago')::date), p.es_comercial "
        "FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
        "WHERE s.usuario_id = :a"), {"a": escenario["alumno_id"]}).first()
    assert (vigente, comercial) == (True, False)

    assert metricas.mrr(db, TENANT_ID, hoy) == antes[0]
    assert _vigentes(db) == antes[1]
    assert _base_cohorte(db) == antes[2]


def test_b2_la_contraprueba_es_la_columna_y_no_el_precio(db, escenario):
    """Con `es_comercial = true` el MISMO pase SÍ suma (y al volver a `false`, deja de sumar).

    Es la contraprueba del test B1: si el pase quedara afuera por su precio, marcar el plan como
    comercial no cambiaría nada. Lo que lo excluye es la columna.
    """
    hoy = date.today()
    mrr_antes = metricas.mrr(db, TENANT_ID, hoy)
    vigentes_antes = _vigentes(db)

    db.execute(text("UPDATE planes SET es_comercial = true WHERE id = :p"),
               {"p": escenario["plan_id"]})
    db.commit()
    assert metricas.mrr(db, TENANT_ID, hoy) == mrr_antes + PRECIO_PASE
    assert _vigentes(db) == vigentes_antes + 1

    db.execute(text("UPDATE planes SET es_comercial = false WHERE id = :p"),
               {"p": escenario["plan_id"]})
    db.commit()
    assert metricas.mrr(db, TENANT_ID, hoy) == mrr_antes, "volver a marcarlo lo saca otra vez"
    assert _vigentes(db) == vigentes_antes


def test_b3_los_features_del_ml_no_lo_ven_como_cliente(db, escenario):
    """Su `tiene_suscripcion_activa` es False: el modelo no puede aprender un pase como cliente."""
    hoy = date.today()
    alumno = db.query(Usuario).filter(Usuario.id == escenario["alumno_id"]).first()

    fila = ml_features.features_alumno(db, TENANT_ID, alumno, hoy)
    assert fila["tiene_suscripcion_activa"] is False
    assert fila["dias_para_vencer_plan"] is None

    # La versión AGREGADA (la que alimenta el churn del BI) dice lo mismo.
    df = ml_features.build_features(db, TENANT_ID, hoy)
    mia = df[df["usuario_id"] == escenario["alumno_id"]]
    assert len(mia) == 1
    assert not bool(mia.iloc[0]["tiene_suscripcion_activa"])

    # Y con el plan marcado como comercial sí lo ve (la misma contraprueba que en B2).
    db.execute(text("UPDATE planes SET es_comercial = true WHERE id = :p"),
               {"p": escenario["plan_id"]})
    db.commit()
    fila2 = ml_features.features_alumno(db, TENANT_ID, alumno, hoy)
    assert fila2["tiene_suscripcion_activa"] is True
    assert fila2["dias_para_vencer_plan"] is not None
    db.execute(text("UPDATE planes SET es_comercial = false WHERE id = :p"),
               {"p": escenario["plan_id"]})
    db.commit()

