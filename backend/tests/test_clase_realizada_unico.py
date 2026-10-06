"""Definición ÚNICA de "clase realizada" (`app.services.clases_service`) y su uso en los KPIs.

Bug que cierra (2026-10): la tarjeta "Clases Impartidas" del Dashboard mostraba 559 y
"Ocupación promedio" 2.11% para el mes EN CURSO, porque contaban TODAS las clases del mes
(incluidas las futuras y las canceladas). Ahora hay UNA definición:
`realizada = no cancelada Y ya terminó (fecha < hoy Chile, o fecha = hoy y hora_fin <= ahora Chile)`.

  A. PURAS (sin BD): el clasificador `estado_clase()` en sus 4 estados + el borde hora_fin, y el
     espejo SQL `sql_clase_realizada()`.
  B. CONTRA TEST (solo lectura): el predicado SQL coincide con el clasificador Python sobre las
     clases reales; un mes CERRADO no cambia de número; y `metricas_service.ocupacion_promedio`
     deja fuera las clases futuras del mes en curso.
  C. CABLEADO: los cuatro archivos de cálculo usan la MISMA función (no una copia).

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_clase_realizada_unico.py -q --noconftest
"""
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import clases_service as cs                            # noqa: E402
from app.utils.santiago import SANTIAGO, ahora_santiago                 # noqa: E402

TENANT_ID = 1
# "Ahora" fijo (hora de Chile) para los tests puros: 2026-10-06 14:00.
AHORA = datetime(2026, 10, 6, 14, 0, tzinfo=SANTIAGO)
HOY = AHORA.date()


# ══════════════════════════════════════════════════════════════════════════════
# A. Puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_dia_pasado_es_realizada():
    ayer = HOY - timedelta(days=1)
    assert cs.estado_clase(ayer, time(9, 0), time(10, 0), False, AHORA) == cs.REALIZADA
    assert cs.es_realizada(ayer, time(9, 0), time(10, 0), False, AHORA)


def test_a2_hoy_ya_termino_es_realizada():
    # 10:00-11:00 con ahora 14:00 -> terminó.
    assert cs.estado_clase(HOY, time(10, 0), time(11, 0), False, AHORA) == cs.REALIZADA


def test_a3_hoy_en_curso():
    # 13:00-15:00 con ahora 14:00 -> en curso.
    assert cs.estado_clase(HOY, time(13, 0), time(15, 0), False, AHORA) == cs.EN_CURSO


def test_a4_hoy_no_empezo_es_proxima():
    assert cs.estado_clase(HOY, time(18, 0), time(19, 0), False, AHORA) == cs.PROXIMA


def test_a5_dia_futuro_es_proxima():
    manana = HOY + timedelta(days=1)
    assert cs.estado_clase(manana, time(9, 0), time(10, 0), False, AHORA) == cs.PROXIMA


def test_a6_cancelada_nunca_es_realizada():
    ayer = HOY - timedelta(days=1)
    assert cs.estado_clase(ayer, time(9, 0), time(10, 0), True, AHORA) == cs.CANCELADA
    assert not cs.es_realizada(ayer, time(9, 0), time(10, 0), True, AHORA)
    # Cancelada HOY, aunque ya haya pasado su hora: sigue sin contar.
    assert not cs.es_realizada(HOY, time(10, 0), time(11, 0), True, AHORA)


def test_a7_el_borde_hora_fin_es_inclusivo():
    # hora_fin EXACTA == ahora -> ya terminó (se compara con <=, no <).
    assert cs.es_realizada(HOY, time(13, 0), time(14, 0), False, AHORA)


def test_a8_el_sql_espejo_usa_las_mismas_columnas_y_la_tz_de_chile():
    sql = cs.sql_clase_realizada("c")
    assert "NOT c.cancelada" in sql
    assert "c.hora_fin" in sql
    assert "America/Santiago" in sql
    # El alias se interpola (constante del código, nunca de un request).
    assert "NOT clases.cancelada" in cs.sql_clase_realizada("clases")


# ══════════════════════════════════════════════════════════════════════════════
# B. Contra TEST (solo lectura)
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


