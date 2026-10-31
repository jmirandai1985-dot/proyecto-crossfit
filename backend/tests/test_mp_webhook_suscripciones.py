"""Webhook de MP para Planes y suscripciones: `POST /api/v1/mp/webhook`.

Tests con `TestClient` sobre un app MÍNIMO (sólo este router), sin red y sin BD:

* la simulación del panel de MP (`type=subscription_preapproval`,
  `data.id=123456`) responde **200** aunque MP devuelva 404 porque ese id no
  existe — es el caso exacto que rompía la simulación;
* un 401 de MP (token sin permiso), un timeout o un 5xx también son 200;
* topics que no son de suscripciones (`payment`, `merchant_order`, ...) se
  ignoran con 200 y NO llaman a MP;
* `data.id` ausente, `data` que no es un objeto o un id con forma inválida ⇒ 200
  y ninguna llamada (nunca 500 ni un path traversal a la API de MP);
* el endpoint no pide JWT: los requests van sin `Authorization`.

httpx se mockea con `httpx.MockTransport`: no sale ningún request real a MP y el
token usado es un literal de prueba.

Correr (aislado, sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_mp_webhook_suscripciones.py -q
"""
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import mp_webhook as api_mp          # noqa: E402
from app.core.config import settings                  # noqa: E402
from app.core.rate_limit import limiter               # noqa: E402

# Token de mentira: el test verifica que viaje en el header, nunca su valor real.
TOKEN_FALSO = "token-de-prueba-no-real"
URL_ESPERADA = "https://api.mercadopago.com/preapproval/123456"


def _app():
    """App mínima: sólo el router de suscripciones, montado con su prefijo real."""
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_mp.router, prefix="/api/v1/mp")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    """Token falso para que el handler intente la consulta (nunca el real)."""
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", TOKEN_FALSO,
                        raising=False)


def _mock_mp(monkeypatch, *, status=404, cuerpo=None, error=None):
    """Inyecta un `httpx.MockTransport` y devuelve la lista de llamadas."""
    llamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        if error is not None:
            raise error(request)
        if cuerpo is not None:
            return httpx.Response(status, json=cuerpo)
        return httpx.Response(status, json={"message": "no encontrado"})

    monkeypatch.setattr(api_mp, "TRANSPORT", httpx.MockTransport(handler))
    return llamadas


def _simulacion_panel():
    """Body que manda "Simular notificación" → Planes y suscripciones."""
    return {
        "action": "updated",
        "api_version": "v1",
        "data": {"id": "123456"},
        "date_created": "2026-10-31T00:00:00.000-04:00",
        "id": "simulacion-123456",
        "live_mode": False,
        "type": "subscription_preapproval",
        "user_id": 123456789,
    }


# ── El caso que reporta el panel: id de prueba inexistente (404) ────────────
def test_simulacion_con_404_de_mp_responde_200(monkeypatch):
    """`data.id=123456` no existe en MP: el webhook igual responde 200."""
    llamadas = _mock_mp(monkeypatch, status=404)

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True}
    # Se consultó el preapproval REAL con el token del servidor en el header.
    assert len(llamadas) == 1
    assert str(llamadas[0].url) == URL_ESPERADA
    assert llamadas[0].headers["authorization"] == f"Bearer {TOKEN_FALSO}"


def test_el_id_tambien_se_lee_del_body_sin_query(monkeypatch):
    """MP manda `?data.id=` y el body; si falta el query, sirve el body."""
    llamadas = _mock_mp(monkeypatch, status=404)

    respuesta = _app().post("/api/v1/mp/webhook",
                            json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}
    assert len(llamadas) == 1
    assert str(llamadas[0].url) == URL_ESPERADA


def test_topic_viejo_preapproval_tambien_se_consulta(monkeypatch):
    llamadas = _mock_mp(monkeypatch, status=404)

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=preapproval&data.id=123456",
        json={"type": "preapproval", "data": {"id": "123456"}})

    assert respuesta.status_code == 200
    assert len(llamadas) == 1


# ── Cualquier falla de MP es 200 (nunca 5xx: MP reintenta cada 15 min) ──────
def test_401_de_mp_responde_200(monkeypatch):
    _mock_mp(monkeypatch, status=401, cuerpo={"message": "invalid token"})

    respuesta = _app().post("/api/v1/mp/webhook?type=subscription_preapproval"
                            "&data.id=123456", json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}


