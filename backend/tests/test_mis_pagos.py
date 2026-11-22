"""
"Mis pagos": el historial de compras del PROPIO alumno.

`GET /api/v1/alumnos/mis-pagos` + `services/mis_pagos.py`.

Dos bloques, sin red y sin base:

1. **Contrato HTTP** (app mínima con sólo el router del historial, `get_db`
   sustituido y el servicio monkeypatcheado): sin token ⇒ 401, un ADMIN o un
   COACH ⇒ 403 (la ruta es del alumno), y el alumno recibe SUS pagos porque
   `alumno_id` y `tenant_id` salen del token —la ruta no acepta ningún id—.
2. **Reglas del servicio** con objetos de mentira: método de pago
   (`mercadopago`/`voucher`/`efectivo`), estado del cobro, la CONDICIÓN de
   "pendiente de activar" (online + pago aprobado + plan sin activar) y el
   armado de la respuesta (`pagos` + `pendientes_activar`).

Correr (aislado, sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_mis_pagos.py -q --noconftest
"""
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import historial_alumno as api_hist          # noqa: E402
from app.core.dependencies import get_current_user           # noqa: E402
from app.db.database import get_db                            # noqa: E402
from app.services import aprobacion_planes                    # noqa: E402
from app.services import mis_pagos as svc                     # noqa: E402

RUTA = "/api/v1/alumnos/mis-pagos"

ALUMNO = {"usuario_id": 3, "tenant_id": 1, "rol": "alumno"}
ADMIN = {"usuario_id": 9, "tenant_id": 1, "rol": "administrador"}
COACH = {"usuario_id": 5, "tenant_id": 1, "rol": "coach"}


class _SesionVacia:
    """La base no se toca: el servicio está monkeypatcheado en el contrato HTTP."""


def _app(usuario):
    """App mínima del historial. `usuario=None` deja la autenticación REAL."""
    app = FastAPI()
    app.include_router(api_hist.router, prefix="/api/v1/alumnos")
    app.dependency_overrides[get_db] = lambda: _SesionVacia()
    if usuario is not None:
        app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app, raise_server_exceptions=False)


# ── Bloque 1: contrato HTTP ─────────────────────────────────────────────────
def test_sin_token_es_401():
    assert _app(None).get(RUTA).status_code == 401


@pytest.mark.parametrize("usuario", [ADMIN, COACH])
def test_solo_el_alumno_usa_esta_ruta(usuario):
    respuesta = _app(usuario).get(RUTA)

    assert respuesta.status_code == 403
    assert "del alumno" in respuesta.json()["detail"]


def test_el_alumno_recibe_sus_pagos_por_el_token(monkeypatch):
    llamadas = []

    def falso(db, *, alumno_id, tenant_id):
        llamadas.append({"alumno_id": alumno_id, "tenant_id": tenant_id})
        return {"pagos": [], "pendientes_activar": []}

    monkeypatch.setattr(svc, "historial", falso)
    respuesta = _app(ALUMNO).get(RUTA)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"pagos": [], "pendientes_activar": []}
    # Los ids salen del TOKEN (3 y 1), no de la URL ni de un query param.
    assert llamadas == [{"alumno_id": 3, "tenant_id": 1}]


def test_la_ruta_no_acepta_el_id_de_otro_alumno():
    ruta = next(r for r in api_hist.router.routes
                if getattr(r, "path", "") == "/mis-pagos")
    nombres = set(inspect.signature(ruta.endpoint).parameters)
    assert nombres == {"db", "current_user"}


# ── Bloque 2: reglas del servicio ───────────────────────────────────────────
def _solicitud(**extra):
    datos = {
        "id": 55, "tenant_id": 1, "alumno_id": 3, "plan_id": 2,
        "estado": "approved", "origen_pago": "mercadopago", "pago_id": 12,
        "voucher_url": None, "precio_clp_snapshot": 30000,
        "precio_final_clp": 27000, "matricula_clp_snapshot": None,
        "created_at": datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc),
    }
    datos.update(extra)
    return SimpleNamespace(**datos)


def _pago(**extra):
    datos = {
        "id": 12, "estado": "aprobado",
        "pagado_en": datetime(2026, 11, 21, 17, 5, tzinfo=timezone.utc),
    }
    datos.update(extra)
    return SimpleNamespace(**datos)


def _plan(**extra):
    datos = {"id": 2, "nombre": "Plan Full", "precio_clp": 30000}
    datos.update(extra)
    return SimpleNamespace(**datos)


def test_metodo_sale_de_como_se_pago():
    assert svc.metodo_de(_solicitud(origen_pago="mercadopago")) == "mercadopago"
    assert svc.metodo_de(
        _solicitud(origen_pago="manual", voucher_url="/static/v1.png")) == "voucher"
    assert svc.metodo_de(
        _solicitud(origen_pago="manual", voucher_url=None)) == "efectivo"
    # Fila vieja sin `origen_pago`: manda el comprobante.
    assert svc.metodo_de(
        _solicitud(origen_pago=None, voucher_url="/static/v1.png")) == "voucher"


@pytest.mark.parametrize("estado_pago,esperado", [
    ("aprobado", "aprobado"),
    ("pendiente", "pendiente"),
    ("en_proceso", "pendiente"),
    ("iniciado", "pendiente"),
    ("rechazado", "rechazado"),
    ("cancelado", "cancelado"),
    ("reembolsado", "reembolsado"),
    ("expirado", "expirado"),
])
def test_el_estado_del_cobro_manda(estado_pago, esperado):
    assert svc.estado_de(_solicitud(), _pago(estado=estado_pago)) == esperado


