"""Arranque más rápido (T7): la revisión del rango es UNA consulta agregada, no 2 por día.

Qué fija este archivo (puro, sin red y sin base de datos):

  A. `dias_incompletos` devuelve EXACTAMENTE las mismas fechas que el bucle día-a-día que
     reemplaza (mismo criterio `clases < horarios`, sin domingos) para varios escenarios.
  B. Los bordes: domingo siempre afuera, un día sin horarios nunca está incompleto, un rango
     completo no devuelve nada.
  C. `revisar_rango` arma los conteos con dos consultas agregadas (se comprueba con una
     sesión doble que simula el GROUP BY) y coincide con `dias_incompletos`.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_generar_clases_dias_incompletos.py -q --noconftest
"""
import sys
from datetime import date, timedelta
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import generar_clases as gc                       # noqa: E402


def _agregado(clases, horarios):
    """Conteos como los devolvería el GROUP BY: clases por fecha, horarios por día."""
    conteo_clases = {}
    for fecha, _hid in clases:
        conteo_clases[fecha] = conteo_clases.get(fecha, 0) + 1
    conteo_horarios = {}
    for ds, _hid in horarios:
        conteo_horarios[ds] = conteo_horarios.get(ds, 0) + 1
    return conteo_clases, conteo_horarios


def _naive(clases, horarios, desde, hasta):
    """El bucle día-a-día que se reemplazó (misma regla, contando en memoria)."""
    out = []
    f = desde
    while f <= hasta:
        if f.weekday() == 6:                 # domingo: no hay horarios base
            f += timedelta(days=1)
            continue
        n_clases = sum(1 for fecha, _ in clases if fecha == f)
        n_horarios = sum(1 for ds, _ in horarios if ds == f.weekday())
        if n_clases < n_horarios:
            out.append(f)
        f += timedelta(days=1)
    return out


def _lunes():
    """Un lunes cualquiera (los escenarios se anclan a un lunes para ser deterministas)."""
    d = date(2026, 4, 6)
    assert d.weekday() == 0
    return d


# ── A. Nuevo == viejo ─────────────────────────────────────────────────────────
def test_a_el_resultado_es_el_mismo_que_el_bucle_dia_a_dia():
    desde = _lunes()
    hasta = desde + timedelta(days=13)                       # 2 semanas
    # Horarios: 2 el lunes, 1 el miércoles y 1 el viernes (los demás días, 0).
    horarios = [(0, 1), (0, 2), (2, 3), (4, 4)]

    escenarios = [
        [],                                                  # sin clases: todo incompleto
        [(desde, 1), (desde, 2),                             # lunes completo
         (desde + timedelta(days=2), 3)],                    # miércoles completo
        [(desde, 1), (desde, 2), (desde + timedelta(days=2), 3),
         (desde + timedelta(days=4), 4),                     # primer viernes completo
         (desde + timedelta(days=6), 9)],                    # domingo (se ignora)
        [(desde, 1),                                         # lunes a medias (falta 1)
         (desde + timedelta(days=4), 4)],                    # viernes completo
    ]
    for clases in escenarios:
        conteo_clases, conteo_horarios = _agregado(clases, horarios)
        nuevo = gc.dias_incompletos(conteo_clases, conteo_horarios, desde, hasta)
        viejo = _naive(clases, horarios, desde, hasta)
        assert nuevo == viejo, (clases, nuevo, viejo)


# ── B. Bordes ─────────────────────────────────────────────────────────────────
def test_b_el_domingo_nunca_aparece():
    desde = _lunes()
    hasta = desde + timedelta(days=6)              # ... domingo (weekday 6)
    faltantes = gc.dias_incompletos({}, {}, desde, hasta)
    assert desde + timedelta(days=6) not in faltantes
    assert all(f.weekday() != 6 for f in faltantes)


def test_b2_un_dia_sin_horarios_no_esta_incompleto():
    desde = _lunes()
    # Sólo el lunes tiene horarios y no hay clases: el único incompleto es el lunes.
    faltantes = gc.dias_incompletos({}, {0: 3}, desde, desde + timedelta(days=6))
    assert faltantes == [desde]


def test_b3_rango_completo_no_devuelve_nada():
    desde = _lunes()
    hasta = desde + timedelta(days=6)
    # Sólo lunes/miércoles/viernes tienen horarios; los tres tienen sus clases.
    horarios = {0: 1, 2: 1, 4: 1}
    clases = {desde: 1, desde + timedelta(days=2): 1, desde + timedelta(days=4): 1}
    assert gc.dias_incompletos(clases, horarios, desde, hasta) == []


# ── C. revisar_rango con las consultas agregadas ───────────────────────────────
class _FakeQuery:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *a, **k):
        return self

    def group_by(self, *a, **k):
        return self

    def all(self):
        return self._filas


class _FakeDB:
    """Sesión que devuelve el GROUP BY de clases o de horarios según la columna pedida."""

    def __init__(self, filas_clases, filas_horarios):
        self._clases = filas_clases
        self._horarios = filas_horarios

    def query(self, *columnas):
        from app.models.clase import Clase
        from app.models.horario_base import HorarioBase

        if columnas[0] is Clase.fecha:
            return _FakeQuery(self._clases)
        if columnas[0] is HorarioBase.dia_semana:
            return _FakeQuery(self._horarios)
        raise AssertionError(f"columna inesperada: {columnas!r}")


def test_c_revisar_rango_arma_los_conteos_con_dos_consultas():
    desde = _lunes()
    hasta = desde + timedelta(days=6)
    # Una fecha con 1 clase y horarios: 2 el lunes, 1 el miércoles.
    db = _FakeDB([(desde, 1)], [(0, 2), (2, 1)])

    faltantes = gc.revisar_rango(db, tenant_id=1, fecha_desde=desde, fecha_hasta=hasta)

    # El lunes (1 < 2) está incompleto; el miércoles (0 < 1) también; el resto no.
    assert desde in faltantes
    assert desde + timedelta(days=2) in faltantes
    assert desde + timedelta(days=1) not in faltantes
    assert faltantes == gc.dias_incompletos({desde: 1}, {0: 2, 2: 1}, desde, hasta)

