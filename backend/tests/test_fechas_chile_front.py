"""Fechas de calendario: Reportes y Gestión de Clases usan el helper de CHILE.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. `Reportes.jsx`: el mes/año con el que se pide el Excel de ventas sale de
     `hoyChileStr()` (calendario chileno), no de `new Date()` del navegador: la última
     noche del mes, un navegador en otra zona pedía el reporte del mes siguiente.
  B. `GestionClases.jsx`: la clase "en curso" se calcula con `horaChileStr()` (hora de
     Chile) y no con `getHours()` del navegador.
  C. Ninguno de los dos usa `toISOString()` para fechas de calendario (el helper ya
     resuelve la zona), y el helper sigue exportando lo que importan.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_fechas_chile_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_reportes_pide_el_excel_con_el_mes_del_calendario_chileno():
    fuente = _fuente("frontend/src/pages/admin/Reportes.jsx")
    assert "import { hoyChileStr } from '../../utils/fecha'" in fuente
    assert "[anio, mes] = hoyChileStr().split('-').map(Number)" in fuente
    assert "const now = new Date();" not in fuente, (
        "el mes del reporte ya no puede salir del reloj del navegador")
    assert "toISOString" not in fuente
    # El nombre del archivo descargado sigue usando ese mes/año.
    assert "reporte_ventas_${mes.toString().padStart(2, '0')}_${anio}.xlsx" in fuente


def test_b_gestion_de_clases_calcula_la_clase_en_curso_con_hora_de_chile():
    fuente = _fuente("frontend/src/pages/coach/GestionClases.jsx")
    assert ("import { horaChileStr, hoyChileStr as hoyStr, "
            "toChileFechaStr as toLocalFechaStr } from '../../utils/fecha'") in fuente
    assert "horaChileStr().split(':')" in fuente
    assert "getHours()" not in fuente, (
        "la clase en curso no puede compararse contra el reloj del navegador")
    assert "hoyStr()" in fuente and "toLocalFechaStr(" in fuente


def test_c_el_helper_de_chile_exporta_lo_que_estas_pantallas_importan():
    fuente = _fuente("frontend/src/utils/fecha.js")
    for funcion in ("hoyChileStr", "toChileFechaStr", "horaChileStr", "fmtFechaChile"):
        assert f"export function {funcion}(" in fuente
