"""Estado VISIBLE de una reserva en "Mis Reservas" (`GET /reservas -> estado_visible`).

El rótulo que ve el alumno NO se calcula en el frontend: el backend expone
`estado_visible` reutilizando la MISMA función que el Historial del alumno
(`historial_alumno_service.estado_asistencia`). Así no vuelve a haber dos criterios
distintos para la misma reserva.

Tests AISLADOS: no tocan la BD, no modifican `reservas.estado`, ni los KPIs, ni las
consultas de reservas "vivas". Sólo clasifican objetos en memoria.

  clasificación backend   ->  rótulo en "Mis Reservas" (frontend)
  --------------------------------------------------------------
  falto                   ->  "No asistió"   (clase pasada sin asistencia)
  asistio                 ->  "Asistió"      (clase pasada con asistencia)
  reservada               ->  "Confirmada"   (clase futura)
  cancelada               ->  "Cancelada"
"""
from datetime import date, datetime, time
from types import SimpleNamespace

from app.services.historial_alumno_service import estado_asistencia
from app.utils.santiago import SANTIAGO


def _clase(fecha, hora_inicio, clase_id=1):
    return SimpleNamespace(id=clase_id, fecha=fecha, hora_inicio=hora_inicio,
                           hora_fin=hora_inicio, cancelada=False)


def _reserva(estado="confirmada", asistio=False, updated_at=None, reserva_id=9):
    return SimpleNamespace(
        id=reserva_id, estado=estado, asistio=asistio, updated_at=updated_at,
        tokens_gastados=1, tenant_id=1, clase_id=1, alumno_id=1,
        fecha_reserva=None, created_at=None,
    )


AHORA = datetime(2026, 3, 10, 12, 0, tzinfo=SANTIAGO)
PASADA = _clase(date(2026, 3, 9), time(19, 0))
FUTURA = _clase(date(2026, 3, 11), time(19, 0))


def test_clase_pasada_sin_asistencia_es_no_asistio():
    # Clase pasada + asistio=False => "falto" (la pantalla muestra "No asistió").
    assert estado_asistencia(_reserva(), PASADA, AHORA) == "falto"


def test_clase_pasada_con_asistencia_es_asistio():
    assert estado_asistencia(_reserva(asistio=True), PASADA, AHORA) == "asistio"


def test_clase_futura_es_reservada():
    assert estado_asistencia(_reserva(), FUTURA, AHORA) == "reservada"


def test_clase_cancelada_es_cancelada():
    # Cancelada con 10 h de margen: a tiempo (el crédito vuelve) => "cancelada".
    hace_10h = datetime(2026, 3, 9, 9, 0, tzinfo=AHORA.tzinfo)
    assert estado_asistencia(
        _reserva(estado="cancelled", updated_at=hace_10h), PASADA, AHORA) == "cancelada"


def test_item_reserva_expone_estado_visible_sin_tocar_estado():
    """`GET /reservas` arma cada fila con `_item_reserva`, que incluye `estado_visible`."""
    from app.api.v1.reservas import _item_reserva

    item = _item_reserva(_reserva(), PASADA, "CrossFit")
    assert item["estado_visible"] == "falto"
    # El estado CRUDO de la BD NO se reescribe: sigue siendo el que guardó el sistema.
    assert item["estado"] == "confirmada"
