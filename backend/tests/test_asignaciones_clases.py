"""
Marcas de la grilla de Supervisión (app/services/asignaciones_clases.py).

Qué se prueba, SIN red y SIN base de datos (B1; B2/B3/B6 agregan los tests de las
operaciones contra la BD):

  * prioridad de `marca_cobertura`: ⚠️ emergencia > 🔴 sin coach > 🟦 admin > ✅ coach;
  * `coach_id` vacío gana sobre un `origen` seteado (dato sucio: no puede haber
    "asignada por el admin" sin coach);
  * `porcentaje_cobertura` (0.0 sin clases, redondeo a 1 decimal).

    cd backend && py -3.12 -m pytest tests/test_asignaciones_clases.py --noconftest -q
"""
from app.services.asignaciones_clases import (
    MARCAS_VALIDAS,
    MARCA_ADMIN,
    MARCA_COACH,
    MARCA_EMERGENCIA,
    MARCA_SIN_COACH,
    ORIGEN_ADMIN,
    ORIGEN_COACH,
    marca_cobertura,
    porcentaje_cobertura,
)


# ── marca_cobertura ────────────────────────────────────────────────────────

def test_sin_coach():
    assert marca_cobertura(None) == MARCA_SIN_COACH
    assert marca_cobertura(0) == MARCA_SIN_COACH
    assert marca_cobertura(None, ORIGEN_COACH) == MARCA_SIN_COACH


def test_tomada_por_el_coach():
    assert marca_cobertura(7) == MARCA_COACH
    assert marca_cobertura(7, ORIGEN_COACH) == MARCA_COACH


def test_asignada_por_el_admin():
    assert marca_cobertura(7, ORIGEN_ADMIN) == MARCA_ADMIN


def test_la_emergencia_gana_siempre():
    assert marca_cobertura(7, ORIGEN_COACH, True) == MARCA_EMERGENCIA
    assert marca_cobertura(7, ORIGEN_ADMIN, True) == MARCA_EMERGENCIA
    assert marca_cobertura(None, None, True) == MARCA_EMERGENCIA


def test_origen_desconocido_cae_a_coach():
    """Un origen raro (dato viejo) no puede marcar 🟦: la marca por defecto es ✅."""
    assert marca_cobertura(7, "otro") == MARCA_COACH


def test_las_marcas_son_las_del_frontend():
    assert sorted(MARCAS_VALIDAS) == ["admin", "coach", "emergencia", "sin_coach"]


# ── porcentaje_cobertura ───────────────────────────────────────────────────

def test_porcentaje_cobertura():
    assert porcentaje_cobertura(0, 0) == 0.0
    assert porcentaje_cobertura(20, 20) == 100.0
    assert porcentaje_cobertura(20, 24) == 83.3
    assert porcentaje_cobertura(1, 3) == 33.3
    assert porcentaje_cobertura(5, 0) == 0.0
