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

from app.api.v1.horarios import _validar_solapamiento_horario  # noqa: E402
from app.api.v1.usuarios import _normalizar_nombre_coach  # noqa: E402
from app.models.usuario import RolUsuario  # noqa: E402


class _Query:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *args, **kwargs):
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
