"""
Semana de clases: **0 = LUNES** (el bug de "DOW" de Supervisión).

Qué se prueba, SIN red y SIN base de datos:

  * `dia_semana_lunes_cero` (delega en `date.weekday()`) con fechas verificables:
    2026-04-06 (lunes) → 0 · 2026-04-10 (viernes) → 4 · 2026-04-12 (domingo) → 6;
  * `dow_pg_a_lunes_cero`: la conversión desde `EXTRACT(DOW …)` de PostgreSQL
    (0=Domingo) a nuestra convención (0=Lunes) → [6,0,1,2,3,4,5];
  * `sql_dow_lunes_cero(columna)` arma la expresión SQL con la conversión (no el DOW crudo);
  * `lunes_de` / `sabado_de_semana` / `fechas_del_rango` (sin domingos, la grilla es lun-sáb);
  * **guard de regresión**: `api/v1/supervision.py` NO expone `EXTRACT(DOW …)` crudo como
    `dia_semana` (usaba la convención de Postgres y corría la grilla un día) y sí usa
    `sql_dow_lunes_cero`.

Se corre aislado (sin `conftest.py`, que aborta si la API no está en TEST):

    cd backend && py -3.12 -m pytest tests/test_semana.py --noconftest -q
"""
from datetime import date, timedelta
from pathlib import Path

from app.utils import semana
from app.utils.semana import (
    SQL_DOW_LUNES_CERO,
    dia_semana_lunes_cero,
    dow_pg_a_lunes_cero,
    es_domingo,
    fechas_del_rango,
    lunes_de,
    nombre_dia,
    sabado_de_semana,
    sql_dow_lunes_cero,
)

# 2026-04-06 es lunes (verificado además con strftime para no depender de la afirmación).
LUNES_REF = date(2026, 4, 6)
VIERNES_REF = LUNES_REF + timedelta(days=4)   # 2026-04-10
SABADO_REF = LUNES_REF + timedelta(days=5)    # 2026-04-11
DOMINGO_REF = LUNES_REF + timedelta(days=6)   # 2026-04-12


# ── convención 0 = Lunes ───────────────────────────────────────────────────

def test_el_dia_de_referencia_es_lunes():
    assert LUNES_REF.strftime("%A") == "Monday"
    assert DOMINGO_REF.strftime("%A") == "Sunday"


def test_lunes_es_cero_y_domingo_es_seis():
    assert dia_semana_lunes_cero(LUNES_REF) == 0
    assert dia_semana_lunes_cero(VIERNES_REF) == 4
    assert dia_semana_lunes_cero(SABADO_REF) == 5
    assert dia_semana_lunes_cero(DOMINGO_REF) == 6


def test_nombres_en_orden_lunes_cero():
    assert nombre_dia(0) == "Lunes"
    assert nombre_dia(5) == "Sábado"
    assert nombre_dia(6) == "Domingo"
    assert semana.DIAS_SEMANA[0] == "Lunes"
    assert len(semana.DIAS_SEMANA) == 7


def test_es_domingo():
    assert es_domingo(DOMINGO_REF) is True
    assert es_domingo(LUNES_REF) is False
    assert es_domingo(SABADO_REF) is False


# ── conversión desde EXTRACT(DOW …) de PostgreSQL ──────────────────────────

def test_dow_de_postgres_a_lunes_cero():
    """Postgres: 0=Domingo … 6=Sábado → nosotros: 0=Lunes … 6=Domingo."""
    assert [dow_pg_a_lunes_cero(d) for d in range(7)] == [6, 0, 1, 2, 3, 4, 5]
    assert dow_pg_a_lunes_cero(1) == 0   # lunes en Postgres = 1
    assert dow_pg_a_lunes_cero(0) == 6   # domingo en Postgres = 0
    assert dow_pg_a_lunes_cero(6) == 5   # sábado en Postgres = 6


def test_la_conversion_python_coincide_con_la_formula_sql():
    """La fórmula SQL `((DOW + 6) % 7)` y `dow_pg_a_lunes_cero` son la misma."""
    for dow in range(7):
        assert dow_pg_a_lunes_cero(dow) == (dow + 6) % 7
    # El DOW de Postgres del lunes de referencia (1) cae en nuestro lunes (0).
    assert dow_pg_a_lunes_cero(1) == LUNES_REF.weekday()


# ── expresión SQL ──────────────────────────────────────────────────────────

def test_sql_dow_lunes_cero_arma_la_expresion():
    assert sql_dow_lunes_cero("c.fecha") == "((EXTRACT(DOW FROM c.fecha)::int + 6) % 7)"
    assert SQL_DOW_LUNES_CERO.format(columna="c.fecha") == \
        sql_dow_lunes_cero("c.fecha")
    # No puede ser un DOW crudo: eso es la convención de Postgres (0=Domingo).
    assert "EXTRACT(DOW FROM {columna})::int" in SQL_DOW_LUNES_CERO


# ── lunes / sábado de la semana y rango ────────────────────────────────────

def test_lunes_y_sabado_de_la_semana():
    assert lunes_de(LUNES_REF) == LUNES_REF
    assert lunes_de(VIERNES_REF) == LUNES_REF
    assert lunes_de(DOMINGO_REF) == LUNES_REF   # el domingo pertenece a esa semana
    assert sabado_de_semana(VIERNES_REF) == SABADO_REF


def test_fechas_del_rango_sin_domingos():
    fechas = fechas_del_rango(LUNES_REF, DOMINGO_REF)
    assert len(fechas) == 6                      # lun..sáb (sin el domingo)
    assert fechas[0] == LUNES_REF
    assert fechas[-1] == SABADO_REF
    assert DOMINGO_REF not in fechas
    assert all(f.weekday() != 6 for f in fechas)


def test_fechas_del_rango_de_un_solo_domingo_es_vacio():
    """La grilla es lunes-sábado: un rango de sólo domingos no tiene días."""
    assert fechas_del_rango(DOMINGO_REF, DOMINGO_REF) == []


def test_fechas_del_rango_incluye_ambos_extremos():
    fechas = fechas_del_rango(LUNES_REF, LUNES_REF)
    assert fechas == [LUNES_REF]


# ── guard: supervision.py no vuelve al DOW crudo ────────────────────────────

def _fuente_supervision() -> str:
    raiz = Path(__file__).resolve().parents[1]     # .../backend
    return (raiz / "app" / "api" / "v1" / "supervision.py").read_text(
        encoding="utf-8")


def test_supervision_usa_el_dow_lunes_cero():
    fuente = _fuente_supervision()
    assert "EXTRACT(DOW FROM c.fecha)::int AS dia_semana" not in fuente, (
        "supervision.py volvió a exponer EXTRACT(DOW …) crudo (0=Domingo): la "
        "grilla se corre un día. Usar sql_dow_lunes_cero (app/utils/semana.py).")
    assert "sql_dow_lunes_cero(" in fuente
    assert '`dia_semana` 0=Lunes..6=Domingo' in fuente


def test_supervision_expone_la_grilla_por_rango():
    """La grilla de Supervisión acepta un rango (desde/hasta), no una fecha suelta."""
    fuente = _fuente_supervision()
    assert '@router.get("/grilla")' in fuente
    assert "def supervision_grilla(" in fuente
    assert "desde: date = Query" in fuente
    assert "hasta: date = Query" in fuente
