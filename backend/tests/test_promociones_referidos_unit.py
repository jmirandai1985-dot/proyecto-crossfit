"""Reglas PURAS de promociones por volumen de referidos (Fase 5).

Sin BD, sin HTTP y sin correo: se fijan las decisiones que no dependen de la
infraestructura y que, si cambian, cambian el dinero de un premio:

  · el período mensual es el de CHILE (un referido del 30/09 23:00 CLT no cae
    en octubre);
  · `mes_gratis` son 30 días y `dias_gratis` exige un entero > 0;
  · el texto del premio es el mismo en panel, campana y correo;
  · Pydantic normaliza/valida el valor según el tipo ANTES de tocar la BD.

    py -3.12 -m pytest tests/test_promociones_referidos_unit.py -q --noconftest
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.referidos import PromocionReferidosCreate       # noqa: E402
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
