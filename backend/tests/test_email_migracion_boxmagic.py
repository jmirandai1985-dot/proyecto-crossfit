"""Correo de activación de BoxMagic (`render_email_migracion_boxmagic`) — AISLADO.

Cubre SIN red y SIN SMTP:
  * el asunto y el cuerpo EXACTOS aprobados (no se puede reescribir el copy);
  * el link del token llega al botón "Activar mi cuenta";
  * el correo usa el MISMO motor de marca (`_template`/`encabezado_marca`): logo,
    borde naranja y pie de contacto, sin un HTML propio;
  * `enviar_email_migracion_boxmagic` manda con `alumno_id=None` y los
    `destinatario_*` del padrón (el candidato todavía no es un Usuario);
  * sin correo no se intenta ningún envío.

    cd backend && py -3.12 -m pytest tests/test_email_migracion_boxmagic.py -q --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import email_service  # noqa: E402

ASUNTO = ("Tu cuenta de Urban Training Box ahora es digital - "
          "activa tu acceso aqui")

CUERPO = (
    "Urban Training Box esta pasando a un nuevo sistema de gestion - y viene "
    "con hartas cosas nuevas: Tu Performance Hub (todas tus marcas y metricas "
    "de rendimiento en un solo lugar), Tu evolucion (ve tu progreso a traves "
    "del tiempo, clase a clase), El Bazar (pide tus productos y accesorios del "
    "box directo desde la app), y tus clases/plan/pagos todo desde un solo "
    "lugar. Si todavia tienes clases o creditos pendientes en BoxMagic se "
    "mantienen sin cambios hasta que se agoten. Despues de activar tu cuenta y "
    "entrar por primera vez te va a aparecer un aviso para instalar la app en "
    "la pantalla principal de tu telefono."
)

LINK = "https://app.urbantrainingbox.cl/migracion/activar?token=abc123"


def test_asunto_exacto():
    asunto, _ = email_service.render_email_migracion_boxmagic("Juan Pérez", LINK)

    assert asunto == ASUNTO


def test_cuerpo_y_saludo_exactos():
    _, html = email_service.render_email_migracion_boxmagic("Juan Pérez", LINK)

    assert "Hola Juan Pérez," in html
    assert CUERPO in html


def test_boton_y_link_del_token():
    _, html = email_service.render_email_migracion_boxmagic("Ana", LINK)

    assert ">Activar mi cuenta</a>" in html
    assert f'href="{LINK}"' in html


def test_usa_el_mismo_encabezado_de_marca():
    """Nada de un header propio: borde naranja, logo y pie vienen de `_template`."""
    _, html = email_service.render_email_migracion_boxmagic("Ana", LINK)

    assert "border:3px solid #ff8c00" in html
    assert "<img src=" in html
    assert email_service.PLACEHOLDER_CONTACTO in html
    assert "Urban Training Box — CrossFit Maipú" in html


def test_envia_con_destinatario_del_padron(monkeypatch):
    capturado = {}

    def _enviar_falso(destinatario, asunto, html, alumno_id=None, tipo="",
                      **kwargs):
        capturado.update({
            "destinatario": destinatario, "asunto": asunto, "html": html,
            "alumno_id": alumno_id, "tipo": tipo, **kwargs,
        })
        return True

    monkeypatch.setattr(email_service, "_enviar", _enviar_falso)

    ok = email_service.enviar_email_migracion_boxmagic(
        {"id": None, "nombre": "Ana Soto", "correo": "ana@test.com",
         "tenant_id": 3},
        LINK,
    )

    assert ok is True
    assert capturado["destinatario"] == "ana@test.com"
    assert capturado["asunto"] == ASUNTO
    assert capturado["alumno_id"] is None
    assert capturado["tipo"] == "migracion_activacion"
    assert capturado["destinatario_nombre"] == "Ana Soto"
    # La fila de notificaciones no puede decir que el destinatario es alumno.
    assert capturado["destinatario_rol"] == "lead"
    assert capturado["tenant_id"] == 3
    assert LINK in capturado["html"]


def test_sin_correo_no_manda_nada(monkeypatch):
    llamado = {"veces": 0}

    def _enviar_falso(*args, **kwargs):
        llamado["veces"] += 1
        return True

    monkeypatch.setattr(email_service, "_enviar", _enviar_falso)

    ok = email_service.enviar_email_migracion_boxmagic(
        {"id": None, "nombre": "Sin Correo", "correo": "", "tenant_id": 3},
        LINK,
    )

    assert ok is False
    assert llamado["veces"] == 0


def test_devuelve_el_fallo_del_motor(monkeypatch):
    monkeypatch.setattr(email_service, "_enviar",
                        lambda *args, **kwargs: False)

    ok = email_service.enviar_email_migracion_boxmagic(
        {"id": None, "nombre": "Ana", "correo": "ana@test.com", "tenant_id": 3},
        LINK,
    )

    assert ok is False
