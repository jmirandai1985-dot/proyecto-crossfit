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
from datetime import date, datetime, time, timedelta
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


def _suspension(fecha_inicio, dias, cancelada=False, fecha_fin=None):
    return SimpleNamespace(fecha_inicio=fecha_inicio, dias=dias, cancelada=cancelada,
                           fecha_fin=fecha_fin)


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


def test_dias_usados_excluye_canceladas():
    ciclo_inicio = datetime(2026, 3, 15, tzinfo=SANTIAGO)
    ciclo_fin = datetime(2027, 3, 15, tzinfo=SANTIAGO)
    suspensiones = [
        _suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 5, cancelada=False),
        _suspension(datetime(2026, 9, 1, tzinfo=SANTIAGO), 2, cancelada=True),  # cancelada: no cuenta
    ]
    assert svc.dias_usados_en_ciclo(suspensiones, ciclo_inicio, ciclo_fin) == 5


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


def test_saldo_recupera_dias_de_suspensiones_canceladas():
    # 7 días CANCELADOS no cuentan: el alumno recupera esos días del saldo (14).
    cancelada = _suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 7, cancelada=True)
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(),
                                  [cancelada], HOY)
    assert r["elegible"] is True
    assert r["saldo_disponible"] == 14


# ── puede_cancelar (cupo anual de cancelación) ───────────────────────────────
def test_puede_cancelar_sin_cancelaciones_previas():
    del_ciclo = [_suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 5, cancelada=False)]
    assert svc.puede_cancelar(del_ciclo) is True
    assert svc.puede_cancelar([]) is True


def test_puede_cancelar_con_cancelacion_previa_en_el_ciclo():
    del_ciclo = [
        _suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 5, cancelada=True),
        _suspension(datetime(2026, 8, 1, tzinfo=SANTIAGO), 3, cancelada=False),
    ]
    assert svc.puede_cancelar(del_ciclo) is False


def test_puede_cancelar_cancelacion_en_ciclo_anterior_no_cuenta():
    # La cancelación del ciclo ANTERIOR queda fuera de `suspensiones_del_ciclo`
    # (el llamador filtra por `fecha_inicio` en el ciclo vigente). Acá se simula
    # ese filtro: el ciclo vigente no tiene ninguna `cancelada=True`.
    inscripcion = datetime(2026, 3, 15, 12, 0, tzinfo=SANTIAGO)
    ciclo_inicio, ciclo_fin = svc.ciclo_vigente(inscripcion, HOY)
    todas = [
        _suspension(datetime(2025, 9, 1, tzinfo=SANTIAGO), 5, cancelada=True),   # ciclo anterior
        _suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 3, cancelada=False),  # ciclo vigente
    ]
    del_ciclo = [s for s in todas if ciclo_inicio <= s.fecha_inicio < ciclo_fin]
    assert len(del_ciclo) == 1
    assert svc.puede_cancelar(del_ciclo) is True


# ── suspensión activa hoy (fix de visibilidad: no solapar dos suspensiones) ──
def _activa(fecha_inicio_delta=-2, fecha_fin_delta=3):
    inicio = datetime.combine(HOY + timedelta(days=fecha_inicio_delta), time.min,
                              tzinfo=SANTIAGO)
    fin = datetime.combine(HOY + timedelta(days=fecha_fin_delta), time.min, tzinfo=SANTIAGO)
    return _suspension(inicio, 5, fecha_fin=fin)


def test_suspension_activa_encuentra_la_viva_y_ignora_canceladas():
    viva = _activa()
    cancelada = _activa()  # mismo rango, pero marcada cancelada
    cancelada.cancelada = True
    futura = _suspension(datetime.combine(HOY + timedelta(days=5), time.min, tzinfo=SANTIAGO),
                         5, fecha_fin=datetime.combine(HOY + timedelta(days=10), time.min, tzinfo=SANTIAGO))

    assert svc.suspension_activa([cancelada, viva], HOY) is viva
    assert svc.suspension_activa([cancelada, futura], HOY) is None


def test_calcular_elegibilidad_con_suspension_activa():
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(),
                                  [_activa()], HOY)
    assert r["elegible"] is False
    assert r["motivo"] == "Ya tienes una suspensión activa hasta 08/10/2026"


def test_calcular_elegibilidad_sin_suspension_activa_sigue_elegible():
    # Suspensión pasada (no activa hoy) no bloquea: el alumno puede pedir otra.
    pasada = _suspension(datetime.combine(HOY - timedelta(days=10), time.min, tzinfo=SANTIAGO),
                         5, fecha_fin=datetime.combine(HOY - timedelta(days=5), time.min, tzinfo=SANTIAGO))
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(),
                                  [pasada], HOY)
    assert r["elegible"] is True
    assert r["motivo"] is None


# ── Suspensión por salud (admin): no cuenta para el saldo/cupo del alumno ────
def _salud(fecha_inicio, dias, cancelada=False, fecha_fin=None):
    """Suspensión `origen='admin_salud'` (la crea el admin, no el alumno)."""
    return SimpleNamespace(fecha_inicio=fecha_inicio, dias=dias, cancelada=cancelada,
                           fecha_fin=fecha_fin, origen="admin_salud")


def test_dias_entre_inclusivo():
    # Del 01 al 03 son 3 días (inclusive), igual que el self-service.
    assert svc.dias_entre(date(2026, 10, 1), date(2026, 10, 3)) == 3
    assert svc.dias_entre(date(2026, 10, 1), date(2026, 10, 1)) == 1
    assert svc.dias_entre(date(2026, 10, 5), date(2026, 10, 8)) == 4


def test_admin_salud_no_cuenta_en_dias_usados():
    ciclo_inicio = datetime(2026, 3, 15, tzinfo=SANTIAGO)
    ciclo_fin = datetime(2027, 3, 15, tzinfo=SANTIAGO)
    suspensiones = [
        _suspension(datetime(2026, 4, 1, tzinfo=SANTIAGO), 5),   # alumno
        _salud(datetime(2026, 5, 1, tzinfo=SANTIAGO), 9),        # admin_salud
    ]
    assert svc.dias_usados_en_ciclo(suspensiones, ciclo_inicio, ciclo_fin) == 5


def test_admin_salud_no_consume_saldo_ni_periodos():
    # Una suspensión por salud de 20 días NO mueve el saldo (14) ni el tope de
    # períodos (0 usados): el alumno sigue 100% disponible.
    salud = _salud(datetime(2026, 4, 1, tzinfo=SANTIAGO), 20)
    r = svc.calcular_elegibilidad(_suscripcion(creditos=10), SimpleNamespace(),
                                  [salud], HOY)
    assert r["elegible"] is True
    assert r["saldo_disponible"] == 14
    assert r["periodos_usados"] == 0


def test_admin_salud_cancelada_no_consume_cupo_de_cancelacion():
    # Una `admin_salud` cancelada NO gasta el cupo de 1 cancelación/año del alumno.
    del_ciclo = [_salud(datetime(2026, 4, 1, tzinfo=SANTIAGO), 5, cancelada=True)]
    assert svc.puede_cancelar(del_ciclo) is True

