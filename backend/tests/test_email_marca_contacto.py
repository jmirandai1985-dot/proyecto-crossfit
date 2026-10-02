"""Bloque C: el logo del gorila, el encabezado único y el contacto del box en los correos.

Qué cubre
---------
A. PURAS (sin BD, sin red, sin API):
   1. El encabezado es el logo del gorila por **URL pública** (`/imgs/logo.png`), a 160 px,
      con `alt` y el nombre en texto debajo (si el cliente bloquea imágenes, se entiende).
   2. El encabezado tiene **una sola definición** (`email_service.encabezado_marca`) y lo usan
      todos los correos: el `h1` de texto viejo no puede volver a copiarse en ningún módulo.
   3. Los asuntos salen en **texto plano**: el bug `est&aacute;` (que se mostraba literal)
      se ve como acento de verdad, también después de codificar/decodificar el header.
   4. La llamada a la acción invita a VOLVER (reservar/activar), no a coordinar con el coach.
   5. `wa_link` normaliza el número del box y `render_con_contacto` resuelve el placeholder
      (con WhatsApp del box, o con el fallback de "responde este correo").
B. CONTRA TEST (escribe y RESTAURA):
   6. `configuracion_negocio.whatsapp` es la fuente del contacto: se guarda por la API (como lo
      hace el admin), el correo sale con ese link, y vacío = el correo no promete un canal.
   7. El correo que SALE de verdad (SMTP falso) no lleva el placeholder y su asunto con acentos
      llega legible.

Ningún test manda correo real: `EMAIL_MODO=noop` (autouse) y el único envío con SMTP falso
patchea `smtplib.SMTP_SSL`. Nunca se toca PROD (fixture `db` con `is_test_db_url`).
Correr con:
    docker exec box-crossfit-backend-1 python -m pytest tests/test_email_marca_contacto.py -q
"""
import email as email_lib
import email.header
import re
import smtplib
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                            # noqa: E402
from app.core.security import create_access_token               # noqa: E402
from app.services import email_service                          # noqa: E402
from app.utils.santiago import SANTIAGO                         # noqa: E402

TENANT_ID = 1
NOMBRE = "Ana Pérez"
WHATSAPP_BOX = "+56 9 1111 2222"
WHATSAPP_LINK = "https://wa.me/56911112222"
# La ventana de un beneficio es un INSTANTE (columna timestamptz): se lee con la TZ chilena.
VIGENTE_HASTA = datetime(2026, 10, 31, 23, 59, tzinfo=SANTIAGO)
# Entidades HTML que NO pueden aparecer en un asunto (el bug del "est&aacute;").
ENTIDAD_HTML = re.compile(r"&(?:[a-zA-Z]+|#\d+);")

