"""Suspensión de plan: reglas PURAS del servicio (sin BD).

Fija lo que, si se afloja, rompe la feature en silencio:
  * el ciclo vigente es el ANIVERSARIO de inscripción (365 días), no el año calendario;
  * el saldo de 14 días se resetea en esa fecha (no el 01/01);
  * la elegibilidad: >= 4 créditos (plan limitado) y >= 10 días hasta el vencimiento;
  * el plan ilimitado (`creditos_disponibles = None`) NO pasa por la regla de créditos.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suspensiones_service.py -q
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import suspensiones_service as svc          # noqa: E402
from app.utils.santiago import SANTIAGO, fin_del_dia_chile    # noqa: E402

HOY = date(2026, 10, 5)


def _suscripcion(creditos=None, expiracion=None):
    expiracion = expiracion or fin_del_dia_chile(HOY + timedelta(days=30))
    return SimpleNamespace(creditos_disponibles=creditos, fecha_expiracion=expiracion)


def _suspension(fecha_inicio, dias):
    return SimpleNamespace(fecha_inicio=fecha_inicio, dias=dias)


# ── ciclo_vigente ────────────────────────────────────────────────────────────
def test_ciclo_vigente_aniversario_de_este_anio():
    inscripcion = datetime(2026, 3, 15, 12, 0, tzinfo=SANTIAGO)
    inicio, fin = svc.ciclo_vigente(inscripcion, datetime(2026, 10, 5, 12, 0, tzinfo=SANTIAGO))
    assert inicio == datetime(2026, 3, 15, 0, 0, tzinfo=SANTIAGO)
    assert fin - inicio == timedelta(days=365)


def test_ciclo_vigente_ya_paso_el_aniversario():
    inscripcion = datetime(2026, 3, 15, 12, 0, tzinfo=SANTIAGO)
    # 2027-04-01: el aniversario 2027-03-15 ya pasó -> el ciclo vigente arrancó este año.
    inicio, fin = svc.ciclo_vigente(inscripcion, datetime(2027, 4, 1, 12, 0, tzinfo=SANTIAGO))
    assert inicio == datetime(2027, 3, 15, 0, 0, tzinfo=SANTIAGO)
    assert fin - inicio == timedelta(days=365)


def test_ciclo_vigente_antes_del_aniversario_de_este_anio():
    inscripcion = datetime(2026, 12, 1, 12, 0, tzinfo=SANTIAGO)
    # 2027-01-10: todavía no llega el aniversario 2027-12-01 -> ciclo del año anterior.
    inicio, _ = svc.ciclo_vigente(inscripcion, datetime(2027, 1, 10, 12, 0, tzinfo=SANTIAGO))
    assert inicio == datetime(2026, 12, 1, 0, 0, tzinfo=SANTIAGO)


# ── dias_usados_en_ciclo ─────────────────────────────────────────────────────
def test_dias_usados_vacio_es_cero():
    ciclo = svc.ciclo_vigente(datetime(2026, 3, 15, tzinfo=SANTIAGO),
                              datetime(2026, 10, 5, tzinfo=SANTIAGO))
    assert svc.dias_usados_en_ciclo([], *ciclo) == 0


def test_dias_usados_suma_solo_las_del_ciclo():
    ciclo_inicio = datetime(2026, 3, 15, tzinfo=SANTIAGO)
    ciclo_fin = datetime(2027, 3, 15, tzinfo=SANTIAGO)
    suspensiones = [
        _suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 5),   # dentro
        _suspension(datetime(2026, 9, 1, tzinfo=SANTIAGO), 2),   # dentro
        _suspension(datetime(2025, 9, 1, tzinfo=SANTIAGO), 7),   # ciclo anterior
        _suspension(datetime(2027, 4, 1, tzinfo=SANTIAGO), 3),   # ciclo siguiente
    ]
    assert svc.dias_usados_en_ciclo(suspensiones, ciclo_inicio, ciclo_fin) == 7


# ── calcular_elegibilidad ────────────────────────────────────────────────────
def test_alumno_nuevo_sin_suspensiones_es_elegible():
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(), [], HOY)
    assert r["elegible"] is True
    assert r["motivo"] is None
    assert r["saldo_disponible"] == 14


def test_justo_en_el_limite_de_4_creditos():
    r = svc.calcular_elegibilidad(_suscripcion(creditos=4), SimpleNamespace(), [], HOY)
    assert r["elegible"] is True

    r = svc.calcular_elegibilidad(_suscripcion(creditos=3), SimpleNamespace(), [], HOY)
    assert r["elegible"] is False
    assert r["motivo"] == svc.MOTIVO_CREDITOS.format(n=3)


def test_justo_en_el_limite_de_10_dias():
    exp_10 = fin_del_dia_chile(HOY + timedelta(days=10))
    exp_9 = fin_del_dia_chile(HOY + timedelta(days=9))
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10, expiracion=exp_10),
                                  SimpleNamespace(), [], HOY)
    assert r["elegible"] is True
    assert r["dias_para_vencimiento"] == 10

    r = svc.calcular_elegibilidad(_suscripcion(creditos=10, expiracion=exp_9),
                                  SimpleNamespace(), [], HOY)
    assert r["elegible"] is False
    assert r["motivo"] == svc.MOTIVO_VENCIMIENTO.format(n=9)


def test_plan_ilimitado_ignora_la_regla_de_creditos():
    # creditos_disponibles = None => ilimitado: no aplica el mínimo de 4 créditos.
    r = svc.calcular_elegibilidad(_suscripcion(creditos=None), SimpleNamespace(), [], HOY)
    assert r["elegible"] is True


def test_saldo_agotado_no_es_elegible():
    suspensiones = [_suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 14)]
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(),
                                  suspensiones, HOY)
    assert r["elegible"] is False
    assert r["motivo"] == svc.MOTIVO_SALDO
    assert r["saldo_disponible"] == 0


def test_dos_periodos_usados_no_es_elegible():
    suspensiones = [
        _suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 2),
        _suspension(datetime(2026, 5, 1, tzinfo=SANTIAGO), 2),
    ]
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(),
                                  suspensiones, HOY)
    assert r["elegible"] is False
    assert r["motivo"] == svc.MOTIVO_PERIODOS
    assert r["periodos_usados"] == 2


def test_saldo_disponible_descuenta_los_dias_usados():
    suspensiones = [_suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 7)]
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(),
                                  suspensiones, HOY)
    assert r["elegible"] is True
    assert r["saldo_disponible"] == 7

