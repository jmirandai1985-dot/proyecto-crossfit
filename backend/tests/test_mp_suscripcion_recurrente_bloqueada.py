"""El COBRO AUTOMÁTICO de Mercado Pago (preapproval) está APAGADO por defecto.

Decisión de negocio 2026-11-26
------------------------------
`POST /api/v1/pagos/suscripcion` crea un `preapproval`: el alumno autoriza que
Mercado Pago le cobre SOLO todos los meses. La ruta y el código se conservan (no
se borra nada), pero la función queda detrás de la bandera
`MP_SUSCRIPCION_RECURRENTE_HABILITADA`, APAGADA por defecto (fail-closed).

QUÉ FIJA ESTE ARCHIVO (sin base y sin red)
  1. la bandera está apagada si la variable no existe o no tiene un valor explícito;
  2. con la bandera apagada, `crear_suscripcion_mp` responde 503 ANTES de tocar la
     base o Mercado Pago (no nace una fila `pendiente` ni un `preapproval`);
  3. la ruta real `POST /pagos/suscripcion` no puede iniciar un cobro automático.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_mp_suscripcion_recurrente_bloqueada.py -q
"""
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import suscripciones_mp  # noqa: E402


class _DbProhibida:
    """Sesión trampa: si el servicio la toca, el test falla.

    La bandera tiene que evaluarse ANTES de cualquier consulta o escritura; tocar
    la base con la bandera apagada sería justamente el bug que este archivo frena.
    """

    def __getattr__(self, nombre):
        raise AssertionError(
            f"la base se tocó ({nombre}) antes de revisar la bandera del cobro automático")


def test_la_bandera_esta_apagada_por_defecto(monkeypatch):
    monkeypatch.delenv(suscripciones_mp.BANDERA_RECURRENTE, raising=False)
    assert suscripciones_mp.suscripcion_recurrente_habilitada() is False
    for valor in ("", "0", "false", "no", "apagado", "off"):
        monkeypatch.setenv(suscripciones_mp.BANDERA_RECURRENTE, valor)
        assert suscripciones_mp.suscripcion_recurrente_habilitada() is False, valor


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", " si ", "yes", "on"])
def test_la_bandera_solo_se_enciende_con_un_valor_explicito(monkeypatch, valor):
    monkeypatch.setenv(suscripciones_mp.BANDERA_RECURRENTE, valor)
    assert suscripciones_mp.suscripcion_recurrente_habilitada() is True


def test_crear_suscripcion_mp_frena_antes_de_la_base_y_de_mp(monkeypatch):
    monkeypatch.delenv(suscripciones_mp.BANDERA_RECURRENTE, raising=False)

    with pytest.raises(suscripciones_mp.ErrorSuscripcion) as error:
        suscripciones_mp.crear_suscripcion_mp(
            _DbProhibida(),
            current_user={"usuario_id": 2, "tenant_id": 1, "rol": "alumno"},
            plan_id=1,
        )

    assert error.value.status_code == 503
    assert error.value.detalle == suscripciones_mp.MENSAJE_RECURRENTE_APAGADA


def test_la_ruta_no_puede_iniciar_un_cobro_automatico(monkeypatch):
    monkeypatch.delenv(suscripciones_mp.BANDERA_RECURRENTE, raising=False)

    from fastapi.testclient import TestClient

    from app.core.dependencies import require_full_access
    from app.db.database import get_db
    from app.main import app

    app.dependency_overrides[require_full_access] = lambda: {
        "usuario_id": 2, "tenant_id": 1, "rol": "alumno"}
    app.dependency_overrides[get_db] = lambda: _DbProhibida()
    try:
        respuesta = TestClient(app).post("/api/v1/pagos/suscripcion",
                                         json={"plan_id": 1})
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == suscripciones_mp.MENSAJE_RECURRENTE_APAGADA
