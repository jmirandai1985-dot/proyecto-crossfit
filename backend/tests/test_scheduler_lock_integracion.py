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
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.scheduler_lock as sl  # noqa: E402
from app.db.database import engine        # noqa: E402


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


# ══════════════════════════════════════════════════════════════════════════════
# El lock se PERDÍA a los 5 min (`idle_in_transaction_session_timeout` de Neon)
#
# Medido contra ESTA BD: la conexión del líder quedaba `idle in transaction` y el
# server la mataba a los 300 s exactos → el lock se liberaba y el proceso seguía
# creyéndose líder. Son fallos de SQL y de estado de sesión, así que con dobles no
# se ven: acá se usan conexiones de verdad (y se simula el kill del server).
# ══════════════════════════════════════════════════════════════════════════════
def _pid_de(conn):
    """PID de sesión de una conexión (y cierra su transacción)."""
    pid = conn.execute(text("SELECT pg_backend_pid()")).scalar()
    conn.commit()
    return pid


def _estado_de(pid):
    """`state` de esa sesión, mirado desde OTRA conexión (desde sí misma da 'active')."""
    with engine.connect() as otra:
        estado = otra.execute(
            text("SELECT state FROM pg_stat_activity WHERE pid = CAST(:pid AS int)"),
            {"pid": pid}).scalar()
        otra.rollback()
    return estado


def _matar_sesion(pid):
    """Simula lo que hace Neon solo a los 5 min de `idle in transaction`."""
    with engine.connect() as otra:
        otra.execute(text("SELECT pg_terminate_backend(CAST(:pid AS int))"),
                     {"pid": pid})
        otra.commit()


def test_la_conexion_del_lider_queda_idle_y_no_idle_in_transaction():
    """Es EL bug: `idle in transaction` > 5 min = el server mata la sesión y adiós lock."""
    assert sl.tomar_lock_lider() is True
    pid = _pid_de(sl._conexion_lider)

    estado = _estado_de(pid)

    assert estado == "idle", (
        f"la conexión del líder quedó en {estado!r}: con 'idle in transaction' Neon la "
        "mata a los 5 min (idle_in_transaction_session_timeout) y se lleva el lock")


def test_el_lock_del_lider_sobrevive_al_commit():
    """El commit cierra la transacción pero NO suelta el lock (es de SESIÓN)."""
    assert sl.tomar_lock_lider() is True

    with engine.connect() as otra:
        libre = otra.execute(
            text("SELECT pg_try_advisory_lock(CAST(:clave AS bigint))"),
            {"clave": sl.CLAVE_LIDER}).scalar()
        if libre:                     # no debería: se limpia antes de fallar
            otra.execute(text("SELECT pg_advisory_unlock(CAST(:clave AS bigint))"),
                         {"clave": sl.CLAVE_LIDER})
            otra.commit()

    assert libre is False, (
        "otra sesión pudo tomar el lock: el commit (o el cierre de la transacción) "
        "lo habría soltado, y el líder se quedaría sin lock al minuto de arrancar")


def test_verificar_lock_lider_detecta_que_el_server_mato_la_sesion():
    """`es_lider()` miente cuando el server mató la sesión; la verificación NO."""
    assert sl.tomar_lock_lider() is True
    assert sl.verificar_lock_lider() is True
    pid = _pid_de(sl._conexion_lider)

    _matar_sesion(pid)

    assert sl.es_lider() is True, "la variable local sigue creyendo que somos líderes"
    assert sl.verificar_lock_lider() is False, (
        "...pero Postgres dice que el lock ya no está: por eso el latido pregunta a "
        "`pg_locks` en vez de mirar la variable")


def test_el_latido_recupera_el_liderazgo_tras_perder_el_lock():
    """Una vuelta real del latido deja la instancia liderando OTRA VEZ de verdad."""
    from app.services.scheduler import scheduler, sincronizar_liderazgo

    assert sl.tomar_lock_lider() is True
    pid = _pid_de(sl._conexion_lider)
    _matar_sesion(pid)
    try:
        assert sincronizar_liderazgo() == "lider_recuperado"
        assert sl.es_lider() is True
        assert sl.verificar_lock_lider() is True, "el lock nuevo también tiene que ser real"
    finally:
        scheduler.remove_all_jobs()


def test_olvidar_lock_lider_devuelve_la_ranura_al_pool():
    """La conexión muerta se quedaba ocupando 1 de 15 ranuras para siempre."""
    antes = engine.pool.checkedout()
    assert sl.tomar_lock_lider() is True
    assert engine.pool.checkedout() == antes + 1
    pid = _pid_de(sl._conexion_lider)
    _matar_sesion(pid)
    assert sl.verificar_lock_lider() is False

    sl.olvidar_lock_lider()

    assert sl.es_lider() is False
    assert engine.pool.checkedout() == antes, (
        "la ranura de la conexión muerta no volvió al pool: se pierde 1 de 15 por "
        "instancia hasta el reinicio de la app")
