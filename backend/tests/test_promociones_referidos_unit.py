"""Reglas PURAS de promociones por volumen de referidos (Fase 5).

Sin BD, sin HTTP y sin correo: se fijan las decisiones que no dependen de la
infraestructura y que, si cambian, cambian el dinero de un premio:

  · el período mensual es el de CHILE (un referido del 30/09 23:00 CLT no cae
    en octubre);
  · `mes_gratis` son 30 días y `dias_gratis` exige un entero > 0;
  · el texto del premio es el mismo en panel, campana y correo;
  · Pydantic normaliza/valida el valor según el tipo ANTES de tocar la BD;
  · publicar en el carrusel (migración 056) es una TARJETA vinculada: el
    serializer no inventa título/texto/fijado cuando la promoción no está
    publicada y el cuerpo de publicación no puede fijar `tipo` ni `promocion_id`.

    py -3.12 -m pytest tests/test_promociones_referidos_unit.py -q --noconftest
"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.referidos import (PromocionReferidosCreate,      # noqa: E402
                                   PublicarPromocionRequest)
from app.services import promociones_referidos_service as svc     # noqa: E402


# ── Período mensual chileno ─────────────────────────────────────────────────
def test_periodo_usa_el_dia_de_chile_no_el_de_utc():
    """23:00 del 30/09 en Chile sigue siendo SEPTIEMBRE, no octubre."""
    ultimo_de_sep = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
    primero_de_oct = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)

    assert svc.periodo_de(ultimo_de_sep) == "2026-09"
    assert svc.periodo_de(primero_de_oct) == "2026-10"


def test_rango_de_periodo_termina_al_inicio_del_mes_siguiente():
    desde, hasta = svc.rango_periodo("2026-10")

    assert desde.isoformat().startswith("2026-10-01T00:00:00")
    assert hasta.isoformat().startswith("2026-11-01T00:00:00")
    # Diciembre no explota al calcular el año siguiente.
    desde_dic, hasta_dic = svc.rango_periodo("2026-12")
    assert desde_dic.year == 2026 and hasta_dic.year == 2027


@pytest.mark.parametrize("periodo", ["2026-13", "2026-00", "octubre", ""])
def test_rango_de_periodo_invalido_falla(periodo):
    with pytest.raises(ValueError):
        svc.rango_periodo(periodo)


# ── Días y texto del premio ──────────────────────────────────────────────────
def test_mes_gratis_son_30_dias():
    assert svc.dias_de_extension("mes_gratis") == 30


def test_dias_gratis_exige_entero_positivo():
    assert svc.dias_de_extension("dias_gratis", "7") == 7
    assert svc.dias_de_extension("dias_gratis", 1) == 1
    for invalido in (0, -1, "1.5", None):
        with pytest.raises(ValueError):
            svc.dias_de_extension("dias_gratis", invalido)


def test_descuento_extra_no_extiende_suscripcion():
    with pytest.raises(ValueError):
        svc.dias_de_extension("descuento_extra", 10)


def test_texto_del_premio_es_el_mismo_en_todos_los_canales():
    assert svc.texto_premio("mes_gratis") == "1 mes gratis (30 días)"
    assert svc.texto_premio("dias_gratis", 1) == "1 día gratis"
    assert svc.texto_premio("dias_gratis", 7) == "7 días gratis"
    assert svc.texto_premio("descuento_extra", "12.50") == "12,5 % de descuento extra"


def test_mensaje_de_la_campana_dice_quien_que_y_donde_confirmar():
    mensaje = svc._mensaje_notificacion({
        "alumno_nombre": "Ana Pérez",
        "umbral_referidos_convertidos": 3,
        "periodo_cumplido": "2026-10",
        "nombre_promocion": "3 referidos = mes gratis",
        "premio_texto": "1 mes gratis (30 días)",
    })
    assert "Ana Pérez" in mensaje
    assert "3 referidos" in mensaje
    assert "Marketing → Referidos" in mensaje


# ── Validación del cuerpo (Pydantic) ────────────────────────────────────────
def test_mes_gratis_normaliza_el_valor_a_none():
    datos = PromocionReferidosCreate(
        nombre="  3 referidos = mes gratis  ",
        umbral_referidos_convertidos=3,
        tipo_premio="mes_gratis",
        valor_premio="99",
    )
    assert datos.nombre == "3 referidos = mes gratis"
    assert datos.valor_premio is None


def test_dias_gratis_rechaza_decimal_y_cero():
    for valor in ("1.5", "0"):
        with pytest.raises(ValidationError):
            PromocionReferidosCreate(
                nombre="Días", umbral_referidos_convertidos=3,
                tipo_premio="dias_gratis", valor_premio=valor)


def test_descuento_extra_exige_porcentaje_mayor_que_cero():
    ok = PromocionReferidosCreate(
        nombre="Extra", umbral_referidos_convertidos=3,
        tipo_premio="descuento_extra", valor_premio="15.5")
    assert str(ok.valor_premio) == "15.5"

    for valor in ("0", "100.01", "12.345"):
        with pytest.raises(ValidationError):
            PromocionReferidosCreate(
                nombre="Extra", umbral_referidos_convertidos=3,
                tipo_premio="descuento_extra", valor_premio=valor)


def test_tipo_sin_valor_obligatorio_falla():
    with pytest.raises(ValidationError):
        PromocionReferidosCreate(
            nombre="Días", umbral_referidos_convertidos=3,
            tipo_premio="dias_gratis")


def test_nombre_en_blanco_y_umbral_invalido_fallan():
    with pytest.raises(ValidationError):
        PromocionReferidosCreate(
            nombre="   ", umbral_referidos_convertidos=3,
            tipo_premio="mes_gratis")
    with pytest.raises(ValidationError):
        PromocionReferidosCreate(
            nombre="Promo", umbral_referidos_convertidos=0,
            tipo_premio="mes_gratis")


# ── Publicación en el carrusel (migración 056) ──────────────────────────────
def _promo(**extra):
    """Fila mínima de `promociones_referidos` para el serializer (sin BD)."""
    base = dict(id=7, nombre="3 referidos = mes gratis",
                umbral_referidos_convertidos=3, periodo="mensual",
                tipo_premio="mes_gratis", valor_premio=None, activo=True)
    base.update(extra)
    return SimpleNamespace(**base)


def test_sin_aviso_la_promocion_no_esta_publicada():
    fila = svc.serializar_promocion(_promo())

    assert fila["publicada"] is False
    assert fila["aviso_id"] is None
    assert fila["publicada_desde"] is None
    assert fila["publicada_hasta"] is None
    # El modal precarga `publicada_*`: con None sabe que debe sugerir el texto.
    assert fila["publicada_titulo"] is None
    assert fila["publicada_texto"] is None
    assert fila["publicada_fijado_arriba"] is False


def test_con_aviso_la_fila_trae_lo_que_dice_la_tarjeta():
    aviso = SimpleNamespace(
        id=41, titulo="3 referidos = 1 mes gratis",
        texto="Trae 3 amigos este mes y te regalamos 30 días.",
        fijado_arriba=True,
        vigente_desde=datetime(2026, 10, 1, tzinfo=timezone.utc),
        vigente_hasta=datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc))

    fila = svc.serializar_promocion(_promo(), 2, aviso)

    assert fila["publicada"] is True
    assert fila["aviso_id"] == 41
    assert fila["publicada_titulo"] == aviso.titulo
    assert fila["publicada_texto"] == aviso.texto
    assert fila["publicada_fijado_arriba"] is True
    assert fila["publicada_desde"] == aviso.vigente_desde
    assert fila["publicada_hasta"] == aviso.vigente_hasta
    # Los datos del premio no cambian por publicar.
    assert fila["premio_texto"] == "1 mes gratis (30 días)"
    assert fila["detecciones_pendientes"] == 2


def test_el_cuerpo_de_publicacion_recorta_y_no_acepta_tipo():
    datos = PublicarPromocionRequest(
        titulo="  3 referidos = mes gratis  ",
        texto="  Trae 3 amigos.  ",
        vigente_desde=date(2026, 10, 1), vigente_hasta=date(2026, 10, 31))

    assert datos.titulo == "3 referidos = mes gratis"
    assert datos.texto == "Trae 3 amigos."
    # Sin dato, la tarjeta NO se fija arriba (el default tiene que ser seguro).
    assert datos.fijado_arriba is False

    # `tipo` y `promocion_id` los fija el backend desde la URL: si el cliente los
    # manda, se rechaza en vez de ignorarlos en silencio.
    with pytest.raises(ValidationError):
        PublicarPromocionRequest(
            titulo="Tarjeta", texto="Texto", vigente_desde=date(2026, 10, 1),
            vigente_hasta=date(2026, 10, 31), tipo="evento")


@pytest.mark.parametrize("campo", ["titulo", "texto"])
def test_texto_en_blanco_no_es_un_texto(campo):
    cuerpo = {"titulo": "Tarjeta", "texto": "Texto",
              "vigente_desde": date(2026, 10, 1),
              "vigente_hasta": date(2026, 10, 31)}
    cuerpo[campo] = "   "
    with pytest.raises(ValidationError):
        PublicarPromocionRequest(**cuerpo)


def test_la_ventana_de_la_tarjeta_no_puede_estar_invertida():
    """Misma regla que Marketing: el modal no puede publicar un aviso ya vencido."""
    with pytest.raises(ValidationError):
        PublicarPromocionRequest(
            titulo="Tarjeta", texto="Texto", vigente_desde=date(2026, 10, 31),
            vigente_hasta=date(2026, 10, 1))
    # El último día de la ventana sí es válido (una tarjeta de UN día).
    un_dia = PublicarPromocionRequest(
        titulo="Tarjeta", texto="Texto", vigente_desde=date(2026, 10, 1),
        vigente_hasta=date(2026, 10, 1))
    assert un_dia.vigente_desde == un_dia.vigente_hasta


def test_un_aviso_vinculado_no_se_convierte_en_otro_tipo():
    """La tarjeta de la promoción no puede pasar a Evento desde Marketing: el
    vínculo (`promocion_id`) seguiría apuntando a la promoción y el panel diría
    "publicada" con otra cosa en el carrusel."""
    from app.services import avisos_marketing as avisos_svc

    aviso = SimpleNamespace(promocion_id=7)
    with pytest.raises(ValueError) as error:
        avisos_svc.actualizar(None, aviso, {
            "tipo": "evento", "titulo": "Cumpleaños del box",
            "texto": "Ven a celebrar", "vigente_desde": date(2026, 10, 1),
            "vigente_hasta": date(2026, 10, 2),
            "fecha_evento": date(2026, 10, 2)})

    assert "despublica" in str(error.value)


def test_los_topos_del_titulo_y_del_texto_son_los_del_aviso():
    with pytest.raises(ValidationError):
        PublicarPromocionRequest(
            titulo="x" * 151, texto="Texto", vigente_desde=date(2026, 10, 1),
            vigente_hasta=date(2026, 10, 31))
    with pytest.raises(ValidationError):
        PublicarPromocionRequest(
            titulo="Tarjeta", texto="x" * 1001,
            vigente_desde=date(2026, 10, 1),
            vigente_hasta=date(2026, 10, 31))

