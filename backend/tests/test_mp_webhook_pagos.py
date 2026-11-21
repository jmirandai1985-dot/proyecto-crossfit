"""
`POST /api/v1/mp/webhook` con `type=payment` (Checkout Pro): firma y delegación.

Por qué existe: en el panel de Mercado Pago la URL de notificación se configura
UNA sola vez por aplicación. Si esa URL queda en el webhook de "Planes y
suscripciones" (`/api/v1/mp/webhook`), un cobro de UN plan llega con
`type=payment`; antes ese topic se ignoraba y el alumno pagaba sin que su plan se
activara (incidente 2026-11: pago real aprobado, plan sin activar). Ahora esta
rama valida la firma HMAC con `MERCADOPAGO_WEBHOOK_SECRET` y delega en
`services/pagos.procesar_aviso_pago`, el MISMO camino (relectura del pago en MP +
`activar_plan`) del webhook de cobros.

Qué se prueba acá (sin red y sin base):

* sin secreto ⇒ 503 (fail-closed) y NO se procesa nada;
* sin `x-signature` o firmada con otro secreto ⇒ 401;
* firma válida ⇒ 200 y se delega con los ids correctos (`notificacion_id`,
  `recurso_id`, `request_id`, `ts`);
* reintento del mismo aviso ⇒ el servicio devuelve `duplicado` y el endpoint lo
  publica tal cual (la idempotencia real es el UNIQUE de `pagos_eventos`);
* `data.id` malformado ⇒ 200 `ignorado` sin tocar MP;
* un topic de suscripciones NO pasa por el camino de pagos.

Lo que el servicio hace con el pago (monto, CAS, `activar_plan`) lo cubren
`tests/test_pagos_webhook_firma.py` y las pruebas de integración.

Correr (aislado, sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_mp_webhook_pagos.py -q --noconftest
"""
import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import mp_webhook as api_mp          # noqa: E402
from app.core.config import settings                 # noqa: E402
from app.core.rate_limit import limiter              # noqa: E402
from app.db.database import get_db                   # noqa: E402
from app.services import pagos as servicio_pagos     # noqa: E402

SECRETO = "secreto-de-prueba"
DATA_ID = "123456789"
REQUEST_ID = "req-1"


class _SesionFalsa:
    """Sesión mínima: `procesar_aviso_pago` se sustituye en estos tests."""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _app(sesion):
    """App mínima: sólo el router de suscripciones, con `get_db` sustituido."""
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_mp.router, prefix="/api/v1/mp")
    app.dependency_overrides[get_db] = lambda: sesion
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _cuota(monkeypatch):
    """Secreto de prueba y contador de rate limit limpio (30/min por IP)."""
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", SECRETO,
                        raising=False)
    limiter.reset()


def _firmar(data_id: str = DATA_ID, request_id: str = REQUEST_ID, ts=None,
            secreto: str = SECRETO):
    ts = int(time.time()) if ts is None else ts
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    firma = hmac.new(secreto.encode(), manifest.encode(),
                     hashlib.sha256).hexdigest()
    return f"ts={ts},v1={firma}", ts


def _webhook(cliente, *, cuerpo=None, data_id=DATA_ID, request_id=REQUEST_ID,
             firma=None, tipo="payment"):
    headers = {"x-request-id": request_id}
    if firma is not None:
        headers["x-signature"] = firma
    return cliente.post(
        f"/api/v1/mp/webhook?data.id={data_id}&type={tipo}",
        json=cuerpo, headers=headers)


def _aviso_pago(notificacion_id="notif-1"):
    """Body de una notificación de Checkout Pro."""
    return {
        "id": notificacion_id,
        "type": "payment",
        "action": "payment.updated",
        "data": {"id": DATA_ID},
    }