def test_500_de_mp_responde_200(monkeypatch):
    _mock_mp(monkeypatch, status=500, cuerpo={"message": "internal"})

    respuesta = _app().post("/api/v1/mp/webhook?type=subscription_preapproval"
                            "&data.id=123456", json=_simulacion_panel())

    assert respuesta.status_code == 200


def test_timeout_de_mp_responde_200(monkeypatch):
    _mock_mp(monkeypatch,
             error=lambda request: httpx.ConnectTimeout("timeout", request=request))

    respuesta = _app().post("/api/v1/mp/webhook?type=subscription_preapproval"
                            "&data.id=123456", json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}


def test_respuesta_que_no_es_json_responde_200(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"<html>no json</html>")

    monkeypatch.setattr(api_mp, "TRANSPORT", httpx.MockTransport(handler))

    respuesta = _app().post("/api/v1/mp/webhook?type=subscription_preapproval"
                            "&data.id=123456", json=_simulacion_panel())

    assert respuesta.status_code == 200


def test_preapproval_existente_responde_200_y_no_cambia_nada(monkeypatch):
    """Read-only: aunque MP devuelva un preapproval autorizado, sólo se loguea."""
    llamadas = _mock_mp(monkeypatch, status=200, cuerpo={
        "id": "123456", "status": "authorized", "payer_id": 999,
        "auto_recurring": {"transaction_amount": 44000, "currency_id": "CLP"},
    })

    respuesta = _app().post("/api/v1/mp/webhook?type=subscription_preapproval"
                            "&data.id=123456", json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}
    assert len(llamadas) == 1


# ── Topics que no son de suscripciones: se ignoran sin llamar a MP ──────────
@pytest.mark.parametrize("topic", [
    "payment",                    # va por /pagos/webhook/mercadopago
    "merchant_order",
    "chargebacks",
    "subscription_authorized_payment",   # su data.id NO es un preapproval
    "subscription_preapproval_plan",
    "topic-desconocido-de-mp",
    "",
])
def test_topics_ajenos_se_ignoran_con_200(monkeypatch, topic):
    llamadas = _mock_mp(monkeypatch, status=404)

    respuesta = _app().post(
        "/api/v1/mp/webhook",
        json={"id": "notif-1", "type": topic, "data": {"id": "123456"}})

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True}
    assert llamadas == [], f"{topic!r} no puede consultar el preapproval"


# ── `data.id` con manejo seguro: nunca 500, nunca una URL rara ──────────────
@pytest.mark.parametrize("body", [
    {"type": "subscription_preapproval"},                      # sin `data`
    {"type": "subscription_preapproval", "data": None},        # `data` nulo
    {"type": "subscription_preapproval", "data": []},          # `data` lista
    {"type": "subscription_preapproval", "data": "123456"},    # `data` string
    {"type": "subscription_preapproval", "data": {}},          # sin `id`
    {"type": "subscription_preapproval", "data": {"id": ""}},  # id vacío
])
def test_body_sin_data_id_valido_responde_200_sin_llamar(monkeypatch, body):
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post("/api/v1/mp/webhook", json=body)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True}
    assert llamadas == []


@pytest.mark.parametrize("id_invalido", [
    "../../users/me",       # path traversal a la API de MP
    "123/456",
    "123 456",
    "x" * 65,               # más largo que la columna de la bitácora
])
def test_id_con_forma_invalida_no_se_consulta(monkeypatch, id_invalido):
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval",
        json={"type": "subscription_preapproval",
              "data": {"id": id_invalido}})

    assert respuesta.status_code == 200, respuesta.text
    assert llamadas == []


def test_body_vacio_responde_200(monkeypatch):
    """Un POST sin body no puede explotar en el parseo."""
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post("/api/v1/mp/webhook")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True}
    assert llamadas == []


def test_sin_access_token_configurado_responde_200(monkeypatch):
    """Sin credencial no se llama a MP: se loguea y se responde 200 igual."""
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "",
                        raising=False)
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post("/api/v1/mp/webhook?type=subscription_preapproval"
                            "&data.id=123456", json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}
    assert llamadas == []


def test_el_endpoint_no_exige_autenticacion(monkeypatch):
    """MP no manda JWT: sin `Authorization` la simulación tiene que pasar."""
    _mock_mp(monkeypatch, status=404)

    respuesta = _app().post("/api/v1/mp/webhook?type=subscription_preapproval"
                            "&data.id=123456", json=_simulacion_panel())

    assert "authorization" not in {
        clave.lower() for clave in respuesta.request.headers}
    assert respuesta.status_code == 200
