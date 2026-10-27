"""Ráfagas de correo: espaciado + reintento ante `SMTPServerDisconnected` (FIX 2026-10-27).

Qué fija este archivo
---------------------
En los envíos masivos (scheduler de renovación/inactividad/urgencia/créditos y la campaña
de fidelización) Gmail corta la conexión y cada corte se llevaba puesto a ESE destinatario:
`_enviar` devolvía `False` y la fila quedaba `fallido` sin reintentar (16
`Connection unexpectedly closed` en PROD el 26/09/2026). Ahora:

1. `_enviar` reintenta `REINTENTOS_CORTE_SMTP` veces con una conexión **NUEVA** (la que se
   cayó ya no sirve) y el registro en `notificaciones_enviadas` sigue siendo **UNO**.
2. Si el corte persiste, el contrato es el de siempre: `False` + UNA fila `fallido`.
3. `espaciar_envio()` duerme `PAUSA_RAFAGA_S` entre correos de una ráfaga y **no duerme**
   en modo prueba (`noop`).
4. Los bucles masivos llaman a `espaciar_envio()` una vez por destinatario.

Sin red, sin SMTP y sin BD: `smtplib`, `time` y `_registrar_envio` van doblados.

Se corre con:
    py -3.12 -m pytest tests/test_email_rafaga_reintento.py -v --noconftest
"""
import smtplib
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.services import email_service  # noqa: E402


class _Registro:
    """Lo que el test necesita ver: filas registradas y segundos dormidos."""

    def __init__(self):
        self.filas = []      # (alumno_id, tipo, estado, detalle_error)
        self.dormido = []    # segundos de cada `time.sleep`

    def registrar(self, alumno_id=None, tipo="", estado="", detalle_error=None,
                  mes_referencia=None, **_ignorado):
        self.filas.append((alumno_id, tipo, estado, detalle_error))
        return len(self.filas)

    def estados(self) -> list:
        return [estado for _, _, estado, _ in self.filas]


class _SMTPFalso:
    """Doble de `smtplib.SMTP_SSL`.

    `cortes`: las primeras N conexiones se caen al enviar (ráfaga frenada por Gmail).
    `error`: si viene, TODA conexión falla con esa excepción (error que no es un corte).
    """

    cortes = 0
    error = None
    abiertas = 0
    enviados = []

    @classmethod
    def reiniciar(cls, cortes: int = 0, error=None):
        cls.cortes, cls.error = cortes, error
        cls.abiertas, cls.enviados = 0, []

    def __init__(self, host, port):
        self.host, self.port = host, port
        type(self).abiertas += 1
        self.numero = type(self).abiertas

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, usuario, clave):
        self.usuario, self.clave = usuario, clave

    def send_message(self, msg):
        if type(self).error is not None:
            raise type(self).error
        if self.numero <= type(self).cortes:
            # Lo mismo que hace Gmail cuando frena una ráfaga.
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        type(self).enviados.append(msg)


class _TiempoFalso:
    """Reemplaza al módulo `time` DENTRO de email_service (no duerme de verdad)."""

    def __init__(self, registro: _Registro):
        self._registro = registro

    def sleep(self, segundos):
        self._registro.dormido.append(segundos)


@pytest.fixture
def registro(monkeypatch):
    """SMTP doblado + registro/time doblados + credenciales: ni red ni BD."""
    reg = _Registro()
    _SMTPFalso.reiniciar()
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", _SMTPFalso)
    monkeypatch.setattr(email_service, "_registrar_envio", reg.registrar)
    monkeypatch.setattr(email_service, "time", _TiempoFalso(reg))
    monkeypatch.setattr(email_service.settings, "GMAIL_SMTP_USER", "box@example.com")
    monkeypatch.setattr(email_service.settings, "GMAIL_SMTP_APP_PASSWORD", "app-password")
    return reg