@pytest.mark.parametrize("estado_solicitud,esperado", [
    ("approved", "aprobado"),
    ("en_cola", "aprobado"),
    ("pending", "pendiente"),
    ("rejected", "rechazado"),
    ("expirada", "expirado"),
])
def test_sin_cobro_online_el_estado_sale_de_la_solicitud(estado_solicitud,
                                                         esperado):
    """Transferencia/efectivo: no hay fila en `pagos`."""
    assert svc.estado_de(
        _solicitud(origen_pago="manual", estado=estado_solicitud), None) == esperado


@pytest.mark.parametrize("estado_solicitud,estado_pago,esperado", [
    ("en_cola", "aprobado", True),     # espera que venza el plan actual
    ("expirada", "aprobado", True),    # el caso del webhook perdido
    ("expirada", "pendiente", False),  # no pagó: no es "pendiente de activar"
    ("approved", "aprobado", False),   # ya activó
    ("pending", "aprobado", False),    # todavía en la cola del admin
])
def test_pendiente_de_activar_solo_con_el_pago_aprobado(
        estado_solicitud, estado_pago, esperado):
    assert svc.es_pendiente_de_activar(
        _solicitud(estado=estado_solicitud),
        _pago(estado=estado_pago)) is esperado


def test_una_compra_manual_nunca_es_pendiente_de_activar():
    assert svc.es_pendiente_de_activar(
        _solicitud(origen_pago="manual", estado="expirada"), _pago()) is False


def test_serializar_compra_usa_el_precio_congelado_y_la_fecha_del_pago():
    compra = svc.serializar_compra(_solicitud(), _pago(), _plan())

    assert compra["solicitud_id"] == 55
    assert compra["pago_id"] == 12
    assert compra["plan"] == "Plan Full"
    assert compra["monto_clp"] == 27000          # precio_final, no el de lista
    assert compra["matricula_clp"] == 0
    assert compra["metodo"] == "mercadopago"
    assert compra["estado"] == "aprobado"
    assert compra["fecha"] == "2026-11-21T17:05:00+00:00"
    assert compra["pendiente_activar"] is False


def test_serializar_compra_sin_pago_usa_la_fecha_de_la_solicitud():
    compra = svc.serializar_compra(
        _solicitud(estado="pending", origen_pago="manual",
                   precio_final_clp=None, voucher_url="/static/v.png"),
        None, _plan())

    assert compra["fecha"] == "2026-11-20T15:00:00+00:00"
    assert compra["metodo"] == "voucher"
    assert compra["estado"] == "pendiente"
    assert compra["monto_clp"] == 30000          # cae al snapshot
    assert compra["pago_id"] is None


class _Consulta:
    def __init__(self, filas):
        self.filas = filas

    def outerjoin(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.filas)

    def first(self):
        return self.filas[0] if self.filas else None


class _SesionFalsa:
    def __init__(self, filas):
        self.filas = filas

    def query(self, *modelos):
        return _Consulta(self.filas)


def test_historial_separa_las_compras_pendientes_de_activar(monkeypatch):
    filas = [
        (_solicitud(id=55, estado="expirada"), _pago(id=12), _plan()),
        (_solicitud(id=56, estado="approved"), _pago(id=13), _plan()),
        (_solicitud(id=57, estado="pending", origen_pago="manual",
                    precio_final_clp=None), None, _plan()),
    ]
    monkeypatch.setattr(aprobacion_planes, "plan_vigente_usable",
                        lambda db, tenant_id, alumno_id: None)

    resultado = svc.historial(_SesionFalsa(filas), alumno_id=3, tenant_id=1)

    assert [c["solicitud_id"] for c in resultado["pagos"]] == [55, 56, 57]
    assert len(resultado["pendientes_activar"]) == 1
    pendiente = resultado["pendientes_activar"][0]
    assert pendiente["solicitud_id"] == 55
    assert pendiente["plan"] == "Plan Full"
    assert pendiente["monto_clp"] == 27000
    assert pendiente["estado_solicitud"] == "expirada"
    assert pendiente["tiene_plan_vigente"] is False


def test_el_pendiente_en_cola_avisa_que_tiene_plan_vigente(monkeypatch):
    filas = [(_solicitud(id=60, estado="en_cola"), _pago(id=20), _plan())]
    monkeypatch.setattr(aprobacion_planes, "plan_vigente_usable",
                        lambda db, tenant_id, alumno_id: SimpleNamespace(id=99))

    resultado = svc.historial(_SesionFalsa(filas), alumno_id=3, tenant_id=1)

    assert resultado["pendientes_activar"][0]["estado_solicitud"] == "en_cola"
    assert resultado["pendientes_activar"][0]["tiene_plan_vigente"] is True


def test_el_historial_oculta_los_checkouts_abandonados():
    """`iniciado` es una intención invisible: no es una compra."""
    fuente = (BACKEND / "app" / "services" / "mis_pagos.py").read_text(
        encoding="utf-8")

    assert 'SolicitudPlan.estado != "iniciado"' in fuente
    assert "SolicitudPlan.alumno_id == alumno_id" in fuente
    assert "SolicitudPlan.tenant_id == tenant_id" in fuente
