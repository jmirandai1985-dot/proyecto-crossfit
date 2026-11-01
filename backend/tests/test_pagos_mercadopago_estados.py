"""Pagos con Mercado Pago: mapa de estados, montos, configuración y firma.

Tests PUROS (sin base de datos y sin red):

* el mapa `status` de MP -> estado interno es la única puerta que decide si se
  activa un plan o se valida un pedido: `approved` sí, `in_process` NO;
* un estado nuevo de MP devuelve `None` (no puede hacer retroceder un pago ya
  aprobado a "pendiente");
* `monto_clp` redondea el Float del Bazar a entero (CLP no tiene decimales);
* sin credenciales o con la pasarela apagada, el servicio corta con
  `PagoOnlineNoDisponible` (el endpoint lo traduce a 503);
* la firma del webhook se valida con el validador del SDK oficial: válida pasa,
  secreto equivocado / header ausente / `ts` viejo se rechazan;
* la preferencia se arma con `external_reference`, monto ENTERO y el
  `sandbox_init_point` cuando el modo no es producción.

El SDK no se llama de verdad: se inyecta un doble en `_SDK_CACHE`.
"""
import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                      # noqa: E402
from app.services import mercadopago_cliente as mp        # noqa: E402


# ── Mapa de estados ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("status,esperado", [
    ("approved", "aprobado"),
    ("pending", "pendiente"),
    ("in_process", "en_proceso"),
    ("authorized", "en_proceso"),
    ("rejected", "rechazado"),
    ("cancelled", "cancelado"),
    ("refunded", "reembolsado"),
    ("charged_back", "reembolsado"),
])
def test_estado_desde_mp(status, esperado):
    assert mp.estado_desde_mp(status) == esperado


def test_solo_approved_activa_el_beneficio():
    assert mp.activa_beneficio("approved") is True
    for status in ("pending", "in_process", "authorized", "rejected",
                   "cancelled", "refunded", "charged_back", "", None):
        assert mp.activa_beneficio(status) is False, (
            f"{status!r} no puede activar un plan ni validar un pedido")


def test_estado_desconocido_no_es_pendiente():
    """Un estado nuevo de MP NO puede degradar un pago aprobado."""
    assert mp.estado_desde_mp("algo_nuevo_de_mp") is None
    assert mp.estado_desde_mp(None) is None


def test_status_llega_con_espacios_o_mayusculas():
    assert mp.estado_desde_mp(" APPROVED ") == "aprobado"


# ── Montos ──────────────────────────────────────────────────────────────────
def test_monto_clp_redondea_el_float_del_bazar():
    assert mp.monto_clp(19990.0) == 19990
    assert mp.monto_clp(19990.4) == 19990
    assert mp.monto_clp(19990.5) == 19990      # round() de Python: al par
    assert isinstance(mp.monto_clp(19990.7), int)


def test_monto_clp_no_inventa_plata():
    assert mp.monto_clp(None) == 0
    assert mp.monto_clp("") == 0
    assert mp.monto_clp("no-es-un-monto") == 0
    assert mp.monto_clp(True) == 0


# ── Configuración fail-fast ─────────────────────────────────────────────────
def test_apagado_por_default_no_se_puede_cobrar(monkeypatch):
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", False, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "APP_USR-x",
                        raising=False)
    with pytest.raises(mp.PagoOnlineNoDisponible) as error:
        mp.configuracion()
    assert error.value.motivo == "deshabilitado"
    assert mp.habilitado() is False


def test_sin_access_token_tampoco(monkeypatch):
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", True, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "  ", raising=False)
    with pytest.raises(mp.PagoOnlineNoDisponible) as error:
        mp.configuracion()
    assert error.value.motivo == "sin_credenciales"
    assert mp.habilitado() is False


def test_configuracion_completa_marca_sandbox_en_test(monkeypatch):
    _config_de_prueba(monkeypatch, modo="test")
    config = mp.configuracion()
    assert config["sandbox"] is True
    assert config["access_token"] == "TEST-token"
    assert config["back_url_base"] == "https://app.test"
    assert mp.habilitado() is True


