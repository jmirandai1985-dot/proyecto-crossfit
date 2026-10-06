"""Cálculos de "Mi historial" (T2) — puros, sin red y sin base de datos.

Qué fija este archivo:

  A. "alumno desde" = primera suscripción o primera asistencia (NUNCA el alta del usuario);
     el alta sólo decide cuando no hay ninguna de las dos (alumno recién creado).
  B. "promedio por semana" = asistencias / semanas REALES del período (desde "alumno desde"),
     con piso de 1 semana (no infla el número ni divide por 0).
  C. "racha (meses al 100%)" sólo cuenta meses COMPLETOS: la caminata arranca en el mes
     anterior, así que el mes en curso nunca suma.
  D. Casos borde: alumno nuevo (sin plan ni asistencia), meses sin plan y mes en curso.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_historial_calculos.py -q --noconftest
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import historial_alumno_service as svc      # noqa: E402


def _dt(anio, mes, dia):
    """`timestamptz` de la BD (UTC), como lo devuelve Postgres."""
    return datetime(anio, mes, dia, 12, 0, tzinfo=timezone.utc)


# ── A. "Alumno desde" ─────────────────────────────────────────────────────────
def test_a_alumno_nuevo_usa_su_alta():
    """Sin plan ni clases: el único dato es la creación del usuario."""
    assert svc.inicio_actividad(created_at=_dt(2026, 3, 1)) == (date(2026, 3, 1), "alta")


def test_a2_la_primera_suscripcion_manda_sobre_el_alta():
    """Alta en enero, activado en marzo: "alumno desde" = marzo, no enero."""
    assert svc.inicio_actividad(
        created_at=_dt(2026, 1, 5), primera_suscripcion=_dt(2026, 3, 1),
        primera_asistencia=None) == (date(2026, 3, 1), "suscripcion")


def test_a3_la_primera_asistencia_tambien_cuenta():
    assert svc.inicio_actividad(
        created_at=_dt(2026, 1, 5), primera_suscripcion=None,
        primera_asistencia=date(2026, 4, 2)) == (date(2026, 4, 2), "asistencia")


def test_a4_gana_la_mas_antigua():
    assert svc.inicio_actividad(
        primera_suscripcion=_dt(2026, 2, 1),
        primera_asistencia=date(2026, 3, 10)) == (date(2026, 2, 1), "suscripcion")
    assert svc.inicio_actividad(
        primera_suscripcion=_dt(2026, 3, 1),
        primera_asistencia=date(2026, 2, 10)) == (date(2026, 2, 10), "asistencia")


def test_a5_sin_datos_no_inventa_fecha():
    assert svc.inicio_actividad() == (None, None)


def test_a6_lee_el_instante_en_hora_de_chile():
    """2026-03-01 02:00 UTC = 2026-02-28 23:00 en Chile: el "desde" es el 28, no el 1."""
    assert svc.inicio_actividad(
        created_at=datetime(2026, 3, 1, 2, 0, tzinfo=timezone.utc)) == (date(2026, 2, 28), "alta")


# ── B. Promedio por semana ────────────────────────────────────────────────────
def test_b_semanas_reales_del_periodo():
    hoy, inicio = date(2026, 4, 9), date(2026, 3, 12)      # 28 días = 4 semanas exactas
    assert svc.promedio_semanal(4, inicio, hoy) == 1.0
    assert svc.promedio_semanal(2, inicio, hoy) == 0.5


def test_b2_piso_de_una_semana():
    hoy = date(2026, 4, 9)
    assert svc.promedio_semanal(3, hoy, hoy) == 3.0                       # empezó hoy
    assert svc.promedio_semanal(2, hoy - timedelta(days=3), hoy) == 2.0   # 3 días -> 1 semana


def test_b3_sin_inicio_es_cero():
    assert svc.promedio_semanal(5, None, date(2026, 4, 9)) == 0.0


def test_b4_no_usa_el_alta_del_usuario():
    """Regresión: antes se dividía por las semanas desde el ALTA (divisor inflado)."""
    hoy = date(2026, 4, 9)
    assert svc.promedio_semanal(8, date(2026, 3, 12), hoy) == 2.0     # 4 semanas reales
    assert svc.promedio_semanal(8, date(2025, 1, 1), hoy) == 0.1      # 15 meses (mal)


# ── C. Racha: sólo meses completos ────────────────────────────────────────────
def test_c_la_racha_arranca_en_el_mes_anterior():
    assert svc._mes_anterior(2026, 4) == (2026, 3)
    assert svc._mes_anterior(2026, 1) == (2025, 12)      # cruza el año


def test_c2_el_mes_en_curso_queda_fuera():
    hoy = date(2026, 4, 9)
    assert svc._mes_anterior(hoy.year, hoy.month) == (2026, 3)    # abril (en curso) no cuenta


# ── D. Meses sin plan ─────────────────────────────────────────────────────────
class _Sus:
    """Suscripción mínima con lo que usa `suscripcion_del_mes` (fechas tz-aware + estado)."""

    def __init__(self, ini, fin, estado="activo"):
        self.fecha_inicio = ini
        self.fecha_expiracion = fin
        self.estado = estado


def test_d_un_mes_en_el_hueco_queda_sin_plan():
    suscripciones = [
        _Sus(_dt(2026, 2, 1), _dt(2026, 2, 28)),      # mes de hace dos
        _Sus(_dt(2026, 4, 1), _dt(2026, 4, 30)),      # mes en curso
    ]
    assert svc.suscripcion_del_mes(suscripciones, 2026, 2) is not None
    assert svc.suscripcion_del_mes(suscripciones, 2026, 3) is None      # hueco -> sin plan
    assert svc.suscripcion_del_mes(suscripciones, 2026, 4) is not None


def test_d2_una_suscripcion_pendiente_no_es_mes_con_plan():
    pendiente = [_Sus(_dt(2026, 3, 1), _dt(2026, 3, 31), estado="pendiente")]
    assert svc.suscripcion_del_mes(pendiente, 2026, 3) is None
