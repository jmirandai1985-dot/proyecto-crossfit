"""
Endpoints de REFERIDOS (Fase 3a) — tests AISLADOS, sin BD y sin red.

Qué se prueba
-------------
  * FORMATO de las tres respuestas: `mi-codigo`, `validar-codigo` y
    `configuracion` (claves exactas y tipos; los `Decimal` de la BD salen como
    `float` en el JSON).
  * Las REGLAS de `validar-codigo` que no necesitan BD: normalización del
    código y prioridad de los motivos (inexistente, inactivo, propio, ya
    referido). La consulta real a la BD y los permisos se cubren en
    `test_referidos_api.py`.
  * Los esquemas Pydantic: rango 0-100 de los porcentajes y `extra="forbid"`
    (el invitado no puede mandar un `usuario_id` ajeno).

    cd backend && py -3.12 -m pytest tests/test_referidos_api_unit.py -q
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.referidos import EstadoReferido
from app.schemas.referidos import (ConfiguracionReferidosOut,
                                   ConfiguracionReferidosUpdate, MiCodigoOut,
                                   ValidarCodigoOut, ValidarCodigoRequest)
from app.services import referidos_service as rs

AHORA = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


# ── Normalización ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada,esperado", [
    ("JPERE234", "JPERE234"),
    (" jpere234 ", "JPERE234"),
    ("\tJpeRe234\n", "JPERE234"),
    ("", ""),
    ("   ", ""),
    (None, ""),
])
def test_normalizar_codigo_ingresado(entrada, esperado):
    """El alumno escribe con espacios/minúsculas: se busca siempre normalizado."""
    assert rs.normalizar_codigo_ingresado(entrada) == esperado


# ── Prioridad de los motivos de rechazo ──────────────────────────────────────

@pytest.mark.parametrize("hechos,esperado", [
    # El código ni existe: no importa nada más.
    (dict(existe=False, activo=True, es_propio=True, ya_referido=True),
     rs.MOTIVO_CODIGO_INEXISTENTE),
    # Existe pero está apagado: gana sobre "propio"/"ya referido".
    (dict(existe=True, activo=False, es_propio=True, ya_referido=True),
     rs.MOTIVO_CODIGO_INACTIVO),
    # Anti-auto-referido.
    (dict(existe=True, activo=True, es_propio=True, ya_referido=False),
     rs.MOTIVO_CODIGO_PROPIO),
    # Un alumno sólo puede ser referido una vez.
    (dict(existe=True, activo=True, es_propio=False, ya_referido=True),
     rs.MOTIVO_YA_REFERIDO),
    # Válido: sin motivo.
    (dict(existe=True, activo=True, es_propio=False, ya_referido=False),
     None),
])
def test_motivo_codigo_invalido(hechos, esperado):
    assert rs.motivo_codigo_invalido(**hechos) == esperado


# ── Formato de `GET /mi-codigo` ──────────────────────────────────────────────

def test_datos_mi_codigo_formato():
    fila = SimpleNamespace(codigo="JPERE234", activo=True,
                           fecha_creacion=AHORA)
    datos = rs.datos_mi_codigo(fila)

    assert datos == {"codigo": "JPERE234", "activo": True,
                     "fecha_creacion": AHORA}
    assert MiCodigoOut(**datos).model_dump() == {
        "codigo": "JPERE234", "activo": True, "fecha_creacion": AHORA}


def test_datos_mi_codigo_no_expone_ids_internos():
    """El alumno no debe ver `usuario_id` ni el `id` de la fila."""
    datos = rs.datos_mi_codigo(SimpleNamespace(
        id=99, usuario_id=7, codigo="JPERE234", activo=False,
        fecha_creacion=AHORA))
    assert set(datos) == {"codigo", "activo", "fecha_creacion"}


# ── Formato de `POST /validar-codigo` ────────────────────────────────────────

def test_datos_referido_aplicado_formato():
    referido = SimpleNamespace(id=11, estado=EstadoReferido.pendiente)
    datos = rs.datos_referido_aplicado(referido, "JPERE234")

    assert datos == {
        "valido": True,
        "codigo": "JPERE234",
        "referido_id": 11,
        "estado": "pendiente",
        "mensaje": rs.MENSAJE_REFERIDO_REGISTRADO,
    }
    assert ValidarCodigoOut(**datos).model_dump()["estado"] == "pendiente"


def test_datos_referido_aplicado_acepta_estado_texto():
    """El estado puede venir como enum o como texto plano (mismo contrato)."""
    datos = rs.datos_referido_aplicado(
        SimpleNamespace(id=12, estado="convertido"), "ABC123")
    assert datos["estado"] == "convertido"


# ── Formato de `GET/PUT /configuracion` ─────────────────────────────────────

def test_datos_configuracion_sin_fila_devuelve_defaults():
    datos = rs.datos_configuracion(None)

    assert datos == {
        "porcentaje_descuento_invitado": 0.0,
        "porcentaje_descuento_invitador": 0.0,
        "activo": False,
        "configurada": False,
    }
    # Los defaults respetan el contrato de la respuesta (números, no strings).
    assert ConfiguracionReferidosOut(**datos).model_dump() == datos


def test_datos_configuracion_convierte_numeric_a_float():
    fila = SimpleNamespace(
        porcentaje_descuento_invitado=Decimal("5.50"),
        porcentaje_descuento_invitador=Decimal("10.00"),
        activo=True,
    )
    datos = rs.datos_configuracion(fila)

    assert datos == {
        "porcentaje_descuento_invitado": 5.5,
        "porcentaje_descuento_invitador": 10.0,
        "activo": True,
        "configurada": True,
    }
    assert isinstance(datos["porcentaje_descuento_invitado"], float)
    assert isinstance(datos["porcentaje_descuento_invitador"], float)


# ── Validación de los cuerpos ────────────────────────────────────────────────

@pytest.mark.parametrize("invitado,invitador", [
    (0, 0), (100, 100), ("12.34", "0.00"), (5, 10),
])
def test_configuracion_update_acepta_rango_0_100(invitado, invitador):
    datos = ConfiguracionReferidosUpdate(
        porcentaje_descuento_invitado=invitado,
        porcentaje_descuento_invitador=invitador,
        activo=True)
    assert datos.porcentaje_descuento_invitado == Decimal(str(invitado))
    assert datos.activo is True


@pytest.mark.parametrize("invalido", [-0.01, 100.01, -1, 101])
def test_configuracion_update_rechaza_fuera_de_rango(invalido):
    with pytest.raises(ValidationError):
        ConfiguracionReferidosUpdate(
            porcentaje_descuento_invitado=invalido,
            porcentaje_descuento_invitador=10,
            activo=True)


def test_configuracion_update_rechaza_mas_de_dos_decimales():
    with pytest.raises(ValidationError):
        ConfiguracionReferidosUpdate(
            porcentaje_descuento_invitado="1.234",
            porcentaje_descuento_invitador=10,
            activo=True)


def test_configuracion_update_exige_los_tres_campos():
    with pytest.raises(ValidationError):
        ConfiguracionReferidosUpdate(
            porcentaje_descuento_invitado=10,
            porcentaje_descuento_invitador=10)


def test_configuracion_update_no_acepta_campos_desconocidos():
    with pytest.raises(ValidationError):
        ConfiguracionReferidosUpdate(
            porcentaje_descuento_invitado=10,
            porcentaje_descuento_invitador=10,
            activo=True,
            tenant_id=2)


def test_validar_codigo_no_acepta_usuario_id_en_el_body():
    """El invitado sale SIEMPRE del token: mandar `usuario_id` es un 422."""
    with pytest.raises(ValidationError):
        ValidarCodigoRequest(codigo="JPERE234", usuario_id=999)


@pytest.mark.parametrize("codigo", ["", "X" * 21])
def test_validar_codigo_request_valida_largo(codigo):
    with pytest.raises(ValidationError):
        ValidarCodigoRequest(codigo=codigo)


def test_validar_codigo_request_acepta_el_codigo_normal():
    assert ValidarCodigoRequest(codigo="JPERE234").codigo == "JPERE234"
