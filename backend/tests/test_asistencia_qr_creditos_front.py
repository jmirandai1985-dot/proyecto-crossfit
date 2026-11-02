"""Check-in por QR: la pantalla muestra los créditos restantes del alumno.

Guard de fuente (sin red y sin base): fija que el endpoint de check-in devuelve el
saldo de créditos (y la marca de plan ilimitado) y que la pantalla `AsistenciaQr`
lo pinta. No usa BD: sólo inspecciona el código.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_asistencia_qr_creditos_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ASISTENCIA = "backend/app/api/v1/asistencia.py"
QR = "frontend/src/pages/AsistenciaQr.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_el_checkin_devuelve_creditos_e_ilimitado():
    fuente = _fuente(ASISTENCIA)
    # El saldo de créditos y la marca de ilimitado van en las DOS ramas de éxito.
    assert fuente.count('"creditos": creditos') == 2
    assert fuente.count('"ilimitado": ilimitado') == 2
    # La marca de ilimitado sale del plan (es_ilimitado), no de un NULL suelto.
    assert "plan.es_ilimitado" in fuente


def test_la_pantalla_pinta_los_creditos_tras_el_checkin():
    fuente = _fuente(QR)
    assert "Créditos de clase restantes:" in fuente
    assert "Plan ilimitado: reserva las clases que quieras." in fuente
    assert "d.creditos" in fuente and "d.ilimitado" in fuente
