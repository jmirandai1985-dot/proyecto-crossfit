"""Correo de bienvenida al LEAD (clase de prueba): recuadro "Tus próximos pasos".

QUÉ CUBRE (aislado: sin BD, sin red, sin SMTP)
----------------------------------------------
1. El HTML que sale de `send_solicitud_prueba_clase` trae el recuadro "Tus próximos
   pasos" con una lista NUMERADA (`<ol>`) de los 3 pasos exactos.
2. El recuadro va DESPUÉS de las credenciales (correo/contraseña) y ANTES del botón
   "Ingresar a mi cuenta": el lead lo lee como instrucción, no perdido en el párrafo.
3. El envío NO cambia: se sigue usando `_template` con el MISMO asunto, link y CTA, y
   `_enviar` recibe el mismo tipo/rol/tenant (acá se reemplaza `_enviar` por un espía).

    cd backend && py -3.12 -m pytest tests/test_email_proximos_pasos.py -q --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import email_service  # noqa: E402

NOMBRE = "Ana Pérez"
CORREO = "ana@test.com"
PASSWORD = "Temp-1234"
LINK = "https://box.cl/login"
TENANT = 1

PASOS = (
    "Entra con tu correo y la contraseña temporal de arriba.",
    "Te vamos a pedir que la cambies por una tuya (es obligatorio).",
    "Dentro verás la pestaña para agendar tu clase de prueba, y más adelante la de planes.",
)


def _enviar_correo(monkeypatch):
    """Ejecuta la función real y captura lo que recibiría `_enviar` (sin enviar nada)."""
    capturado = {}

    def _envio_falso(destinatario, asunto, html, *args, **kwargs):
        capturado.update({
            "destinatario": destinatario,
            "asunto": asunto,
            "html": html,
            "args": args,
            "kwargs": kwargs,
        })
        return True

    monkeypatch.setattr(email_service, "_enviar", _envio_falso)
    ok = email_service.send_solicitud_prueba_clase(
        NOMBRE, CORREO, PASSWORD, LINK, tenant_id=TENANT)

    assert ok is True
    assert capturado, "no se llamó a _enviar"
    return capturado


def test_el_correo_trae_el_recuadro_con_los_tres_pasos(monkeypatch):
    """El recuadro existe, es una lista numerada y los 3 pasos están completos."""
    html = _enviar_correo(monkeypatch)["html"]

    assert "Tus próximos pasos" in html
    assert "<ol" in html and "</ol>" in html, "la lista tiene que ser numerada (<ol>)"
    assert html.count("<li") == 3, "son exactamente 3 pasos"
    for paso in PASOS:
        assert paso in html, f"falta el paso: {paso}"

    # Estilos inline (los clientes de correo no cargan CSS externo) y caja visible.
    assert "background-color:#fff7ed" in html
    assert "border-left:4px solid #f97316" in html


def test_el_recuadro_va_despues_de_las_credenciales_y_antes_del_boton(monkeypatch):
    """Orden de lectura: credenciales -> qué hacer (pasos) -> CTA de ingreso."""
    html = _enviar_correo(monkeypatch)["html"]

    assert f"{CORREO}" in html and f"{PASSWORD}" in html
    pos_credenciales = html.index("Tu contraseña temporal:")
    pos_pasos = html.index("Tus próximos pasos")
    pos_boton = html.index("Ingresar a mi cuenta")

    assert pos_credenciales < pos_pasos, "los pasos van DESPUÉS de las credenciales"
    assert pos_pasos < pos_boton, "los pasos van ANTES del botón de ingreso"


def test_el_envio_y_el_asunto_no_cambian(monkeypatch):
    """Sigue usando `_template` con el mismo asunto, CTA, link y tipo de envío."""
    llamadas_template = []
    template_real = email_service._template

    def _template_espia(*args, **kwargs):
        llamadas_template.append((args, kwargs))
        return template_real(*args, **kwargs)

    monkeypatch.setattr(email_service, "_template", _template_espia)
    capturado = _enviar_correo(monkeypatch)

    assert len(llamadas_template) == 1, "el correo se arma con el MISMO helper _template"
    args, _ = llamadas_template[0]
    assert "Felicidades" in args[0]                 # título
    assert args[1] == f"¡Hola, {NOMBRE}!"            # saludo
    assert "Tus próximos pasos" in args[2]           # el recuadro va en el cuerpo
    assert args[3] == "Ingresar a mi cuenta"         # CTA sin cambios
    assert args[4] == LINK                           # link sin cambios

    assert capturado["destinatario"] == CORREO
    assert "Has tomado la mejor decisión de tu vida" in capturado["asunto"]
    # Mismos metadatos del envío best-effort (lead, sin alumno_id, scopeado al box).
    assert capturado["args"][0] is None
    assert capturado["kwargs"]["tipo"] == "solicitud_prueba_clase"
    assert capturado["kwargs"]["destinatario_nombre"] == NOMBRE
    assert capturado["kwargs"]["destinatario_rol"] == "lead"
    assert capturado["kwargs"]["tenant_id"] == TENANT