@pytest.fixture
def entorno_real(monkeypatch):
    """Producción + `EMAIL_MODO=real` + SMTP cargado ⇒ los correos salen de verdad."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(email_service.settings, "EMAIL_MODO", email_service.MODO_REAL)
    assert email_service.es_modo_simulado() is False


@pytest.fixture
def entorno_noop(monkeypatch):
    """Producción + `EMAIL_MODO=noop` ⇒ todo simulado (no hay SMTP que cuidar)."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(email_service.settings, "EMAIL_MODO", email_service.MODO_NOOP)
    assert email_service.es_modo_simulado() is True


# ── 1) Reintento con conexión nueva ──────────────────────────────────────────
def test_un_corte_se_reintenta_con_una_conexion_nueva(entorno_real, registro):
    """El corte del servidor NO pierde al destinatario: se reenvía por otra conexión."""
    _SMTPFalso.reiniciar(cortes=1)

    ok = email_service._enviar("alumno@example.com", "Asunto", "<p>hola</p>",
                               alumno_id=7, tipo="inactividad")

    assert ok is True
    assert _SMTPFalso.abiertas == 2, "el reintento tiene que ABRIR una conexión nueva"
    assert len(_SMTPFalso.enviados) == 1
    assert registro.estados() == ["enviado"], "un corte reintentado no es una fila 'fallido'"
    assert registro.dormido == [email_service.PAUSA_REINTENTO_S]


def test_el_reintento_no_duplica_el_registro(entorno_real, registro):
    """La fila de `notificaciones_enviadas` es UNA: la del envío que terminó bien."""
    _SMTPFalso.reiniciar(cortes=1)

    email_service._enviar("alumno@example.com", "Asunto", "<p>hola</p>",
                          alumno_id=7, tipo="inactividad")

    assert len(registro.filas) == 1
    assert registro.filas[0][0] == 7 and registro.filas[0][1] == "inactividad"


def test_si_el_corte_persiste_queda_fallido_una_sola_vez(entorno_real, registro):
    """Agotados los reintentos, el contrato es el de siempre: `False` + 1 fila `fallido`."""
    _SMTPFalso.reiniciar(cortes=99)

    ok = email_service._enviar("alumno@example.com", "Asunto", "<p>hola</p>",
                               alumno_id=7, tipo="inactividad")

    assert ok is False
    assert _SMTPFalso.abiertas == 1 + email_service.REINTENTOS_CORTE_SMTP
    assert _SMTPFalso.enviados == []
    assert registro.estados() == ["fallido"]
    assert "Connection unexpectedly closed" in registro.filas[0][3]


def test_un_error_que_no_es_corte_no_se_reintenta(entorno_real, registro):
    """Sólo `SMTPServerDisconnected` reintenta: un rechazo de credenciales falla de una."""
    _SMTPFalso.reiniciar(error=smtplib.SMTPAuthenticationError(535, b"credenciales"))

    ok = email_service._enviar("alumno@example.com", "Asunto", "<p>hola</p>",
                               alumno_id=7, tipo="inactividad")

    assert ok is False
    assert _SMTPFalso.abiertas == 1, "no se reintenta lo que no es un corte"
    assert registro.estados() == ["fallido"]


# ── 2) Espaciado de la ráfaga ───────────────────────────────────────────────
def test_espaciar_envio_duerme_la_pausa_configurada(entorno_real, registro):
    assert email_service.espaciar_envio() == email_service.PAUSA_RAFAGA_S
    assert registro.dormido == [email_service.PAUSA_RAFAGA_S]


def test_espaciar_envio_acepta_otro_ritmo(entorno_real, registro):
    assert email_service.espaciar_envio(1.5) == 1.5
    assert registro.dormido == [1.5]


def test_espaciar_envio_no_duerme_en_noop(entorno_noop, registro):
    """Una ráfaga simulada de 300 correos no puede tardar 2 minutos."""
    assert email_service.espaciar_envio() == 0.0
    assert registro.dormido == []


