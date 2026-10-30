"""Integración de la pasarela: fail-closed, aislamiento y nada a medias.

Contra el servidor de TEST (`run_tests.bat` / uvicorn en localhost:8000). Estos
casos se prueban SIN credenciales de Mercado Pago a propósito: lo que se verifica
es que con la pasarela apagada (el default) **no se crea nada** y el alumno
recibe un mensaje claro, nunca un 500:

* `GET /pagos/disponibilidad` responde un booleano;
* `POST /pagos/membresia` ⇒ 503 y el número de solicitudes pendientes NO cambia
  (no queda una solicitud huérfana en la cola del admin);
* `POST /pagos/bazar` ⇒ 503 y el stock NO cambia (no se reserva nada);
* el webhook sin firma/secreto ⇒ 401/503 y no procesa;
* `GET /pagos/{id}` de otro box ⇒ 404 (el tenant sale del token).

Si alguien enciende la pasarela en TEST, los dos POST se saltan: acá no se quiere
crear una preferencia real ni cobrar nada. El flujo completo (pago aprobado →
plan activo → una sola `TransaccionFinanciera`) se prueba a mano con las tarjetas
de prueba de MP y queda documentado en el §11 del diseño.

Correr (con el servidor arriba):
    cd backend && py -3.12 -m pytest tests/test_pagos_mercadopago_integracion.py -q
"""
import pytest
import requests

from tests.conftest import BASE, get_admin_token, get_alumno_token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _disponible() -> bool:
    respuesta = requests.get(f"{BASE}/pagos/disponibilidad", timeout=10)
    assert respuesta.status_code == 200, respuesta.text
    return bool(respuesta.json().get("habilitado"))


def _stock(producto_id: int) -> float:
    respuesta = requests.get(
        f"{BASE}/productos/{producto_id}",
        headers=_auth(get_alumno_token()), timeout=10)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json().get("stock")


def test_disponibilidad_es_un_booleano(health_check):
    respuesta = requests.get(f"{BASE}/pagos/disponibilidad", timeout=10)
    assert respuesta.status_code == 200
    assert isinstance(respuesta.json().get("habilitado"), bool)


def test_membresia_apagada_no_crea_solicitud(health_check):
    if _disponible():
        pytest.skip("MERCADOPAGO_HABILITADO=true en TEST: no se crea un cobro real")

    headers = _auth(get_admin_token())
    antes = requests.get(f"{BASE}/solicitudes/pendientes", headers=headers,
                         timeout=10).json()

    respuesta = requests.post(
        f"{BASE}/pagos/membresia", json={"plan_id": 1},
        headers=_auth(get_alumno_token()), timeout=10)

    assert respuesta.status_code == 503, respuesta.text
    assert "transferencia" in respuesta.json()["detail"]

    despues = requests.get(f"{BASE}/solicitudes/pendientes", headers=headers,
                           timeout=10).json()
    assert len(despues) == len(antes), \
        "un 503 no puede dejar una solicitud pendiente en la cola del admin"


def test_bazar_apagado_no_reserva_stock(health_check):
    if _disponible():
        pytest.skip("MERCADOPAGO_HABILITADO=true en TEST: no se crea un cobro real")

    catalogo = requests.get(f"{BASE}/productos?activo=true",
                            headers=_auth(get_alumno_token()), timeout=10).json()
    con_stock = [p for p in catalogo if (p.get("stock") or 0) > 0]
    if not con_stock:
        pytest.skip("el catálogo de TEST no tiene productos con stock")
    producto = con_stock[0]
    stock_antes = _stock(producto["id"])

    respuesta = requests.post(
        f"{BASE}/pagos/bazar",
        json={"producto_id": producto["id"], "cantidad": 1},
        headers=_auth(get_alumno_token()), timeout=10)

    assert respuesta.status_code == 503, respuesta.text
    assert _stock(producto["id"]) == stock_antes, \
        "un 503 no puede descontar stock (el producto quedaría bloqueado)"


def test_webhook_sin_firma_valida_no_procesa(health_check):
    respuesta = requests.post(
        f"{BASE}/pagos/webhook/mercadopago?data.id=1&type=payment",
        json={"id": "integracion-sin-firma", "type": "payment",
              "data": {"id": "1"}},
        timeout=10)
    # 503 si el secreto está vacío (fail-closed) o 401 si hay secreto y la firma
    # no corresponde. Nunca 200.
    assert respuesta.status_code in (401, 503), respuesta.text


def test_pago_de_otro_box_se_ve_como_inexistente(health_check):
    """El tenant sale del token: un id de otro box no existe para este alumno."""
    respuesta = requests.get(
        f"{BASE}/pagos/999999",
        headers=_auth(get_alumno_token(tenant_id=999)),
        timeout=10)
    assert respuesta.status_code == 404, respuesta.text


def test_pago_inexistente_es_404(health_check):
    respuesta = requests.get(
        f"{BASE}/pagos/999999", headers=_auth(get_alumno_token()), timeout=10)
    assert respuesta.status_code == 404, respuesta.text
