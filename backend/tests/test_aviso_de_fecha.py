"""
La ventana del aviso del archivo semanal (Bloque D) — `payload_aviso_de_fecha`.

POR QUÉ ES PURO: acá se decide CUÁNDO lo ve el alumnado, que es la parte del aviso que no
se puede equivocar (un aviso del miércoles que se ve el martes es un aviso perdido). La
ventana sale de `rango_vigencia` — la MISMA del aviso rápido y del panel del admin—, así que
este test lo que fija es que un día se traduce en su día de Chile completo, sin lógica de
fechas nueva.
"""
from datetime import date

from app.services.avisos_marketing import (TIPO_AVISO, payload_aviso_de_fecha,
                                           payload_aviso_rapido)
from app.utils.santiago import SANTIAGO


def test_el_aviso_dura_su_dia_completo_en_chile():
    """00:00:00 del día → 23:59:59 del mismo día, en hora de Chile."""
    dia = date(2026, 10, 14)                       # miércoles
    datos = payload_aviso_de_fecha("Trae calcetas", dia)

    assert datos["vigente_desde"] == datos["vigente_hasta"].replace(
        hour=0, minute=0, second=0)
    assert datos["vigente_desde"].astimezone(SANTIAGO).date() == dia
    assert datos["vigente_hasta"].astimezone(SANTIAGO).date() == dia
    assert (datos["vigente_hasta"] - datos["vigente_desde"]).total_seconds() == 86399


def test_es_el_aviso_del_box_de_siempre_con_la_fecha_del_archivo():
    """Mismo tipo/flyer/título que el aviso rápido: sólo cambia el DÍA."""
    dia = date(2026, 10, 14)
    del_archivo = payload_aviso_de_fecha("Trae calcetas. Hay cuerda", dia)
    de_hoy = payload_aviso_rapido("Trae calcetas. Hay cuerda")

    assert del_archivo["tipo"] == TIPO_AVISO == de_hoy["tipo"]
    assert del_archivo["titulo"] == de_hoy["titulo"] == "Trae calcetas"
    assert del_archivo["imagen_url"] is None and del_archivo["fijado_arriba"] is False
    assert del_archivo["vigente_desde"] != de_hoy["vigente_desde"]
