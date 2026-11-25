"""Reglas del resumen mensual del Dashboard admin (sin red y sin base).

Cubre las funciones PURAS de `services/dashboard_admin.py`:

* el rango del mes en America/Santiago y los días que se muestran;
* la serie diaria de Ingreso del mes (todos los días, 0 incluido);
* el ranking que EXCLUYE el plan de prueba gratis (`precio_clp = 0`);
* el MRR que cuenta UN plan por alumno (el que vence más tarde) y descarta
  precios 0.

Y fija, sobre el código, que la fuente es `pagos` aprobados (no
`transacciones_financieras`) y que el MRR usa la misma regla de vigencia y
créditos que `aprobacion_planes._plan_vigente_usable`.

Correr aislado (sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_dashboard_admin.py -q --noconftest
"""
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import dashboard_admin as svc          # noqa: E402
from app.utils.santiago import SANTIAGO                  # noqa: E402


# ── Rango y días del mes ───────────────────────────────────────────────────
def test_rango_del_mes_usa_los_bordes_de_chile():
    primer, ultimo, inicio, fin = svc.rango_del_mes(2026, 11)

    assert primer == date(2026, 11, 1)
    assert ultimo == date(2026, 11, 30)
    assert inicio == datetime(2026, 11, 1, 0, 0, 0, tzinfo=SANTIAGO)
    assert fin == datetime(2026, 11, 30, 23, 59, 59, tzinfo=SANTIAGO)


def test_rango_del_mes_febrero_bisiesto():
    _, ultimo, _, _ = svc.rango_del_mes(2024, 2)
    assert ultimo == date(2024, 2, 29)


def test_dias_del_mes_en_curso_corta_en_hoy():
    dias = svc.dias_del_mes(
        date(2026, 11, 1), date(2026, 11, 30), hoy=date(2026, 11, 25))

    assert len(dias) == 25
    assert dias[0] == date(2026, 11, 1)
    assert dias[-1] == date(2026, 11, 25)


def test_dias_del_mes_cerrado_va_completo():
    dias = svc.dias_del_mes(
        date(2026, 10, 1), date(2026, 10, 31), hoy=date(2026, 11, 25))

    assert len(dias) == 31


# ── Serie diaria ───────────────────────────────────────────────────────────
def test_agrupar_por_dia_suma_y_conserva_los_dias_en_cero():
    dias = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]
    cobros = [
        {"fecha": date(2026, 10, 1), "monto_clp": 40000},
        {"fecha": date(2026, 10, 1), "monto_clp": 15000},
        {"fecha": date(2026, 10, 3), "monto_clp": 25000},
    ]

    filas = svc.agrupar_por_dia(cobros, dias)

    assert [f["fecha"] for f in filas] == [
        "2026-10-01", "2026-10-02", "2026-10-03"]
    assert [f["total_clp"] for f in filas] == [55000, 0, 25000]
    assert [f["cantidad"] for f in filas] == [2, 0, 1]


def test_agrupar_por_dia_ignora_dias_fuera_del_rango():
    filas = svc.agrupar_por_dia(
        [{"fecha": date(2026, 9, 30), "monto_clp": 99999}],
        [date(2026, 10, 1)],
    )

    assert filas == [{"fecha": "2026-10-01", "total_clp": 0, "cantidad": 0}]


def test_resumir_ingreso_mes_separa_membresia_y_bazar_sin_cambiar_el_total():
    cobros = [
        {"fecha": date(2026, 10, 1), "monto_clp": 40000, "concepto": "membresia"},
        {"fecha": date(2026, 10, 1), "monto_clp": 15000, "concepto": "bazar"},
    ]
    pagos = [{"pago_id": 1}, {"pago_id": 2}]

    resumen = svc.resumir_ingreso_mes(
        cobros, pagos, [date(2026, 10, 1)])

    assert resumen["total_clp"] == 55000
    assert resumen["total_membresia_clp"] == 40000
    assert resumen["total_bazar_clp"] == 15000
    assert resumen["cantidad"] == 2
    assert resumen["total_clp"] == (resumen["total_membresia_clp"]
                                    + resumen["total_bazar_clp"])


