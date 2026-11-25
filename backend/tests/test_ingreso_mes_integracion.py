"""Integración de las tarjetas que tocan DINERO: Ingreso del mes y Membresías.

No usa red ni base real: la sesión es un doble que devuelve las filas ya
"consultadas" y se ejecutan las funciones REALES del servicio (serialización de
`pagos_del_dia`, agrupación por día y ranking). Así se valida el camino
completo —fila de `pagos` → respuesta del endpoint— sin depender de que el
servidor de test esté levantado.

También fija que los tres endpoints nuevos existen bajo `/admin` y exigen el
token de ADMINISTRADOR (el `tenant_id` sale del token, nunca de un parámetro).

Correr aislado:
    cd backend && py -3.12 -m pytest tests/test_ingreso_mes_integracion.py -q --noconftest
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import admin as api_admin                 # noqa: E402
from app.core.dependencies import get_current_admin       # noqa: E402
from app.services import dashboard_admin as svc          # noqa: E402

ENERO = datetime(2020, 1, 3, 14, 0, tzinfo=timezone.utc)


class _Consulta:
    """Doble de `Query`: acepta la cadena de llamadas y devuelve las filas dadas."""

    def __init__(self, filas):
        self.filas = filas

    def outerjoin(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def select_from(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def group_by(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.filas)


class _Sesion:
    """Sesión de mentira: cada query devuelve las mismas filas preparadas."""

    def __init__(self, filas):
        self.filas = filas

    def query(self, *modelos):
        return _Consulta(self.filas)


def _pago(**extra):
    datos = {
        "id": 1, "usuario_id": 3, "concepto": "membresia",
        "referencia_id": 55, "monto_clp": 40000, "estado": "aprobado",
        "pagado_en": ENERO,
        "created_at": ENERO,
        "metodo_pago": "visa", "tipo_pago": "credit_card",
    }
    datos.update(extra)
    return SimpleNamespace(**datos)


# ── Ingreso del mes: pagos → serialización → totales y serie diaria ─────────
def _solicitud(**extra):
    datos = {"id": 55, "tenant_id": 1, "alumno_id": 3, "plan_id": 2,
             "estado": "approved"}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _alumno(**extra):
    datos = {"id": 3, "nombre": "Ana Pérez", "correo": "ana@box.cl"}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _plan(**extra):
    datos = {"id": 2, "nombre": "Plan Full", "precio_clp": 40000}
    datos.update(extra)
    return SimpleNamespace(**datos)


def test_ingreso_del_mes_integra_membresia_y_bazar(monkeypatch):
    filas = [
        (_pago(id=1, concepto="membresia", referencia_id=55, monto_clp=40000),
         _solicitud(), _alumno(), _plan()),
        (_pago(id=2, concepto="bazar", referencia_id=77, monto_clp=15000),
         None, _alumno(), None),
    ]
    monkeypatch.setattr(
        svc, "suscripciones_por_pago",
        lambda db, tenant_id, ids: {1: SimpleNamespace(id=9, pago_id=1, estado="activo")})
    monkeypatch.setattr(
        svc, "productos_por_pedido",
        lambda db, tenant_id, ids: {77: "Camiseta · Talla M"})

    resumen = svc.resumen_ingreso_mes(_Sesion(filas), 1, anio=2020, mes=1)

    # El total del mes es la suma de los cobros APROBADOS (membresía + Bazar).
    assert resumen["total_clp"] == 55000
    assert resumen["total_membresia_clp"] == 40000
    assert resumen["total_bazar_clp"] == 15000
    assert resumen["cantidad"] == 2
    # Cada día del mes viaja con su total (31 días de enero).
    assert len(resumen["dias"]) == 31
    dia = next(d for d in resumen["dias"] if d["fecha"] == "2020-01-03")
    assert dia == {"fecha": "2020-01-03", "total_clp": 55000, "cantidad": 2}
    # La fila conserva el origen: el panel distingue plan de Bazar.
    assert [p["origen"] for p in resumen["pagos"]] == ["membresia", "bazar"]
    assert resumen["pagos"][1]["producto"] == "Camiseta · Talla M"


def test_ingreso_del_mes_sin_pagos_devuelve_cero_no_un_error(monkeypatch):
    monkeypatch.setattr(svc, "suscripciones_por_pago", lambda *a, **k: {})
    monkeypatch.setattr(svc, "productos_por_pedido", lambda *a, **k: {})

    resumen = svc.resumen_ingreso_mes(_Sesion([]), 1, anio=2020, mes=1)

    assert resumen["total_clp"] == 0
    assert resumen["cantidad"] == 0
    assert len(resumen["dias"]) == 31
    assert all(d["total_clp"] == 0 for d in resumen["dias"])


# ── Membresías del mes: el plan de prueba gratis NO entra ───────────────────
def test_membresias_del_mes_excluye_el_plan_gratis():
    filas = [
        (2, "Plan Full", 40000, 2, 80000),
        (5, "Plan Test", 0, 4, 0),
    ]

    resultado = svc.ranking_planes_mes(_Sesion(filas), 1, anio=2020, mes=1)

    assert resultado["total_altas"] == 2
    assert [p["plan_nombre"] for p in resultado["planes"]] == ["Plan Full"]
    assert resultado["planes"][0]["total_clp"] == 80000
    assert resultado["planes"][0]["porcentaje"] == 100.0


# ── Contrato: rutas nuevas y guard de ADMIN ─────────────────────────────────
def test_los_tres_endpoints_existen_y_exigen_admin():
    rutas = {r.path: r for r in api_admin.router.routes}
    for path in ("/ingreso-mes", "/membresias-mes", "/mrr"):
        assert path in rutas, f"falta la ruta {path}"
        dependencias = [d.call for d in rutas[path].dependant.dependencies]
        assert get_current_admin in dependencias, (
            f"{path} debe exigir el token de administrador")

