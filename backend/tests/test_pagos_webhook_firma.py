"""Pagos online: fail-closed de la configuración y firma del webhook (HTTP).

Tests con `TestClient` sobre un app MÍNIMO (sólo el router de pagos), sin
servidor levantado y sin base de datos real:

* con `MERCADOPAGO_HABILITADO=false` (el default) los POST responden **503** y
  NO tocan la base: el servicio corta antes de crear la solicitud o el pedido;
* habilitado pero sin access token ⇒ 503 también (fail-fast, no 500);
* el webhook **sin secreto configurado** responde 503 y no procesa nada
  (fail-closed: nunca "aceptar porque no hay secreto");
* firma inválida ⇒ 401; firma válida ⇒ se procesa;
* el mismo `id` de notificación dos veces ⇒ `duplicado` (no se aplica dos veces);
* `merchant_order` (o cualquier tipo que no sea `payment`) se registra y se
  corta con 200: no dice si se cobró.

Las dependencias de auth y de BD se reemplazan: acá se prueba el contrato HTTP,
no el negocio (eso lo cubre la integración contra TEST).
"""
import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import pagos as api_pagos                       # noqa: E402
from app.core.config import settings                            # noqa: E402
from app.core.dependencies import require_full_access           # noqa: E402
from app.core.rate_limit import limiter                          # noqa: E402
from app.db.database import get_db                               # noqa: E402

SECRETO = "secreto-de-prueba"


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _SesionFalsa:
    """Sesión mínima: registra lo que se agrega y puede simular un duplicado."""

    def __init__(self, duplicar=False):
        self.duplicar = duplicar
        self.agregados = []
        self.commits = 0

    def begin_nested(self):
        return _Nested()

    def add(self, obj):
        self.agregados.append(obj)

    def flush(self):
        if self.duplicar:
            raise IntegrityError("duplicado", None, Exception("dup"))

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _app(sesion):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_pagos.router, prefix="/api/v1/pagos")
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[require_full_access] = lambda: {
        "usuario_id": 5, "tenant_id": 1, "rol": "alumno"}
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def apagado(monkeypatch):
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", False, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "APP_USR-x",
                        raising=False)


def _firmar(data_id: str, request_id: str, ts: int, secreto: str = SECRETO):
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    firma = hmac.new(secreto.encode(), manifest.encode(),
                     hashlib.sha256).hexdigest()
    return f"ts={ts},v1={firma}"


# ── Configuración fail-fast (503, sin tocar la base) ────────────────────────
def test_membresia_con_pasarela_apagada_es_503_y_no_toca_la_base(apagado):
    sesion = _SesionFalsa()
    cliente = _app(sesion)
    respuesta = cliente.post("/api/v1/pagos/membresia", json={"plan_id": 1})
    assert respuesta.status_code == 503
    assert "transferencia" in respuesta.json()["detail"]
    assert sesion.agregados == [] and sesion.commits == 0


def test_bazar_con_pasarela_apagada_es_503_y_no_reserva_stock(apagado):
    sesion = _SesionFalsa()
    cliente = _app(sesion)
    respuesta = cliente.post("/api/v1/pagos/bazar",
                             json={"producto_id": 1, "cantidad": 1})
    assert respuesta.status_code == 503
    assert sesion.agregados == [] and sesion.commits == 0


def test_habilitado_sin_access_token_tambien_es_503(monkeypatch):
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", True, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "", raising=False)
    sesion = _SesionFalsa()
    respuesta = _app(sesion).post("/api/v1/pagos/membresia",
                                  json={"plan_id": 1})
    assert respuesta.status_code == 503
    assert sesion.agregados == []


def test_disponibilidad_refleja_el_interruptor(apagado):
    respuesta = _app(_SesionFalsa()).get("/api/v1/pagos/disponibilidad")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"habilitado": False}



# ── Webhook ────────────────────────────────────────────────────────────────
def _webhook(cliente, *, cuerpo, data_id="123456789", request_id="req-1",
             firma=None, tipo="payment"):
    headers = {"x-request-id": request_id}
    if firma is not None:
        headers["x-signature"] = firma
    return cliente.post(
        f"/api/v1/pagos/webhook/mercadopago?data.id={data_id}&type={tipo}",
        json=cuerpo, headers=headers)


def test_webhook_sin_secreto_es_503_y_no_procesa(monkeypatch, apagado):
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "", raising=False)
    sesion = _SesionFalsa()
    respuesta = _webhook(_app(sesion), cuerpo={"id": "notif-1",
                                               "type": "payment",
                                               "data": {"id": "123456789"}})
    assert respuesta.status_code == 503
    assert sesion.agregados == []


def test_webhook_con_firma_invalida_es_401(monkeypatch, apagado):
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", SECRETO,
                        raising=False)
    respuesta = _webhook(
        _app(_SesionFalsa()),
        cuerpo={"type": "payment", "data": {"id": "123456789"}},
        firma=_firmar("123456789", "req-1", int(time.time()), "otro-secreto"))
    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "Firma inválida"


def test_webhook_sin_firma_es_401(monkeypatch, apagado):
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", SECRETO,
                        raising=False)
    respuesta = _webhook(_app(_SesionFalsa()),
                         cuerpo={"type": "payment", "data": {"id": "1"}})
    assert respuesta.status_code == 401


def test_webhook_reintento_del_mismo_aviso_es_duplicado(monkeypatch, apagado):
    """El UNIQUE de `notificacion_id` frena el reintento exacto de MP."""
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", SECRETO,
                        raising=False)
    sesion = _SesionFalsa(duplicar=True)
    respuesta = _webhook(
        _app(sesion),
        cuerpo={"id": "notif-dup", "type": "payment",
                "data": {"id": "123456789"}},
        firma=_firmar("123456789", "req-1", int(time.time())))
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "duplicado"}


def test_webhook_merchant_order_se_registra_y_se_corta(monkeypatch, apagado):
    """`merchant_order` no dice si se cobró: se deja la traza y no se aplica."""
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", SECRETO,
                        raising=False)
    sesion = _SesionFalsa()
    respuesta = _webhook(
        _app(sesion),
        cuerpo={"id": "notif-mo", "type": "merchant_order",
                "data": {"id": "555"}},
        data_id="555", tipo="merchant_order",
        firma=_firmar("555", "req-1", int(time.time())))
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "desconocido"}
    assert any(getattr(e, "resultado", None) == "desconocido"
               for e in sesion.agregados)


def test_webhook_sin_ids_se_ignora(monkeypatch, apagado):
    """Sin `id` de notificación no hay clave de idempotencia: no se procesa."""
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", SECRETO,
                        raising=False)
    sesion = _SesionFalsa()
    respuesta = _webhook(
        _app(sesion), cuerpo={"type": "payment"},
        firma=_firmar("123456789", "req-1", int(time.time())))
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ignorado"}
    assert sesion.agregados == []