# ── Ranking de planes ──────────────────────────────────────────────────────
def test_ranking_excluye_el_plan_de_prueba_gratis():
    filas = [
        (2, "Plan Full", 40000, 3, 120000),
        (5, "Plan Test", 0, 10, 0),
        (6, "Plan Básico", 25000, 1, 25000),
    ]

    ranking = svc.serializar_ranking(filas)

    assert [p["plan_nombre"] for p in ranking["planes"]] == ["Plan Full", "Plan Básico"]
    assert ranking["total_altas"] == 4          # 3 + 1: la prueba NO suma
    assert ranking["planes"][0]["porcentaje"] == 75.0
    assert ranking["planes"][1]["porcentaje"] == 25.0


def test_ranking_vacio_no_inventa_porcentajes():
    assert svc.serializar_ranking([(5, "Plan Test", 0, 4, 0)]) == {
        "total_altas": 0, "planes": []}


# ── MRR ────────────────────────────────────────────────────────────────────
def _suscripcion(usuario_id, suscripcion_id=1):
    return SimpleNamespace(id=suscripcion_id, usuario_id=usuario_id)


def _plan(plan_id, nombre, precio):
    return SimpleNamespace(id=plan_id, nombre=nombre, precio_clp=precio)


def test_mrr_cuenta_un_plan_por_alumno_y_suma_por_plan():
    filas = [
        # El alumno 3 tiene dos planes activos: manda el primero (vence más
        # tarde) y el segundo NO se suma otra vez.
        (_suscripcion(3, 10), _plan(2, "Plan Full", 40000)),
        (_suscripcion(3, 11), _plan(6, "Plan Básico", 25000)),
        (_suscripcion(4, 12), _plan(2, "Plan Full", 40000)),
    ]

    mrr = svc.agrupar_mrr_por_plan(filas)

    assert mrr["alumnos"] == 2
    assert mrr["total_clp"] == 80000
    assert mrr["planes"] == [{
        "plan_id": 2, "plan_nombre": "Plan Full", "precio_clp": 40000,
        "alumnos": 2, "total_clp": 80000,
    }]


def test_mrr_no_cuenta_planes_gratis():
    mrr = svc.agrupar_mrr_por_plan([
        (_suscripcion(3, 10), _plan(5, "Plan Test", 0)),
    ])

    assert mrr == {"alumnos": 0, "total_clp": 0, "planes": []}


# ── La fuente, en el código ────────────────────────────────────────────────
def test_la_fuente_es_pagos_aprobados_y_no_la_caja():
    fuente = (BACKEND / "app" / "services" / "dashboard_admin.py").read_text(
        encoding="utf-8")

    assert "func.coalesce(Pago.pagado_en, Pago.created_at)" in fuente, (
        "el día de un cobro se decide por pagado_en (o created_at si no vino)")
    assert "Pago.estado == ESTADO_APROBADO" in fuente
    assert "Pago.concepto.in_(CONCEPTOS_DEL_DIA)" in fuente, (
        "Ingreso del mes incluye membresías Y Bazar")
    assert "Pago.concepto == CONCEPTO_MEMBRESIA" in fuente
    assert "plan_precio > 0" in fuente, (
        "el plan de prueba gratis no entra en el ranking")
    assert "Plan.precio_clp > 0" in fuente, (
        "el plan de prueba gratis no entra en el MRR")
    assert "plan_suscripcion" in fuente, (
        "el ranking también resuelve los cobros recurrentes (referencia=suscripción)")


def test_mrr_usa_la_misma_regla_que_plan_vigente_usable():
    fuente = (BACKEND / "app" / "services" / "dashboard_admin.py").read_text(
        encoding="utf-8")

    assert 'Suscripcion.estado == "activo"' in fuente
    assert "vigente_hoy(Suscripcion.fecha_expiracion" in fuente
    assert "Suscripcion.creditos_disponibles.is_(None)" in fuente
    assert "Suscripcion.creditos_disponibles > 0" in fuente

