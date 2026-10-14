"""
El archivo semanal del coach (Bloque D) — `app/services/wod_semana.py`.

POR QUÉ ES UN TEST PURO (sin API ni base de datos): el formato del .xlsx es una regla de
negocio cerrada —orden de columnas, qué es un archivo roto y qué cae en "Otro"— y no
necesita ni servidor ni rama TEST para probarse. Las planillas se arman EN MEMORIA con
openpyxl: este test no lee ni escribe ningún archivo de nadie.

Contrato que se fija acá:
  * 7 días válidos (con o sin fila de encabezado) → 7 días ordenados por fecha;
  * `wod_tipo`: "amrap " → AMRAP · "RFT" o vacío → Otro (el coach no rompe el archivo);
  * calentamiento / musculación / aviso vacíos → None (son opcionales);
  * celdas combinadas, fila vacía en el medio, fecha repetida, fecha ilegible, >7 días y
    WOD sin nombre/descripción → error explícito y NINGÚN día inventado;
  * `payloads_de_semana` mapea a los campos de la tabla (musculacion → fuerza_habilidad,
    descripción → wod_principal) y sale `estado = publicado`.
"""
from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.services.wod_semana import (MAX_DIAS, ArchivoInvalido, leer_archivo,
                                     normalizar_tipo, payloads_de_semana)

FILA_OK = [
    date(2026, 10, 13), "400m trote", "5x5 Back Squat", "Fran", "For Time",
    "21-15-9 Thrusters/Pull-ups", "Trae calcetas",
]


def _xlsx(filas, combinar=None) -> bytes:
    """Planilla en memoria (bytes), como la subiría el coach."""
    wb = Workbook()
    hoja = wb.active
    for fila in filas:
        hoja.append(list(fila))
    if combinar:
        hoja.merge_cells(combinar)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _semana(n=7):
    """`n` días seguidos desde el lunes 2026-10-19 (semana lunes→domingo)."""
    return [[date(2026, 10, 19 + i), None, None, f"WOD {i + 1}", "For Time",
             f"Bloque {i + 1}", None] for i in range(n)]


def test_siete_dias_validos_se_ordenan_por_fecha():
    """(1) El caso feliz: 7 filas → 7 días, ordenados aunque vengan desordenados."""
    dias, errores = leer_archivo(_xlsx(list(reversed(_semana()))))
    assert errores == []
    assert len(dias) == MAX_DIAS
    assert [d["fecha"] for d in dias] == sorted(d["fecha"] for d in dias)
    # La planilla venía al revés y el primer WOD es el del 19 (el de la fecha menor).
    assert dias[0]["fecha"] == date(2026, 10, 19)
    assert dias[0]["wod_nombre"] == "WOD 1"
    assert dias[0]["wod_tipo"] == "For Time"


def test_la_fila_de_encabezado_no_se_confunde_con_un_dia():
    """(2) Si la primera fila son los títulos, se saltea y no aparece como error."""
    filas = [["fecha", "calentamiento", "musculacion", "wod_nombre", "wod_tipo",
              "wod_descripcion", "aviso"]] + _semana(7)
    dias, errores = leer_archivo(_xlsx(filas))
    assert errores == []
    assert len(dias) == MAX_DIAS


def test_tipo_desconocido_o_vacio_cae_en_otro():
    """(3) El vocabulario: lo que no es For Time/AMRAP/EMOM cae en "Otro"."""
    assert normalizar_tipo("amrap ") == "AMRAP"
    assert normalizar_tipo("emom") == "EMOM"
    assert normalizar_tipo("For time") == "For Time"
    assert normalizar_tipo("RFT") == "Otro"
    assert normalizar_tipo("") == "Otro"
    assert normalizar_tipo(None) == "Otro"


def test_opcionales_vacios_no_rompen_y_quedan_en_none():
    """(4) Calentamiento, musculación y aviso son opcionales (celda vacía)."""
    dias, errores = leer_archivo(_xlsx([FILA_OK]))
    assert errores == []
    dia = dias[0]
    assert dia["calentamiento"] == "400m trote"
    assert dia["musculacion"] == "5x5 Back Squat"
    assert dia["aviso"] == "Trae calcetas"
    assert dia["wod_tipo"] == "For Time"

    dias, errores = leer_archivo(_xlsx([_semana(1)[0]]))
    assert errores == []
    assert dias[0]["calentamiento"] is None
    assert dias[0]["musculacion"] is None
    assert dias[0]["aviso"] is None


