"""Reglas PURAS de los tramos del invitador (Parte C).

Sin BD, sin HTTP y sin correo: se fijan las decisiones que mueven dinero y que
no necesitan infraestructura para probarse.

  · con 3 referidos y una escalera 1/2/3 se aplica UN premio: el MÁS ALTO
    (la exclusividad que la Fase 5 no tenía);
  · un tramo apagado no compite;
  · la ventana del ciclo se recorta con la compra anticipada (una conversión no
    se cuenta dos veces);
  · Pydantic valida el valor del premio con la MISMA regla que las promociones.

    py -3.12 -m pytest tests/test_tramos_referidos_unit.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.referidos import (MotorPremiosUpdate,        # noqa: E402
                                   TramoReferidoCreate)
from app.services import tramos_referidos_service as svc      # noqa: E402


# ── Exclusividad: un solo premio, el más alto ───────────────────────────────
ESCALERA = [
    {"umbral_referidos": 1, "tipo_premio": "descuento_extra",
     "valor_premio": 15, "activo": True},
    {"umbral_referidos": 2, "tipo_premio": "descuento_extra",
     "valor_premio": 30, "activo": True},
    {"umbral_referidos": 3, "tipo_premio": "mes_gratis",
     "valor_premio": None, "activo": True},
]


def test_tres_referidos_devuelven_el_tramo_mas_alto_y_no_los_tres():
    tramo = svc.umbral_mas_alto(3, ESCALERA)

    assert tramo is not None
    assert tramo["umbral_referidos"] == 3
    assert tramo["tipo_premio"] == "mes_gratis"


@pytest.mark.parametrize("convertidos,esperado", [
    (1, 1), (2, 2), (3, 3), (4, 3), (99, 3),
])
def test_el_tramo_es_el_escalon_alcanzado_mas_alto(convertidos, esperado):
    assert svc.umbral_mas_alto(convertidos, ESCALERA)["umbral_referidos"] == esperado


def test_sin_referidos_no_hay_tramo():
    assert svc.umbral_mas_alto(0, ESCALERA) is None


def test_un_tramo_apagado_no_compite():
    escalera = [
        {"umbral_referidos": 1, "tipo_premio": "descuento_extra",
         "valor_premio": 15, "activo": True},
        {"umbral_referidos": 3, "tipo_premio": "mes_gratis",
         "valor_premio": None, "activo": False},
    ]

    assert svc.umbral_mas_alto(3, escalera)["umbral_referidos"] == 1


# ── Ventana del ciclo (compras anticipadas) ─────────────────────────────────
def test_ventana_sin_suscripcion_posterior_es_el_ciclo_completo():
    assert svc.ventana_efectiva(date(2026, 9, 12), date(2026, 10, 11)) == \
        (date(2026, 9, 12), date(2026, 10, 11))


def test_ventana_se_corta_en_el_inicio_de_la_siguiente_suscripcion():
    """Compró antes de vencer: el día de la nueva compra es del ciclo nuevo."""
    assert svc.ventana_efectiva(
        date(2026, 9, 12), date(2026, 10, 11), date(2026, 10, 1)) == \
        (date(2026, 9, 12), date(2026, 10, 1))


def test_una_suscripcion_posterior_al_cierre_no_alarga_la_ventana():
    assert svc.ventana_efectiva(
        date(2026, 9, 12), date(2026, 10, 11), date(2026, 10, 20)) == \
        (date(2026, 9, 12), date(2026, 10, 11))


# ── Texto de la escalera y avisos ───────────────────────────────────────────
def test_texto_de_la_escalera_ordena_por_umbral_y_usa_la_frase_del_premio():
    textos = svc.texto_escalera(list(reversed(ESCALERA)))

    assert textos[0] == "1 referido = 15 % de descuento extra"
    assert textos[2] == "3 referidos = 1 mes gratis (30 días)"


def test_escalera_que_premia_menos_arriba_genera_aviso():
    escalera = [
        {"umbral_referidos": 1, "tipo_premio": "descuento_extra",
         "valor_premio": 30, "activo": True},
        {"umbral_referidos": 2, "tipo_premio": "descuento_extra",
         "valor_premio": 10, "activo": True},
    ]

    avisos = svc.advertencias_escalera(escalera)

    assert len(avisos) == 1
    assert "2 referidos" in avisos[0]


def test_escalera_creciente_no_genera_avisos():
    assert svc.advertencias_escalera(ESCALERA) == []


# ── Validación del valor del premio (Pydantic) ──────────────────────────────
def test_mes_gratis_normaliza_el_valor_a_none():
    datos = TramoReferidoCreate(umbral_referidos=3, tipo_premio="mes_gratis",
                                valor_premio=30)

    assert datos.valor_premio is None


def test_descuento_extra_valido_se_conserva():
    datos = TramoReferidoCreate(umbral_referidos=1,
                                tipo_premio="descuento_extra",
                                valor_premio=15)

    assert float(datos.valor_premio) == 15.0


@pytest.mark.parametrize("tipo_premio,valor_premio", [
    ("descuento_extra", 0),
    ("descuento_extra", 101),
    ("dias_gratis", 0),
    ("dias_gratis", 2.5),
    ("descuento_extra", None),
])
def test_valor_de_premio_invalido_no_llega_a_la_bd(tipo_premio, valor_premio):
    with pytest.raises(ValidationError):
        TramoReferidoCreate(umbral_referidos=1, tipo_premio=tipo_premio,
                            valor_premio=valor_premio)


def test_umbral_cero_es_invalido():
    with pytest.raises(ValidationError):
        TramoReferidoCreate(umbral_referidos=0, tipo_premio="mes_gratis")


def test_campo_desconocido_en_el_cuerpo_es_rechazado():
    with pytest.raises(ValidationError):
        TramoReferidoCreate(umbral_referidos=1, tipo_premio="mes_gratis",
                            premio_envenenado=1)


# ── Selector de motor ───────────────────────────────────────────────────────
@pytest.mark.parametrize("motor", ["promociones", "tramos"])
def test_motor_valido(motor):
    assert MotorPremiosUpdate(motor_premios=motor).motor_premios == motor


@pytest.mark.parametrize("motor", ["", "ambos", "TRAMOS", "otro"])
def test_motor_invalido(motor):
    with pytest.raises(ValidationError):
        MotorPremiosUpdate(motor_premios=motor)