# Los correos al ALUMNO que arma `email_service` con el template compartido. Una entrada por
# correo: si mañana alguien agrega uno con su propio encabezado, el test lo tiene que ver.
RENDERS_AL_ALUMNO = (
    ("vencimiento", lambda: email_service.render_email_vencimiento_plan(
        NOMBRE, "Plan 12", date(2026, 10, 5))),
    ("inactividad", lambda: email_service.render_email_fidelizacion(NOMBRE, 20)),
    ("inactividad_temprana", lambda: email_service.render_email_fidelizacion_temprana(NOMBRE, 10)),
    ("inactividad_larga", lambda: email_service.render_email_fidelizacion_larga(NOMBRE, 40)),
    ("inactividad_larga_sin_plan", lambda: email_service.render_email_fidelizacion_larga(
        NOMBRE, 40, True)),
    ("riesgo_alto", lambda: email_service.render_email_riesgo_alto(NOMBRE, 45)),
    ("beneficio_descuento", lambda: email_service.render_email_beneficio(
        NOMBRE, "descuento", 25, VIGENTE_HASTA, "Plan 12")),
    ("beneficio_clases", lambda: email_service.render_email_beneficio(
        NOMBRE, "clases_gratis", 2, VIGENTE_HASTA, "Plan 12")),
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    """NINGÚN test de este módulo manda correo de verdad (queda registrado `simulado`)."""
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado, nunca PROD)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    """TestClient de la app real (sin levantar servidor)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def tokens(db):
    """Token del admin REAL del box TEST (PUT /configuracion es sólo admin)."""
    from sqlalchemy import text
    fila = db.execute(text(
        "SELECT id, correo FROM usuarios WHERE tenant_id = :t AND rol = 'administrador' "
        "AND estado = 'activo' ORDER BY id LIMIT 1"), {"t": TENANT_ID}).first()
    if fila is None:
        pytest.skip("TEST no tiene un administrador activo")
    token = create_access_token({
        "usuario_id": int(fila[0]), "tenant_id": TENANT_ID,
        "rol": "administrador", "correo": fila[1] or "admin@test.com"})
    return {"admin": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def config_del_box(db, cliente, tokens):
    """La fila de `configuracion_negocio` del box: se escribe por la API y se RESTAURA.

    Devuelve `guardar(numero)` (el PUT del admin) y `leer()` (el GET público que ve el alumno).
    El teardown deja la fila como estaba, pase lo que pase.
    """
    def _leer():
        r = cliente.get(f"/api/v1/configuracion?tenant_id={TENANT_ID}")
        assert r.status_code == 200, r.text
        return r.json()

    def _guardar(numero):
        r = cliente.put("/api/v1/configuracion", json={"whatsapp": numero},
                        headers=tokens["admin"])
        assert r.status_code == 200, r.text
        return r.json()

    original = _leer().get("whatsapp")
    yield {"original": original, "guardar": _guardar, "leer": _leer}
    _guardar(original or "")


@pytest.fixture
def alumno_temp(db):
    """Un alumno TEMPORAL del box TEST (el pie del correo necesita un alumno real).

    `_tenant_de_alumno` resuelve el box por el alumno, así que el test end-to-end necesita una
    fila de verdad. Se borra al terminar: no queda basura en la rama TEST.
    """
    from sqlalchemy import text
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    correo = f"marca.contacto.{sufijo}@test.local"
    alumno_id = db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                              estado, created_at)
        VALUES (:t, :r, 'Alumno Marca TEST', :c, 'x', 'alumno', true, 'activo', now())
        RETURNING id"""),
        {"t": TENANT_ID, "r": f"97{sufijo[-8:]}-5", "c": correo}).scalar()
    db.commit()
    yield {"id": int(alumno_id), "correo": correo}
    db.rollback()
    db.execute(text("DELETE FROM usuarios WHERE id = :i"), {"i": alumno_id})
    db.commit()


class SMTPFalso:
    """SMTP de mentira: captura el mensaje y nunca sale a la red."""

    ultimo = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, *args, **kwargs):
        return None

    def send_message(self, msg):
        type(self).ultimo = msg


def _texto_de_html(html):
    """El html sin etiquetas (para buscar frases del copy sin que las parta un <strong>)."""
    return re.sub(r"<[^>]+>", " ", html)


# ══════════════════════════════════════════════════════════════════════════════
# A. El encabezado (logo del gorila, una sola definición)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_el_encabezado_es_el_logo_por_url_publica():
    """Logo del gorila: archivo real del repo servido por la web, 160 px, con alt y respaldo."""
    url = email_service.url_logo_email()
    encabezado = email_service.encabezado_marca()

    assert url.endswith("/imgs/logo.png"), f"la ruta pública del logo cambió: {url}"
    assert url.startswith("http"), f"el logo tiene que ser una URL absoluta: {url}"
    assert f'src="{url}"' in encabezado
    assert 'alt="Urban Training Box"' in encabezado, "sin alt, el correo sin imágenes no dice nada"
    assert 'width="160"' in encabezado, "el logo va a 160 px de ancho"
    assert "URBAN TRAINING BOX" in encabezado, "el nombre tiene que estar en TEXTO debajo del logo"
    # Ni base64 ni `cid:`: eso era lo que Gmail/Outlook bloqueaba (el correo llegaba sin logo).
    for prohibido in ("base64", "data:image", "cid:"):
        assert prohibido not in encabezado, f"el logo volvió a viajar como {prohibido}"


def test_a2_el_encabezado_viejo_no_esta_copiado_en_ningun_modulo():
    """Una sola definición: nadie puede volver a pegar un encabezado propio en otro módulo."""
    archivos = sorted((BACKEND / "app").rglob("*.py"))
    assert archivos, "no se encontró el código de la app"
    textos = {a: a.read_text(encoding="utf-8", errors="replace") for a in archivos}

    viejo = "URBAN" + "<br>"
    copias = [a.name for a, t in textos.items() if viejo in t]
    assert not copias, f"el encabezado viejo (h1 de texto) volvió a copiarse en: {copias}"

    definiciones = [a.name for a, t in textos.items() if "def encabezado_marca" in t]
    assert definiciones == ["email_service.py"], (
        f"el encabezado tiene que definirse una sola vez, y está en: {definiciones}")


