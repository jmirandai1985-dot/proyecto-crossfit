"""Fechas de calendario: Reportes y el panel del coach usan el helper de CHILE.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. `Reportes.jsx`: el mes/año con el que se pide el Excel de ventas sale de
     `hoyChileStr()` (calendario chileno), no de `new Date()` del navegador: la última
     noche del mes, un navegador en otra zona pedía el reporte del mes siguiente.
  B. El panel del coach NO decide la clase "en curso" con el reloj del navegador: el estado
     lo pone el backend (`estado == "en_curso"`, hora de Chile) y se lee desde
     `utils/franjasAsistencia`, la única definición compartida. (Ese cálculo vivía en
     `GestionClases.jsx`, retirada por completo.)
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


def test_b_el_panel_del_coach_no_calcula_la_clase_en_curso_con_el_reloj_del_navegador():
    """La clase "en curso" la decide el BACKEND (`estado == "en_curso"`, hora de Chile) y el
    front sólo la lee. Ese cálculo vivía en `GestionClases.jsx` (retirada por completo); ahora
    el estado sale de `utils/franjasAsistencia`, la única definición compartida."""
    franjas = _fuente("frontend/src/utils/franjasAsistencia.js")
    assert "clase?.estado === 'en_curso'" in franjas
    assert "getHours()" not in franjas and "horaChileStr" not in franjas, (
        "el corte por franja es puro: no lee ni el reloj del navegador ni el de Chile")
    assert "from '../utils/franjasAsistencia'" in _fuente("frontend/src/components/ResumenCoach.jsx")
    for pantalla in ("frontend/src/pages/coach/DashboardCoach.jsx",
                     "frontend/src/components/ResumenCoach.jsx"):
        assert "getHours()" not in _fuente(pantalla), (
            f"{pantalla}: la clase en curso no puede compararse contra el reloj del navegador")


def test_c_el_helper_de_chile_exporta_lo_que_estas_pantallas_importan():
    fuente = _fuente("frontend/src/utils/fecha.js")
    for funcion in ("hoyChileStr", "toChileFechaStr", "horaChileStr", "fmtFechaChile"):
        assert f"export function {funcion}(" in fuente