def test_modo_production_no_usa_sandbox(monkeypatch):
    _config_de_prueba(monkeypatch, modo="production")
    assert mp.configuracion()["sandbox"] is False


def _config_de_prueba(monkeypatch, modo="test"):
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", True, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "TEST-token",
                        raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_MODO", modo, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "secreto",
                        raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_BACK_URL_BASE",
                        "https://app.test/", raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_NOTIFICATION_URL",
                        "https://api.test/api/v1/pagos/webhook/mercadopago",
                        raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_TEST_BUYER_EMAIL", "",
                        raising=False)



# ── Firma del webhook (HMAC-SHA256 con el secreto del box) ──────────────────
def _firmar(secreto: str, data_id: str, request_id: str, ts: int) -> str:
    """Reproduce el manifest que documenta MP (y que firma el SDK)."""
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    firma = hmac.new(secreto.encode("utf-8"), manifest.encode("utf-8"),
                     hashlib.sha256).hexdigest()
    return f"ts={ts},v1={firma}"


def test_firma_valida_pasa():
    ts = int(time.time())
    header = _firmar("secreto", "123456789", "req-1", ts)
    mp.validar_firma(header, "req-1", "123456789", "secreto")


def test_firma_con_otro_secreto_se_rechaza():
    ts = int(time.time())
    header = _firmar("otro-secreto", "123456789", "req-1", ts)
    with pytest.raises(mp.FirmaInvalida) as error:
        mp.validar_firma(header, "req-1", "123456789", "secreto")
    assert error.value.motivo == "SignatureMismatch"


def test_firma_ausente_se_rechaza():
    with pytest.raises(mp.FirmaInvalida) as error:
        mp.validar_firma(None, "req-1", "123456789", "secreto")
    assert error.value.motivo == "MissingSignatureHeader"


def test_firma_con_ts_viejo_se_rechaza_por_replay():
    ts = int(time.time()) - mp.TOLERANCIA_FIRMA_SEGUNDOS - 60
    header = _firmar("secreto", "123456789", "req-1", ts)
    with pytest.raises(mp.FirmaInvalida) as error:
        mp.validar_firma(header, "req-1", "123456789", "secreto")
    assert error.value.motivo == "TimestampOutOfTolerance"


def test_firma_sin_hash_se_rechaza():
    with pytest.raises(mp.FirmaInvalida):
        mp.validar_firma("ts=1704908010", "req-1", "123456789", "secreto")


# ── Preferencia (Checkout Pro) con un SDK de mentira ────────────────────────
class _Preferencia:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.payload = None

    def create(self, datos):
        self.payload = datos
        return self.respuesta


class _Pagos:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.pedidos = []

    def get(self, payment_id):
        self.pedidos.append(payment_id)
        return self.respuesta


class _SDKFalso:
    def __init__(self, preferencia=None, pago=None):
        self._preferencia = _Preferencia(preferencia) if preferencia else None
        self._pago = _Pagos(pago) if pago else None

    def preference(self):
        return self._preferencia

    def payment(self):
        return self._pago


def _pago(monto=19990):
    from types import SimpleNamespace
    return SimpleNamespace(id=7, monto_clp=monto,
                           external_reference="uuid-externo-123")