def test_b1_el_predicado_sql_concuerda_con_el_clasificador(db):
    """Mismo veredicto en SQL y en Python, sobre las clases reales alrededor de HOY."""
    hoy = ahora_santiago().date()
    a, b = hoy - timedelta(days=2), hoy + timedelta(days=1)
    params = {"t": TENANT_ID, "a": a, "b": b}
    filas = db.execute(text(
        "SELECT id, fecha, hora_inicio, hora_fin, cancelada FROM clases "
        "WHERE tenant_id = :t AND fecha BETWEEN :a AND :b"), params).fetchall()
    if not filas:
        pytest.skip("TEST no tiene clases en la ventana de prueba")

    sql_ids = {r[0] for r in db.execute(text(
        "SELECT id FROM clases WHERE tenant_id = :t AND fecha BETWEEN :a AND :b AND "
        + cs.sql_clase_realizada("clases")), params).fetchall()}
    py_ids = {r.id for r in filas
              if cs.es_realizada(r.fecha, r.hora_inicio, r.hora_fin, r.cancelada)}
    assert sql_ids == py_ids


def test_b2_un_mes_cerrado_no_cambia_de_numero(db):
    """Para un mes ya terminado, "realizada" == "no cancelada" (todas ya terminaron)."""
    hoy = ahora_santiago().date()
    ini = (hoy.replace(day=1) - timedelta(days=1)).replace(day=1)   # 1° del mes anterior
    fin = hoy.replace(day=1) - timedelta(days=1)                    # último día del mes anterior
    params = {"t": TENANT_ID, "a": ini, "b": fin}
    total = db.execute(text(
        "SELECT COUNT(*) FROM clases WHERE tenant_id = :t AND fecha BETWEEN :a AND :b"),
        params).scalar() or 0
    if total == 0:
        pytest.skip("TEST no tiene clases en el mes anterior")

    realizadas = db.execute(text(
        "SELECT COUNT(*) FROM clases WHERE tenant_id = :t AND fecha BETWEEN :a AND :b AND "
        + cs.sql_clase_realizada("clases")), params).scalar() or 0
    no_canceladas = db.execute(text(
        "SELECT COUNT(*) FROM clases WHERE tenant_id = :t AND fecha BETWEEN :a AND :b "
        "AND NOT cancelada"), params).scalar() or 0
    assert realizadas == no_canceladas
    # En TEST no hay clases canceladas: el número del mes cerrado es EXACTAMENTE el de antes.
    if no_canceladas == total:
        assert realizadas == total


def test_b3_ocupacion_promedio_del_mes_en_curso_solo_cuenta_realizadas(db):
    """`metricas_service.ocupacion_promedio` aplica la definición: descarta las clases futuras."""
    from app.services import metricas_service as metricas

    hoy = ahora_santiago().date()
    ini = hoy.replace(day=1)
    params = {"t": TENANT_ID, "a": ini, "b": hoy}

    fila = db.execute(text(
        "SELECT COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0)), 0), "
        "       COALESCE(SUM(COALESCE(c.cupo_maximo, 0)), 0) "
        "FROM clases c WHERE c.tenant_id = :t AND c.fecha >= :a AND c.fecha <= :b AND "
        + cs.sql_clase_realizada("c")), params).first()
    esperado = round(int(fila[0]) / int(fila[1]) * 100, 2) if fila[1] else 0
    assert metricas.ocupacion_promedio(db, TENANT_ID, ini, hoy) == esperado


# ══════════════════════════════════════════════════════════════════════════════
# C. Cableado: los cuatro archivos de cálculo usan la MISMA función
# ══════════════════════════════════════════════════════════════════════════════
def test_c1_los_sitios_de_calculo_usan_la_definicion_unica():
    import app.api.v1.kpis_populate as kpis_populate
    import app.api.v1.reportes as reportes
    import app.services.metricas_service as metricas_service
    import app.services.reportes_service as reportes_service

    for mod in (reportes, kpis_populate, metricas_service, reportes_service):
        assert hasattr(mod, "sql_clase_realizada"), mod.__name__
    # Y el predicado se escribe en el SQL de cada archivo (no una copia a mano).
    for ruta in ("app/api/v1/reportes.py", "app/api/v1/kpis_populate.py",
                 "app/services/metricas_service.py", "app/services/reportes_service.py"):
        assert "sql_clase_realizada" in (_BACKEND / ruta).read_text(encoding="utf-8"), ruta