@pytest.mark.parametrize("etiqueta,render", RENDERS_AL_ALUMNO, ids=[e for e, _ in RENDERS_AL_ALUMNO])
def test_a3_todos_los_correos_llevan_el_mismo_encabezado(etiqueta, render):
    """Cada correo al alumno lleva EXACTAMENTE el encabezado de marca (y una sola vez)."""
    _, html = render()
    encabezado = email_service.encabezado_marca()

    assert html.count(encabezado) == 1, f"{etiqueta}: el encabezado falta o está repetido"
    assert email_service.url_logo_email() in html, f"{etiqueta}: el correo salió sin el logo"


@pytest.mark.parametrize("etiqueta,render", RENDERS_AL_ALUMNO, ids=[e for e, _ in RENDERS_AL_ALUMNO])
def test_a4_los_asuntos_son_texto_plano(etiqueta, render):
    """El asunto no puede llevar entidades HTML y tiene que sobrevivir al encoding del header."""
    from email.message import EmailMessage

    asunto, _ = render()

    assert not ENTIDAD_HTML.search(asunto), f"{etiqueta}: el asunto tiene entidades HTML: {asunto!r}"
    # Round-trip real: lo que armaría `_enviar` y lo que termina leyendo el cliente.
    msg = EmailMessage()
    msg["Subject"] = asunto
    crudo = email_lib.message_from_string(msg.as_string())
    partes = email_lib.header.decode_header(crudo["Subject"])
    legible = "".join(p.decode(enc or "ascii") if isinstance(p, bytes) else p for p, enc in partes)
    assert legible == asunto, f"{etiqueta}: el asunto llega distinto: {legible!r}"


def test_a5_el_asunto_de_vencimiento_dice_esta_con_acento():
    """El bug reportado (Tu plan X est&aacute; por vencer) queda cubierto explícitamente."""
    asunto, _ = email_service.render_email_vencimiento_plan(NOMBRE, "Plan 12", date(2026, 10, 5))
    assert "está por vencer" in asunto
    assert "&aacute;" not in asunto


def test_a6_la_cta_invita_a_volver_y_no_a_coordinar_con_el_coach():
    """El correo lo manda el BOX: la acción es volver a entrenar, no hablar con alguien."""
    _, riesgo = email_service.render_email_riesgo_alto(NOMBRE, 45)
    _, larga = email_service.render_email_fidelizacion_larga(NOMBRE, 40)
    _, larga_sin_plan = email_service.render_email_fidelizacion_larga(NOMBRE, 40, True)

    for etiqueta, html in (("riesgo", riesgo), ("larga", larga)):
        plano = _texto_de_html(html).lower()
        assert "coach" not in plano, f"{etiqueta}: el correo le pide al alumno hablar con el coach"
        assert "coordinar" not in plano, f"{etiqueta}: 'coordinar' no es una acción concreta"
        assert "Reservar mi clase" in html, f"{etiqueta}: falta el botón para reservar en la app"
        assert "/alumno/mis-reservas" in html, f"{etiqueta}: el botón no lleva a reservar"

    # Sin plan vigente, el botón lleva a activar uno (no al calendario de reservas).
    assert "Activar mi plan" in larga_sin_plan and "/alumno/solicitar-plan" in larga_sin_plan
    assert "Reservar mi clase" not in larga_sin_plan


@pytest.mark.parametrize("numero,esperado", [
    ("+56 9 1234 5678", "https://wa.me/56912345678"),
    ("56912345678", "https://wa.me/56912345678"),
    ("9 1234 5678", "https://wa.me/56912345678"),        # sin código de país -> +56
    ("(9) 1234-5678", "https://wa.me/56912345678"),
    ("", ""), (None, ""), ("no tengo numero", ""), ("123", ""),
])
def test_a7_wa_link_normaliza_el_numero(numero, esperado):
    assert email_service.wa_link(numero) == esperado


