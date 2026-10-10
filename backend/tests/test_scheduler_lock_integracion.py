"""Integración REAL de los advisory locks contra la BD de TEST.

Por qué existe
--------------
El bug del `::bigint` (ver tests/test_scheduler_lock_sql.py) hacía que
`tomar_lock_lider()` devolviera False SIEMPRE y que `lock_de_job` no bloqueara nada,
y ningún test con dobles lo veía porque el doble reemplaza justo la conexión. Acá se
usa la conexión de verdad: si el SQL vuelve a romperse, el leader lock no se toma y
esto falla enseguida.

Se corre contra TEST:

    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_scheduler_lock_integracion.py -q --noconftest
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.scheduler_lock as sl  # noqa: E402


@pytest.fixture(autouse=True)
def solo_en_test():
    """Estos tests ESCRIBEN locks en la BD: nunca contra producción."""
    from app.core.config import is_test_db_url, settings

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es TEST: aborto (exporta ENVIRONMENT=test)")


@pytest.fixture(autouse=True)
def liberar_al_salir():
    yield
    sl.soltar_lock_lider()


def test_esta_instancia_puede_llegar_a_ser_lider():
    """Antes del fix esto devolvía False siempre (y el scheduler quedaba en standby)."""
    assert sl.tomar_lock_lider() is True
    assert sl.es_lider() is True
    # Idempotente: pedirlo de nuevo sigue dando True sin abrir otra conexión.
    assert sl.tomar_lock_lider() is True


def test_el_lock_de_job_bloquea_el_segundo_intento_el_mismo_dia():
    """El cerrojo (job, día) tiene que bloquear DE VERDAD (era el fail-open silencioso)."""
    with sl.lock_de_job("generar_clases_diarias") as primera:
        assert primera is True
        with sl.lock_de_job("generar_clases_diarias") as segunda:
            assert segunda is False, (
                "el segundo intento del mismo (job, día) entró igual: el lock no "
                "está bloqueando (revisá el CAST del SQL)")
    # Al salir del `with` se libera: otra vez se puede tomar.
    with sl.lock_de_job("generar_clases_diarias") as tercera:
        assert tercera is True