def test_celdas_combinadas_son_error():
    """(5) El mockup las prohíbe: no se puede leer bien un día partido en dos celdas."""
    _, errores = leer_archivo(_xlsx(_semana(3), combinar="A1:A2"))
    assert any("combinadas" in e for e in errores)


def test_fila_vacia_en_el_medio_es_error():
    """(6) Una fila en blanco no se saltea en silencio: se avisa."""
    filas = _semana(3)
    filas.insert(1, [None, None, None, None, None, None, None])
    dias, errores = leer_archivo(_xlsx(filas))
    assert any("vacía" in e for e in errores)
    assert len(dias) == 3, "los días buenos se programan igual (19, 20 y 21)"


def test_fecha_repetida_es_error():
    """(7) Dos filas para el mismo día: se avisa y no se programa dos veces."""
    filas = _semana(2)
    filas[1][0] = filas[0][0]
    dias, errores = leer_archivo(_xlsx(filas))
    assert any("repetida" in e for e in errores)
    assert len(dias) == 1


def test_fecha_ilegible_es_error():
    """(8) La fecha tiene que ser fecha de Excel o AAAA-MM-DD (y la fila mala no entra)."""
    filas = _semana(2)
    filas[1][0] = "lunes 20"
    dias, errores = leer_archivo(_xlsx(filas))
    assert any("fecha" in e.lower() for e in errores)
    assert len(dias) == 1, "sólo entra el día que sí tiene fecha legible"

    # La primera fila sin fecha legible se toma como ENCABEZADO (el mockup documenta las
    # columnas y mucha gente las pega igual): no es un día y se avisa que no hay datos.
    dias, errores = leer_archivo(_xlsx([["lunes 19", None, None, "WOD", "For Time",
                                        "bloque", None]]))
    assert dias == []
    assert any("fila" in e.lower() for e in errores)


def test_mas_de_siete_dias_no_programa_nada():
    """(9) 8 filas no son una semana: se rechaza el lote completo."""
    dias, errores = leer_archivo(_xlsx(_semana(8)))
    assert any("7" in e for e in errores)
    assert dias == []


def test_wod_sin_nombre_o_sin_descripcion_es_error():
    """(10) El WOD es lo mínimo que no puede faltar."""
    sin_nombre = _semana(1)
    sin_nombre[0][3] = None
    dias, errores = leer_archivo(_xlsx(sin_nombre))
    assert any("nombre" in e for e in errores)
    assert dias == []

    sin_desc = _semana(1)
    sin_desc[0][5] = "  "
    dias, errores = leer_archivo(_xlsx(sin_desc))
    assert any("descripción" in e for e in errores)
    assert dias == []


def test_archivo_que_no_es_xlsx():
    """(11) Un .csv renombrado no se lee "a medias": se rechaza de frente."""
    with pytest.raises(ArchivoInvalido):
        leer_archivo(b"fecha,calentamiento\n2026-10-13,400m")
    with pytest.raises(ArchivoInvalido):
        leer_archivo(b"")


def test_payloads_mapean_a_los_campos_de_la_tabla():
    """(12) El puente con la API de WODs: mismos campos que el formulario manual."""
    dias, _ = leer_archivo(_xlsx([FILA_OK]))
    payloads = payloads_de_semana(dias)
    assert len(payloads) == 1
    cuerpo = payloads[0]
    assert cuerpo["fecha"] == date(2026, 10, 13)
    assert cuerpo["titulo"] == "Fran"
    assert cuerpo["calentamiento"] == "400m trote"
    assert cuerpo["fuerza_habilidad"] == "5x5 Back Squat"      # musculacion
    assert cuerpo["wod_principal"] == "21-15-9 Thrusters/Pull-ups"
    assert cuerpo["tipo_metcon"] == "For Time"
    assert cuerpo["estado"] == "publicado"
