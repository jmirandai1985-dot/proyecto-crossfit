"""Suspensión de plan: helpers puros que siguen vivos (sin BD).

El self-service del alumno se retiró junto con sus reglas puras (`ciclo_vigente`,
`dias_usados_en_ciclo`, `calcular_elegibilidad`, `puede_cancelar`, `suspension_activa`,
`motivo_suspension_activa`), así que acá sólo queda lo que usa la suspensión por
salud del admin:
  * `dias_entre` es INCLUSIVO (del 01 al 03 son 3 días).

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suspensiones_service.py -q
"""
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import suspensiones_service as svc          # noqa: E402


def test_dias_entre_inclusivo():
    # Del 01 al 03 son 3 días (inclusive), igual que antes.
    assert svc.dias_entre(date(2026, 10, 1), date(2026, 10, 3)) == 3
    assert svc.dias_entre(date(2026, 10, 1), date(2026, 10, 1)) == 1
    assert svc.dias_entre(date(2026, 10, 5), date(2026, 10, 8)) == 4