def _espia(monkeypatch, resultado="aplicado"):
    """Sustituye el servicio y devuelve la lista de llamadas capturadas."""
    llamadas = []

    def falso(db, *, notificacion_id, tipo, recurso_id, request_id=None,
              ts_header=None):
        llamadas.append({
            "notificacion_id": notificacion_id, "tipo": tipo,
            "recurso_id": recurso_id, "request_id": request_id,
            "ts_header": ts_header,
        })
        return resultado

    monkeypatch.setattr(servicio_pagos, "procesar_aviso_pago", falso)
    return llamadas


# ── Fail-closed: sin secreto o con firma inválida no se procesa nada ─────────
def test_sin_secreto_es_503_y_no_procesa(monkeypatch):
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "",
                        raising=False)
    llamadas = _espia(monkeypatch)
    firma, _ = _firmar()

    respuesta = _webhook(_app(_SesionFalsa()), cuerpo=_aviso_pago(), firma=firma)

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "Webhook de pagos no configurado"
    assert llamadas == []


def test_sin_firma_es_401(monkeypatch):
    llamadas = _espia(monkeypatch)

    respuesta = _webhook(_app(_SesionFalsa()), cuerpo=_aviso_pago())

    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "Firma inválida"
    assert llamadas == []


def test_firma_de_otro_secreto_es_401(monkeypatch):
    llamadas = _espia(monkeypatch)
    firma, _ = _firmar(secreto="otro-secreto")

    respuesta = _webhook(_app(_SesionFalsa()), cuerpo=_aviso_pago(), firma=firma)

    assert respuesta.status_code == 401
    assert llamadas == []


def test_firma_de_otro_data_id_es_401(monkeypatch):
    """La firma cubre `data.id`: no se puede reusar la de otro pago."""
    llamadas = _espia(monkeypatch)
    firma, _ = _firmar(data_id="999")

    respuesta = _webhook(_app(_SesionFalsa()), cuerpo=_aviso_pago(), firma=firma)

    assert respuesta.status_code == 401
    assert llamadas == []


# ── Firma válida: 200 rápido y delegación en el servicio de pagos ────────────
def test_pago_aprobado_delega_en_el_servicio_y_responde_200(monkeypatch):
    llamadas = _espia(monkeypatch, resultado="aplicado")
    firma, ts = _firmar()

    respuesta = _webhook(
        _app(_SesionFalsa()),
        cuerpo=_aviso_pago(notificacion_id="notif-1"), firma=firma)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "resultado": "aplicado"}
    assert llamadas == [{
        "notificacion_id": "notif-1",
        "tipo": "payment",
        "recurso_id": DATA_ID,
        "request_id": REQUEST_ID,
        "ts_header": str(ts)[:20],
    }]


def test_reintento_del_mismo_aviso_publica_duplicado(monkeypatch):
    """La idempotencia real es el UNIQUE de `pagos_eventos`; acá se propaga."""
    _espia(monkeypatch, resultado="duplicado")
    firma, _ = _firmar()

    respuesta = _webhook(_app(_SesionFalsa()), cuerpo=_aviso_pago(),
                         firma=firma)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "resultado": "duplicado"}


def test_data_id_malformado_se_ignora_sin_firma(monkeypatch):
    """El id viene de un endpoint público: no puede convertirse en path traversal."""
    llamadas = _espia(monkeypatch)

    respuesta = _webhook(_app(_SesionFalsa()), cuerpo=_aviso_pago(),
                         data_id="../../etc/passwd")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "resultado": "ignorado"}
    assert llamadas == []


def test_topic_de_suscripcion_no_pasa_por_el_camino_de_pagos(monkeypatch):
    """`subscription_preapproval_plan` es una plantilla: se corta sin llamar a MP."""
    llamadas = _espia(monkeypatch)

    respuesta = _webhook(
        _app(_SesionFalsa()),
        cuerpo={"id": "sim-1", "type": "subscription_preapproval_plan",
                "data": {"id": "123456"}},
        data_id="123456", tipo="subscription_preapproval_plan")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "resultado": "ignorado"}
    assert llamadas == []
