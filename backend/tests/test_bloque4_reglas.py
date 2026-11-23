"""Reglas unitarias del Bloque 4 (sin BD)."""
import sys
from datetime import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1.horarios import (  # noqa: E402
    _validar_cruce_coach,
    _validar_solapamiento_horario,
)
from app.api.v1.usuarios import _normalizar_nombre_coach  # noqa: E402
from app.models.usuario import RolUsuario  # noqa: E402


class _Query:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def all(self):
        return self._filas


class _DB:
    def __init__(self, filas):
        self._filas = filas

    def query(self, *args, **kwargs):
        return _Query(self._filas)


def _disc(nombre="CrossFit", requiere=True, open_box=False):
    return SimpleNamespace(id=1, nombre=nombre, requiere_coach=requiere,
                           es_open_box=open_box)


def _horario(inicio, fin):
    return SimpleNamespace(hora_inicio=inicio, hora_fin=fin)


def _coach_row(horario_id, coach_id, dia, inicio, fin, disciplina,
               vigente_hasta=None, activo=True):
    """Fila (HorarioCoach, HorarioBase, Disciplina) de la consulta de cruce."""
    return (
        SimpleNamespace(coach_id=coach_id, horario_id=horario_id,
                        vigente_hasta=vigente_hasta),
        SimpleNamespace(id=horario_id, dia_semana=dia, hora_inicio=inicio,
                        hora_fin=fin, activo=activo),
        disciplina,
    )


def test_solapamiento_estricto_con_misma_sala_y_coach():
    db = _DB([_horario(time(10), time(11))])
    with pytest.raises(HTTPException) as exc:
        _validar_solapamiento_horario(
            db, 1, _disc(), 1, "10:30", "11:30")
    assert exc.value.status_code == 409
    assert "CrossFit 10:00-11:00" in exc.value.detail


def test_huecos_y_bordes_no_se_consideran_solapamiento():
    db = _DB([_horario(time(10), time(11))])
    _validar_solapamiento_horario(db, 1, _disc(), 1, "11:00", "12:00")
    _validar_solapamiento_horario(db, 1, _disc(), 1, "09:00", "10:00")


@pytest.mark.parametrize("nombre", ["Musculación", "Open Box", "Levantamiento Olímpico"])
def test_disciplinas_sin_validacion_no_chocan(nombre):
    db = _DB([_horario(time(10), time(11))])
    _validar_solapamiento_horario(
        db, 1, _disc(nombre=nombre, open_box=nombre == "Open Box"),
        1, "10:15", "10:45")


def test_solo_valida_disciplinas_con_coach():
    db = _DB([_horario(time(10), time(11))])
    _validar_solapamiento_horario(
        db, 1, _disc(requiere=False), 1, "10:15", "10:45")


def test_normaliza_nombre_de_coach_y_respeta_demo():
    assert _normalizar_nombre_coach(
        "  juan   pérez ", RolUsuario.coach) == "Juan Pérez"
    assert _normalizar_nombre_coach(
        "coach demo", RolUsuario.coach, correo="demo@box.cl") == "coach demo"
    assert _normalizar_nombre_coach(
        "alumna ejemplo", RolUsuario.alumno) == "alumna ejemplo"


# ══════════════════════════════════════════════════════════════════════════════
# Cruce de coach ENTRE disciplinas (mismo coach, salas distintas)
# ══════════════════════════════════════════════════════════════════════════════
def test_cruce_de_coach_choca_entre_disciplinas_y_salas_distintas():
    """El mismo coach no puede dictar CrossFit y Gap a la misma hora."""
    db = _DB([_coach_row(204, 7, 1, time(10), time(11), _disc("CrossFit"))])

    with pytest.raises(HTTPException) as exc:
        _validar_cruce_coach(db, 1, 7, _disc("Gap"), 1, "10:30", "11:30")

    assert exc.value.status_code == 409
    # El mensaje dice QUÉ clase choca y a qué hora.
    assert "CrossFit 10:00-11:00" in exc.value.detail


def test_cruce_de_coach_sin_choque_permite_huecos_y_otro_dia():
    """Tocarse (11:00) no es pisarse, y otro día no cruza."""
    db = _DB([_coach_row(204, 7, 1, time(10), time(11), _disc("CrossFit"))])

    _validar_cruce_coach(db, 1, 7, _disc("Gap"), 1, "11:00", "12:00")
    _validar_cruce_coach(db, 1, 7, _disc("Gap"), 2, "10:00", "11:00")


def test_musculacion_con_coach_distinto_a_la_misma_hora_no_choca():
    """Musculación es de acceso libre: otro coach puede estar en paralelo."""
    musculacion = _disc("Musculación", requiere=False, open_box=True)
    db = _DB([_coach_row(205, 8, 1, time(10), time(11), musculacion)])

    _validar_cruce_coach(db, 1, 9, _disc("CrossFit"), 1, "10:15", "10:45")


def test_musculacion_del_mismo_coach_queda_fuera_del_cruce():
    """La disciplina sin coach no genera cruce aunque tenga coach en la fila."""
    musculacion = _disc("Musculación", requiere=False, open_box=True)
    db = _DB([_coach_row(205, 7, 1, time(10), time(11), musculacion)])

    _validar_cruce_coach(db, 1, 7, _disc("CrossFit"), 1, "10:15", "10:45")


def test_levantamiento_olimpico_queda_fuera_del_cruce_temporalmente():
    """EXCLUSIÓN TEMPORAL: Levantamiento Olímpico puede coincidir por ahora."""
    levantamiento = _disc("Levantamiento Olímpico")
    db = _DB([_coach_row(206, 7, 1, time(10), time(11), levantamiento)])

    # Ni como disciplina que ya tiene el coach...
    _validar_cruce_coach(db, 1, 7, _disc("CrossFit"), 1, "10:15", "10:45")
    # ... ni como disciplina nueva que se está asignando.
    _validar_cruce_coach(db, 1, 7, levantamiento, 1, "10:15", "10:45")


def test_cruce_ignora_la_propia_plantilla_y_las_vigencias_vencidas():
    """Una clase no choca con su propio horario ni con un coach ya liberado."""
    from datetime import date

    db = _DB([_coach_row(204, 7, 1, time(10), time(11), _disc("CrossFit"))])
    _validar_cruce_coach(db, 1, 7, _disc("Gap"), 1, "10:30", "11:30",
                         excluir_horario_id=204)

    vencida = _DB([_coach_row(204, 7, 1, time(10), time(11), _disc("CrossFit"),
                              vigente_hasta=date(2020, 1, 1))])
    _validar_cruce_coach(vencida, 1, 7, _disc("Gap"), 1, "10:30", "11:30")