def test_a8_sin_whatsapp_el_pie_ofrece_responder_el_correo():
    """Un box sin número cargado no puede prometer un canal: queda 'responde este correo'."""
    bloque = email_service.bloque_contacto(None)

    assert email_service.CONTACTO_FALLBACK in bloque
    assert "wa.me" not in bloque and "http" not in bloque


def test_a9_el_template_deja_el_placeholder_y_render_lo_resuelve():
    """El template es de todos los tenants: el contacto se resuelve recién al armar el correo."""
    html = email_service._template("Título", "Hola", "Cuerpo", "Botón", "https://x.cl")

    assert email_service.PLACEHOLDER_CONTACTO in html, "el template tiene que dejar el hueco"
    resuelto = email_service.render_con_contacto(html, None)
    assert email_service.PLACEHOLDER_CONTACTO not in resuelto, "quedó el placeholder a la vista"
    assert email_service.CONTACTO_FALLBACK in resuelto
    # Idempotente y sin tocar la BD cuando no hay placeholder.
    assert email_service.render_con_contacto(resuelto, None) == resuelto
    assert email_service.render_con_contacto("<p>x</p>", TENANT_ID) == "<p>x</p>"


# ══════════════════════════════════════════════════════════════════════════════
# B. El contacto del box contra TEST (escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
def test_b1_el_whatsapp_del_box_sale_de_la_configuracion(config_del_box):
    """Lo que el admin carga en Configuración es el WhatsApp que llevan los correos."""
    guardado = config_del_box["guardar"](WHATSAPP_BOX)

    assert guardado["whatsapp"] == WHATSAPP_BOX
    assert config_del_box["leer"]()["whatsapp"] == WHATSAPP_BOX
    assert email_service.contacto_del_box(TENANT_ID) == WHATSAPP_BOX
    # Y el pie del correo lo lleva con el link listo para clickear.
    bloque = email_service.bloque_contacto(TENANT_ID)
    assert WHATSAPP_LINK in bloque
    assert WHATSAPP_BOX in bloque, "el número tiene que verse tal como lo escribió el box"


def test_b2_un_whatsapp_vacio_no_promete_canal(config_del_box):
    """Un WhatsApp vacío es 'sin canal' (NULL en la BD), no un teléfono en blanco."""
    config_del_box["guardar"]("")

    assert config_del_box["leer"]()["whatsapp"] is None
    assert email_service.contacto_del_box(TENANT_ID) == ""
    bloque = email_service.bloque_contacto(TENANT_ID)
    assert email_service.CONTACTO_FALLBACK in bloque
    assert "wa.me" not in bloque


def test_b3_el_correo_que_sale_lleva_el_whatsapp_y_el_asunto_con_acentos(
        alumno_temp, config_del_box, monkeypatch):
    """End-to-end del envío (SMTP falso): sin placeholder, con el WhatsApp y el asunto legible."""
    config_del_box["guardar"](WHATSAPP_BOX)
    SMTPFalso.ultimo = None
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPFalso)
    monkeypatch.setattr(email_service, "_registrar_envio", lambda *a, **k: None)
    # Este es el ÚNICO test del módulo que arma el mensaje de verdad (y sale a un SMTP falso).
    # El camino real sólo existe EN PRODUCCIÓN: fuera de prod el fail-safe fuerza `noop`.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_REAL)

    asunto, html = email_service.render_email_vencimiento_plan(NOMBRE, "Plan 12", date(2026, 10, 5))
    ok = email_service.enviar_renderizado(alumno_temp["correo"], asunto, html,
                                          alumno_id=alumno_temp["id"], tipo="vencimiento")
    assert ok is True, "el envío falló: %r" % (email_service.ULTIMO_ERROR_SMTP,)
    enviado = SMTPFalso.ultimo
    assert enviado is not None, "el correo no se armó"

    cuerpo_html = enviado.get_body(preferencelist=("html",)).get_content()
    assert email_service.PLACEHOLDER_CONTACTO not in cuerpo_html
    assert WHATSAPP_LINK in cuerpo_html, "el correo salió sin el WhatsApp del box"
    assert email_service.url_logo_email() in cuerpo_html, "el correo salió sin el logo"

    crudo = email_lib.message_from_string(enviado.as_string())
    partes = email_lib.header.decode_header(crudo["Subject"])
    legible = "".join(p.decode(enc or "ascii") if isinstance(p, bytes) else p for p, enc in partes)
    assert legible == asunto and "está por vencer" in legible
