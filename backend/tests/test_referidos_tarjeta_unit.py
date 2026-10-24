"""
La tarjeta FIJA del carrusel "Invita y Gana" (migración 058) — AISLADA, sin BD.

Qué se prueba
-------------
  * `datos_tarjeta` resuelve el copy EFECTIVO sin escribir nada: sin fila todo
    es default; con fila cada texto NULL o en blanco cae a SU default (campo por
    campo) y el texto guardado sale recortado.
  * `personalizada` cuenta TEXTOS propios, no `visible`: apagar la tarjeta no la
    vuelve "personalizada" y una fila que sólo apaga sigue heredando el copy.
  * El contrato Pydantic: `TarjetaReferidosOut` valida lo que devuelve el
    servicio, y `TarjetaReferidosUpdate` recorta, convierte el blanco en `None`
    (="usar el default"), exige `visible`, respeta los máximos de las columnas y
    prohíbe campos ajenos (`tenant_id`, `usuario_id`).
  * El PERMISO de las rutas se cuida por código: `GET /referidos/tarjeta` es
    `get_current_user` (el alumno del carrusel, incluso en plan de prueba) y
    `PUT /referidos/tarjeta` es `get_current_admin`. La integración real vive en
    `test_referidos_tarjeta_api.py`.

    cd backend && py -3.12 -m pytest tests/test_referidos_tarjeta_unit.py -q --noconftest
"""
from pathlib import Path
from types import SimpleNamespace
import re

import pytest
from pydantic import ValidationError

from app.models.referidos import TarjetaReferidos
from app.schemas.referidos import (TARJETA_CTA_MAX, TARJETA_TEXTO_MAX,
                                   TARJETA_TITULO_MAX, TarjetaReferidosOut,
                                   TarjetaReferidosUpdate)
from app.services import referidos_service as rs

RAIZ = Path(__file__).resolve().parents[1]
FUENTE_API = (RAIZ / "app" / "api" / "v1" / "referidos.py").read_text(
    encoding="utf-8-sig")

CAMPOS = ("titulo", "texto", "cta")
DEFAULTS = {
    "titulo": rs.TARJETA_REFERIDOS_TITULO,
    "texto": rs.TARJETA_REFERIDOS_TEXTO,
    "cta": rs.TARJETA_REFERIDOS_CTA,
}


# ── 1. `datos_tarjeta`: el copy efectivo ────────────────────────────────────

def test_sin_fila_el_copy_es_el_default():
    """Leer no crea filas: sin fila se responde el copy genérico, nada más."""
    datos = rs.datos_tarjeta(None)
    assert datos == {**DEFAULTS, "visible": True, "personalizada": False}


@pytest.mark.parametrize("campo,maximo", [
    ("titulo", TARJETA_TITULO_MAX),
    ("texto", TARJETA_TEXTO_MAX),
    ("cta", TARJETA_CTA_MAX),
])
def test_el_default_cabe_en_el_maximo_de_su_columna(campo, maximo):
    """Un default más largo que la columna reventaría al guardar el primer texto."""
    assert 0 < len(DEFAULTS[campo]) <= maximo


def test_el_default_no_es_un_texto_vacio():
    for campo in CAMPOS:
        assert DEFAULTS[campo].strip() == DEFAULTS[campo]
        assert DEFAULTS[campo], campo


def test_cada_campo_cae_a_su_default_por_separado():
    """Personalizar sólo el título NO congela el texto ni el botón."""
    datos = rs.datos_tarjeta(SimpleNamespace(
        titulo="Trae a tu parcero", texto=None, cta="   ", visible=True))

    assert datos["titulo"] == "Trae a tu parcero"
    assert datos["texto"] == rs.TARJETA_REFERIDOS_TEXTO
    assert datos["cta"] == rs.TARJETA_REFERIDOS_CTA
    assert datos["personalizada"] is True


def test_el_texto_guardado_se_devuelve_recortado():
    datos = rs.datos_tarjeta(SimpleNamespace(
        titulo="  Uno  ", texto="\n Dos \t", cta="Tres ", visible=True))

    assert (datos["titulo"], datos["texto"], datos["cta"]) == \
        ("Uno", "Dos", "Tres")


def test_visible_no_es_personalizacion():
    """Apagar la tarjeta no la vuelve "personalizada" (el chip del panel)."""
    datos = rs.datos_tarjeta(SimpleNamespace(
        titulo=None, texto=None, cta=None, visible=False))

    assert datos["visible"] is False
    assert datos["personalizada"] is False
    assert datos["titulo"] == rs.TARJETA_REFERIDOS_TITULO


def test_sin_atributo_visible_la_tarjeta_se_muestra():
    """Una fila vieja (sin la columna) no puede esconder la tarjeta del alumno."""
    datos = rs.datos_tarjeta(SimpleNamespace(titulo="Hola", texto=None, cta=None))
    assert datos["visible"] is True


