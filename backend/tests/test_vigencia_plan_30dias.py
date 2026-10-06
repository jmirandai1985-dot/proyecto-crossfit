"""Vigencia de un plan: `inicio + duracion_dias` dias SEGUIDOS, en hora de Chile.

Que fija este archivo
---------------------
Regla 2026-10-06: un plan dura `duracion_dias` dias contados desde su dia de contratacion
(`inicio`), en dias CALENDARIO de Chile, y vale hasta las 23:59:59 de ese ultimo dia. Antes
los caminos de escritura divergian: la aprobacion de una solicitud, la compra de emergencia y
`fix_fechas` forzaban el FIN DE MES, mientras el seeder demo usaba `inicio + duracion`.

Ahora UNA sola funcion (`app.utils.santiago.fin_de_plan_chile`) define el vencimiento en los
CUATRO caminos: `solicitudes_planes.aprobar_solicitud`, `comprar_emergencia`, `fix_fechas` y
`POST /suscripciones` (cuando no viene la fecha). El plan de Prueba cae solo: su
`duracion_dias` es 7.

  A. PURAS (sin BD): la aritmetica de `fin_de_plan_chile` (30 dias, el fin del dia chileno,
     DST, cruce de mes/anio y el piso de 1 dia).
  B. ESTRUCTURA (sin BD): los cuatro caminos usan LA MISMA funcion y ninguno volvio al fin de
     mes — si uno diverge, este test FALLA.
  C. INTEGRACION (HTTP, contra TEST): ESCRIBE dinero, asi que va `@pytest.mark.skip` (escrita
     y NO ejecutada en esta fase). Se corre a mano cuando se valide sobre TEST.

Correr (aislado, sin la API):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_vigencia_plan_30dias.py -q --noconftest
"""
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.utils.santiago import (                                    # noqa: E402
    SANTIAGO, fecha_chile, fin_de_plan_chile, fin_del_dia_chile,
)


# ==============================================================================
# A. Puras (sin BD)
# ==============================================================================
def test_a1_treinta_dias_desde_la_contratacion():
    """Contratado el 03/10/2026 con un plan de 30 dias -> vence el 02/11/2026."""
    vence = fin_de_plan_chile(date(2026, 10, 3), 30)
    assert fecha_chile(vence) == date(2026, 11, 2)
    assert vence.tzinfo is not None


def test_a2_el_vencimiento_es_el_fin_del_dia_chile():
    """El ultimo dia vale COMPLETO: 23:59:59 hora de Chile (mismo criterio que `vigente_el_dia`)."""
    vence = fin_de_plan_chile(date(2026, 10, 3), 30)
    assert vence == fin_del_dia_chile(date(2026, 11, 2))
    assert (vence.hour, vence.minute, vence.second) == (23, 59, 59)


def test_a3_acepta_datetime_y_usa_su_dia_de_chile():
    """23:30 del 03/10 en Chile (ya es 04/10 en UTC) sigue contando como contratacion del 03/10."""
    dt = datetime(2026, 10, 3, 23, 30, tzinfo=SANTIAGO)
    assert fin_de_plan_chile(dt, 30) == fin_de_plan_chile(date(2026, 10, 3), 30)


def test_a4_duracion_minima_es_un_dia():
    """`duracion_dias` <= 0 no puede dar un plan de 0 dias: piso 1."""
    assert fin_de_plan_chile(date(2026, 10, 3), 0) == fin_del_dia_chile(date(2026, 10, 4))
    assert fin_de_plan_chile(date(2026, 10, 3), -5) == fin_del_dia_chile(date(2026, 10, 4))


def test_a5_cruza_fin_de_mes_y_de_anio():
    assert fecha_chile(fin_de_plan_chile(date(2026, 12, 20), 30)) == date(2027, 1, 19)


def test_a6_el_plan_de_prueba_cae_solo_en_7_dias():
    """El plan de Prueba tiene `duracion_dias = 7`: no hace falta un caso especial."""
    assert fecha_chile(fin_de_plan_chile(date(2026, 10, 3), 7)) == date(2026, 10, 10)


def test_a7_dst_de_chile_no_altera_el_dia():
    """El cambio de hora de Chile (septiembre) no corre el dia del vencimiento."""
    # 01/09/2026 + 30 dias = 01/10/2026 (en horario de verano, UTC-3).
    assert fecha_chile(fin_de_plan_chile(date(2026, 9, 1), 30)) == date(2026, 10, 1)



# ==============================================================================
# B. Estructura (sin BD): una sola definicion, sin caminos que diverjan
# ==============================================================================
def test_b1_los_cuatro_caminos_usan_la_misma_funcion():
    """El vencimiento se calcula con `santiago.fin_de_plan_chile` en los CUATRO caminos.

    Si alguien reintroduce el fin de mes (o su propia aritmetica) en uno solo, este test
    FALLA: dos caminos con fechas distintas es el bug sobre dinero que este cambio cierra.
    """
    import app.utils.santiago as santiago
    import app.api.v1.solicitudes_planes as sp
    import app.api.v1.comprar_emergencia as ce
    import app.api.v1.fix_fechas as ff
    import app.api.v1.suscripciones as su

    assert sp.fin_de_plan_chile is santiago.fin_de_plan_chile
    assert ce.fin_de_plan_chile is santiago.fin_de_plan_chile
    assert ff.fin_de_plan_chile is santiago.fin_de_plan_chile
    assert su.fin_de_plan_chile is santiago.fin_de_plan_chile


def test_b2_ningun_camino_volvio_al_fin_de_mes():
    """Ninguno de los caminos de escritura importa ya `fin_de_mes_chile`."""
    import app.api.v1.solicitudes_planes as sp
    import app.api.v1.comprar_emergencia as ce
    import app.api.v1.fix_fechas as ff
    import app.api.v1.suscripciones as su

    for mod in (sp, ce, ff, su):
        assert not hasattr(mod, "fin_de_mes_chile"), mod.__name__


# ==============================================================================
# C. Integracion (HTTP, contra TEST) — ESCRIBE dinero: escrita y NO ejecutada
# ==============================================================================
@pytest.mark.skip(reason="toca dinero (vigencia): integracion escrita, NO ejecutada en esta "
                         "fase. Correr a mano sobre TEST cuando se valide.")
def test_c1_suscripciones_sin_fecha_calcula_inicio_mas_duracion():
    """POST /suscripciones sin `fecha_expiracion` -> `inicio + plan.duracion_dias` (dia de Chile).

    Completar con ids reales de TEST (plan/alumno) y el header de admin (ver
    `tests/conftest.py::get_admin_token`) antes de correr. Debe fallar si el endpoint vuelve a
    exigir la fecha o si calcula el fin de mes.
    """
    raise AssertionError("Test de integracion: completar con ids reales de TEST y correr a mano.")


@pytest.mark.skip(reason="toca dinero (vigencia): integracion escrita, NO ejecutada en esta "
                         "fase. Correr a mano sobre TEST cuando se valide.")
def test_c2_aprobar_y_crear_dan_el_mismo_vencimiento_para_el_mismo_inicio():
    """Para el MISMO (inicio, plan), `aprobar_solicitud` y `POST /suscripciones` dan la MISMA
    `fecha_expiracion`. Escrita y NO ejecutada (crea una suscripcion real).
    """
    raise AssertionError("Test de integracion: completar con ids reales de TEST y correr a mano.")