def test_preferencia_arma_el_payload_y_usa_sandbox(monkeypatch):
    _config_de_prueba(monkeypatch, modo="test")
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-1",
        "init_point": "https://mp/prod",
        "sandbox_init_point": "https://mp/sandbox",
    }})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    preference_id, init_point = mp.crear_preferencia(
        pago=_pago(19990.0), titulo="Plan King Kong", email="a@b.cl")

    assert preference_id == "pref-1"
    assert init_point == "https://mp/sandbox", "en test se usa sandbox_init_point"
    payload = sdk._preferencia.payload
    assert payload["external_reference"] == "uuid-externo-123"
    assert payload["items"][0]["unit_price"] == 19990
    assert isinstance(payload["items"][0]["unit_price"], int), \
        "CLP no tiene decimales: mandar un Float es un monto inválido"
    assert payload["items"][0]["currency_id"] == "CLP"
    # En sandbox el email real del alumno NO viaja: sin test buyer configurado
    # el payer queda vacío y no se manda.
    assert "payer" not in payload
    assert payload["notification_url"].endswith("/pagos/webhook/mercadopago")
    assert payload["back_urls"]["success"].endswith("/alumno/pago/resultado/7")
    assert "payment_methods" not in payload


def test_preferencia_usa_el_rut_valido_como_identification(monkeypatch):
    _config_de_prueba(monkeypatch, modo="production")
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-rut",
        "init_point": "https://mp/prod",
        "sandbox_init_point": "https://mp/sandbox",
    }})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    mp.crear_preferencia(pago=_pago(), titulo="Plan", email="a@b.cl",
                         rut="11.111.111-1")

    assert sdk._preferencia.payload["payer"] == {
        "email": "a@b.cl",
        "identification": {"type": "RUT", "number": "11111111-1"},
    }


def test_preferencia_omite_identification_si_el_rut_no_sirve(monkeypatch):
    _config_de_prueba(monkeypatch, modo="production")
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-sin-rut",
        "init_point": "https://mp/prod",
        "sandbox_init_point": "https://mp/sandbox",
    }})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    # DV inválido a propósito: el RUT no se manda ni como string vacío.
    mp.crear_preferencia(pago=_pago(), titulo="Plan", email="a@b.cl",
                         rut="12.345.678-9")

    assert sdk._preferencia.payload["payer"] == {"email": "a@b.cl"}
    assert "identification" not in sdk._preferencia.payload["payer"]


def test_preferencia_sin_datos_del_pagador_no_manda_payer(monkeypatch):
    _config_de_prueba(monkeypatch)
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-sin-payer",
        "init_point": "https://mp/prod",
        "sandbox_init_point": "https://mp/sandbox",
    }})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    mp.crear_preferencia(pago=_pago(), titulo="Plan")

    assert "payer" not in sdk._preferencia.payload


def test_preferencia_en_sandbox_usa_el_email_del_test_buyer(monkeypatch):
    _config_de_prueba(monkeypatch, modo="test")
    monkeypatch.setattr(settings, "MERCADOPAGO_TEST_BUYER_EMAIL",
                        "comprador@test.com", raising=False)
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-testbuyer",
        "init_point": "https://mp/prod",
        "sandbox_init_point": "https://mp/sandbox",
    }})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    mp.crear_preferencia(pago=_pago(), titulo="Plan",
                         email="alumna.real@gmail.com", rut="11.111.111-1")

    assert sdk._preferencia.payload["payer"] == {
        "email": "comprador@test.com",
        "identification": {"type": "RUT", "number": "11111111-1"},
    }


def test_preferencia_en_sandbox_sin_test_buyer_no_manda_el_email_real(monkeypatch):
    _config_de_prueba(monkeypatch, modo="test")
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-sin-testbuyer",
        "init_point": "https://mp/prod",
        "sandbox_init_point": "https://mp/sandbox",
    }})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    mp.crear_preferencia(pago=_pago(), titulo="Plan",
                         email="alumna.real@gmail.com")

    # El correo real no se filtra al sandbox y, sin RUT, el payer queda vacío.
    assert "payer" not in sdk._preferencia.payload


def test_preferencia_en_produccion_usa_el_email_real(monkeypatch):
    _config_de_prueba(monkeypatch, modo="production")
    monkeypatch.setattr(settings, "MERCADOPAGO_TEST_BUYER_EMAIL",
                        "comprador@test.com", raising=False)
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-prod-email",
        "init_point": "https://mp/prod",
    }})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    mp.crear_preferencia(pago=_pago(), titulo="Plan",
                         email="alumna.real@gmail.com")

    assert sdk._preferencia.payload["payer"] == {"email": "alumna.real@gmail.com"}