# ── 3) Los bucles masivos espacian una vez por destinatario ─────────────────
class _Fila:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resultado:
    def __init__(self, filas):
        self._filas = filas

    def fetchall(self):
        return self._filas


class _DBFalsa:
    """Sólo lo que usan los bucles: `execute(...).fetchall()`."""

    def __init__(self, filas):
        self.filas = filas

    def execute(self, *_a, **_k):
        return _Resultado(self.filas)


def test_el_bucle_de_alertas_espacia_una_vez_por_correo(entorno_real, registro, monkeypatch):
    """`enviar_alertas_sin_creditos`: 3 destinatarios ⇒ 3 correos y 3 pausas."""
    from app.services import alertas_email_service as alertas

    enviados = []

    def _send(nombre, correo, registrar=False):
        enviados.append(correo)
        return True

    monkeypatch.setattr(email_service, "send_alerta_sin_creditos", _send)
    monkeypatch.setattr(alertas, "_ya_enviado", lambda *a, **k: False)
    monkeypatch.setattr(alertas, "_reclamar_envio", lambda *a, **k: 1)
    monkeypatch.setattr(alertas, "_marcar_fallido", lambda *a, **k: None)

    db = _DBFalsa([_Fila(id=1, nombre="A", correo="a@example.com"),
                   _Fila(id=2, nombre="B", correo="b@example.com"),
                   _Fila(id=3, nombre="C", correo="c@example.com")])

    resumen = alertas.enviar_alertas_sin_creditos(db, tenant_id=1)

    assert resumen["enviados"] == 3 and resumen["fallidos"] == 0
    assert enviados == ["a@example.com", "b@example.com", "c@example.com"]
    assert registro.dormido == [email_service.PAUSA_RAFAGA_S] * 3


def test_un_deduplicado_no_gasta_pausa(entorno_real, registro, monkeypatch):
    """Si el alumno ya fue notificado no hay correo: tampoco hay nada que espaciar."""
    from app.services import alertas_email_service as alertas

    monkeypatch.setattr(email_service, "send_alerta_sin_creditos",
                        lambda *a, **k: pytest.fail("no debía enviarse"))
    monkeypatch.setattr(alertas, "_ya_enviado", lambda *a, **k: True)

    db = _DBFalsa([_Fila(id=1, nombre="A", correo="a@example.com")])
    resumen = alertas.enviar_alertas_sin_creditos(db, tenant_id=1)

    assert resumen["enviados"] == 0 and resumen["deduplicados"] == 1
    assert registro.dormido == []


def test_la_campana_de_fidelizacion_espacia_por_alumno(entorno_real, registro, monkeypatch):
    """La campaña manual (`POST /fidelizacion/campana-email/{tenant_id}`) también es ráfaga."""
    from app.api.v1 import fidelizacion

    enviados = []

    def _fake_envio(nombre, correo, dias_ausente):
        enviados.append(correo)
        return True

    monkeypatch.setattr(fidelizacion, "enviar_email_fidelizacion", _fake_envio)
    monkeypatch.setattr(fidelizacion, "analizar_fidelizacion", lambda *a, **k: {
        "alumnos_alerta": [
            {"nombre": "A", "correo": "a@example.com", "dias_ausente": 9, "tiene_historial": True},
            {"nombre": "B", "correo": "b@example.com", "dias_ausente": 12, "tiene_historial": True},
            {"nombre": "C", "correo": "c@example.com", "dias_ausente": None, "tiene_historial": False},
        ]})

    resumen = fidelizacion.enviar_campana_email(
        tenant_id=1, umbral_dias=7, background_tasks=None, db=None,
        current_user={"tenant_id": 1, "id": 1, "rol": "admin"})

    assert resumen["emails_enviados"] == 2
    assert enviados == ["a@example.com", "b@example.com"]
    assert resumen["omitidos_sin_historial"] == ["c@example.com"]
    assert registro.dormido == [email_service.PAUSA_RAFAGA_S] * 2
