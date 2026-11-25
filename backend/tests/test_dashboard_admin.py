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
from datetime import date, datetime, time
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



# ── Planes de prueba: ni el gratis ni el de precio simbólico son membresías ──
def test_es_plan_de_prueba_por_nombre():
    assert svc.es_plan_de_prueba("Prueba") is True
    assert svc.es_plan_de_prueba("Clase de prueba") is True
    assert svc.es_plan_de_prueba("Plan Test") is True
    assert svc.es_plan_de_prueba("Trial 1 clase") is True
    assert svc.es_plan_de_prueba("Princesa") is False
    assert svc.es_plan_de_prueba("Plan Full") is False
    assert svc.es_plan_de_prueba(None) is False


def test_ranking_excluye_plan_prueba_con_precio_simbolico():
    ranking = svc.serializar_ranking([
        (2, "Plan Full", 40000, 2, 80000),
        (5, "Prueba", 1500, 9, 13500),   # clase de prueba: NO es membresía
    ])

    assert ranking["total_altas"] == 2
    assert [p["plan_nombre"] for p in ranking["planes"]] == ["Plan Full"]


def test_mrr_excluye_plan_prueba_con_precio_simbolico():
    mrr = svc.agrupar_mrr_por_plan([
        (_suscripcion(3, 10), _plan(2, "Plan Full", 40000)),
        (_suscripcion(4, 11), _plan(5, "Prueba", 1500)),
    ])

    assert mrr["alumnos"] == 1
    assert mrr["total_clp"] == 40000
    assert [p["plan_nombre"] for p in mrr["planes"]] == ["Plan Full"]


# ── Alumnos activos: una fila por alumno y misma base para el riesgo ─────────
class _ConsultaFalsa:
    def __init__(self, filas):
        self.filas = filas

    def join(self, *args, **kwargs):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.filas)


class _SesionFalsa:
    def __init__(self, filas):
        self.filas = filas

    def query(self, *modelos):
        return _ConsultaFalsa(self.filas)


def _alumno(usuario_id, nombre, creado="2026-11-01"):
    return SimpleNamespace(
        id=usuario_id, nombre=nombre, correo=f"{usuario_id}@box.cl",
        created_at=datetime.fromisoformat(creado),
    )


def _suscripcion_activa(usuario_id, suscripcion_id=1):
    return SimpleNamespace(
        id=suscripcion_id, usuario_id=usuario_id, creditos_disponibles=3,
        fecha_expiracion=datetime(2026, 12, 1, 23, 59, 59, tzinfo=SANTIAGO),
    )


def test_listar_alumnos_activos_cuenta_una_vez_por_alumno():
    filas = [
        (_suscripcion_activa(3, 10), _alumno(3, "Ana"), _plan(2, "Plan Full", 40000)),
        # Misma alumna con otra suscripción vigente: no se cuenta dos veces.
        (_suscripcion_activa(3, 11), _alumno(3, "Ana"), _plan(6, "Plan Básico", 25000)),
        (_suscripcion_activa(4, 12), _alumno(4, "Beto"), _plan(2, "Plan Full", 40000)),
    ]

    resultado = svc.listar_alumnos_activos(_SesionFalsa(filas), 1, limite=10)

    assert resultado["total"] == 2
    assert {a["nombre"] for a in resultado["alumnos"]} == {"Ana", "Beto"}


def test_la_base_de_activos_es_la_misma_que_usa_el_riesgo():
    fuente = (BACKEND / "app" / "services" / "dashboard_admin.py").read_text(
        encoding="utf-8")

    assert "def ids_alumnos_activos" in fuente
    assert 'Usuario.rol == "alumno"' in fuente
    assert "Usuario.es_prueba.is_(False)" in fuente
    assert 'Suscripcion.estado == "activo"' in fuente
    assert "vigente_hoy(Suscripcion.fecha_expiracion" in fuente


# ── Ocupación por clase: misma fórmula que la tarjeta ───────────────────────
class _ResultadoFalso:
    def __init__(self, filas=None, scalar=None):
        self._filas = filas or []
        self._scalar = scalar

    def fetchall(self):
        return self._filas

    def scalar(self):
        return self._scalar


class _SesionOcupacion:
    def __init__(self, filas, sin_cupo):
        self.filas = filas
        self.sin_cupo = sin_cupo
        self.llamadas = 0

    def execute(self, *args, **kwargs):
        self.llamadas += 1
        if self.llamadas == 1:
            return _ResultadoFalso(filas=self.filas)
        return _ResultadoFalso(scalar=self.sin_cupo)


def test_ocupacion_por_clase_suma_asistentes_y_cupos():
    filas = [
        SimpleNamespace(id=1, fecha=date(2026, 11, 2), hora_inicio=time(18, 0),
                        disciplina="CrossFit", coach="Ana", cupo_maximo=10,
                        asistentes=4),
        SimpleNamespace(id=2, fecha=date(2026, 11, 3), hora_inicio=time(19, 0),
                        disciplina="CrossFit", coach="Ana", cupo_maximo=10,
                        asistentes=1),
    ]

    resultado = svc.ocupacion_mes_por_clase(
        _SesionOcupacion(filas, sin_cupo=7), 1, anio=2026, mes=11)

    assert resultado["asistentes"] == 5
    assert resultado["cupo"] == 20
    assert resultado["total_pct"] == 25.0
    assert resultado["clases_sin_cupo"] == 7
    assert [c["pct"] for c in resultado["clases"]] == [40.0, 10.0]
    assert resultado["clases"][0]["hora_inicio"] == "18:00"