def test_preferencia_en_produccion_usa_init_point(monkeypatch):
    _config_de_prueba(monkeypatch, modo="production")
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-2", "init_point": "https://mp/prod",
        "sandbox_init_point": "https://mp/sandbox"}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)
    _, init_point = mp.crear_preferencia(pago=_pago(), titulo="Plan")
    assert init_point == "https://mp/prod"


def test_bazar_puede_excluir_medios_que_se_acreditan_tarde(monkeypatch):
    _config_de_prueba(monkeypatch)
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-3", "init_point": "https://mp/prod"}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)
    mp.crear_preferencia(pago=_pago(9990), titulo="Polera",
                         excluir_medios=mp.MEDIOS_EXCLUIDOS_BAZAR)
    assert sdk._preferencia.payload["payment_methods"] == {
        "excluded_payment_types": [{"id": "ticket"}]}


def test_preferencia_sin_init_point_falla(monkeypatch):
    _config_de_prueba(monkeypatch)
    sdk = _SDKFalso(preferencia={"status": 201, "response": {"id": "pref-4"}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)
    with pytest.raises(mp.ErrorMercadoPago):
        mp.crear_preferencia(pago=_pago(), titulo="Plan")


def test_preferencia_usa_auto_return_con_back_url_https(monkeypatch):
    _config_de_prueba(monkeypatch)
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-5", "init_point": "https://mp/prod"}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)
    mp.crear_preferencia(pago=_pago(), titulo="Plan")
    assert sdk._preferencia.payload["auto_return"] == "approved"


def test_preferencia_sin_https_omite_auto_return(monkeypatch):
    """MP rechaza la preferencia ENTERA (`400 invalid_auto_return`) si `auto_return`
    viaja con una `back_urls.success` http (localhost o IP de LAN). En local se
    omite: el alumno vuelve con el botón de MP y el pago se confirma por webhook.
    """
    _config_de_prueba(monkeypatch)
    monkeypatch.setattr(settings, "MERCADOPAGO_BACK_URL_BASE",
                        "http://192.168.100.241:5173", raising=False)
    sdk = _SDKFalso(preferencia={"status": 201, "response": {
        "id": "pref-6", "init_point": "https://mp/prod"}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)

    mp.crear_preferencia(pago=_pago(), titulo="Plan")

    payload = sdk._preferencia.payload
    assert payload["back_urls"]["success"].startswith("http://192.168.100.241:5173")
    assert "auto_return" not in payload, \
        "con back_urls http MP responde 400 invalid_auto_return (el endpoint lo "\
        "mostraba como un 503 genérico)"


def test_preferencia_rechazada_por_mp_falla(monkeypatch):
    _config_de_prueba(monkeypatch)
    sdk = _SDKFalso(preferencia={"status": 401,
                                 "response": {"message": "invalid token"}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)
    with pytest.raises(mp.ErrorMercadoPago):
        mp.crear_preferencia(pago=_pago(), titulo="Plan")


def test_leer_pago_devuelve_el_pago_real(monkeypatch):
    _config_de_prueba(monkeypatch)
    sdk = _SDKFalso(pago={"status": 200, "response": {
        "id": 555, "status": "approved", "transaction_amount": 19990}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)
    detalle = mp.leer_pago(555)
    assert detalle["status"] == "approved"
    assert sdk._pago.pedidos == ["555"]


def test_leer_pago_404_es_error(monkeypatch):
    _config_de_prueba(monkeypatch)
    sdk = _SDKFalso(pago={"status": 404, "response": {}})
    monkeypatch.setitem(mp._SDK_CACHE, "TEST-token", sdk)
    with pytest.raises(mp.ErrorMercadoPago):
        mp.leer_pago(999)