def test_los_maximos_del_schema_coinciden_con_las_columnas():
    columnas = TarjetaReferidos.__table__.c
    assert columnas.titulo.type.length == TARJETA_TITULO_MAX
    assert columnas.texto.type.length == TARJETA_TEXTO_MAX
    assert columnas.cta.type.length == TARJETA_CTA_MAX
    # Los tres textos son NULL-ables: NULL = "usar el default de ese campo".
    for campo in CAMPOS:
        assert columnas[campo].nullable is True, campo
    assert columnas.visible.nullable is False


# ── 2. El contrato Pydantic ─────────────────────────────────────────────────

def test_out_valida_lo_que_devuelve_el_servicio():
    """`GET` nunca devuelve textos nulos: el alumno no conoce los defaults."""
    salida = TarjetaReferidosOut(**rs.datos_tarjeta(None)).model_dump()

    assert set(salida) == {"titulo", "texto", "cta", "visible", "personalizada"}
    for campo in CAMPOS:
        assert isinstance(salida[campo], str) and salida[campo]
    assert salida["visible"] is True
    assert salida["personalizada"] is False


def test_update_recorta_y_convierte_el_blanco_en_default():
    datos = TarjetaReferidosUpdate(
        titulo="  Trae a tu parcero  ", texto="   ", cta=None, visible=False)

    assert datos.titulo == "Trae a tu parcero"
    assert datos.texto is None       # blanco = "usar el default"
    assert datos.cta is None         # ausente = "usar el default"
    assert datos.visible is False


def test_update_exige_visible():
    """Apagar la tarjeta es una decisión explícita, nunca un efecto colateral."""
    with pytest.raises(ValidationError):
        TarjetaReferidosUpdate(titulo="Hola")


@pytest.mark.parametrize("campo,maximo", [
    ("titulo", TARJETA_TITULO_MAX),
    ("texto", TARJETA_TEXTO_MAX),
    ("cta", TARJETA_CTA_MAX),
])
def test_update_respeta_el_maximo_de_cada_campo(campo, maximo):
    justo = TarjetaReferidosUpdate(**{campo: "a" * maximo, "visible": True})
    assert len(getattr(justo, campo)) == maximo

    with pytest.raises(ValidationError):
        TarjetaReferidosUpdate(**{campo: "a" * (maximo + 1), "visible": True})


@pytest.mark.parametrize("ajeno", [
    {"tenant_id": 2},
    {"usuario_id": 7},
    {"id": 1},
    {"tipo": "referidos"},
])
def test_update_no_acepta_campos_ajenos(ajeno):
    """El box sale del token: el cuerpo no puede mover la fila a otro tenant."""
    with pytest.raises(ValidationError):
        TarjetaReferidosUpdate(visible=True, **ajeno)


# ── 3. Permisos de las rutas (por código, la BD se prueba aparte) ────────────

def _bloque_de_ruta(marcador: str) -> str:
    """El decorador + la función, hasta la ruta siguiente."""
    inicio = FUENTE_API.index(marcador)
    fin = FUENTE_API.find("@router.", inicio + len(marcador))
    return FUENTE_API[inicio:fin if fin != -1 else len(FUENTE_API)]


def _dependencias(bloque: str) -> list:
    """Los `Depends(...)` del bloque, en orden: es el candado de permisos."""
    return re.findall(r"Depends\(([^)]*)\)", bloque)


def test_get_tarjeta_es_para_cualquier_autenticado():
    bloque = _bloque_de_ruta('@router.get("/tarjeta"')

    # Sólo la sesión y el token: lo lee el Inicio del alumno, también en plan de
    # prueba (igual que `GET /marketing/vigentes`). Si alguien le agrega
    # `require_full_access` o `get_current_admin`, este test lo tiene que ver.
    assert _dependencias(bloque) == ["get_db", "get_current_user"]
    assert "require_full_access(" not in bloque


def test_put_tarjeta_es_solo_admin_y_usa_el_tenant_del_token():
    bloque = _bloque_de_ruta('@router.put("/tarjeta"')

    assert _dependencias(bloque) == ["get_db", "get_current_admin"]
    assert 'current_user["tenant_id"]' in bloque
    assert "datos.tenant_id" not in bloque
    for campo in CAMPOS + ("visible",):
        assert f"tarjeta.{campo} = " in bloque, campo
    assert "db.commit()" in bloque


def test_la_api_importa_el_modelo_y_los_esquemas_de_la_tarjeta():
    assert "TarjetaReferidos)" in FUENTE_API
    assert "TarjetaReferidosOut" in FUENTE_API
    assert "TarjetaReferidosUpdate" in FUENTE_API
