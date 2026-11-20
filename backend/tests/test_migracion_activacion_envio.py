"""Envío masivo del correo de activación (`POST .../activacion/enviar`) — AISLADO.

SIN BD y SIN red: app mínima con el router REAL, `get_db` falsa y los helpers de
consulta monkeypatcheados (mismo patrón que `test_migracion_candidato_edicion.py`).
Cubre:
  * sólo se manda a los Activos con correo (omite los que no tienen email);
  * el token se guarda SOLO como hash sha256 del que viaja en el link;
  * un candidato con token vigente no recibe un segundo correo (idempotencia);
  * un envío fallido invalida el token y NO marca `correo_migracion_enviado_en`;
  * `{enviados, fallidos, omitidos, total}` cuadra;
  * la primera corrida con enviados > 0 guarda `migracion_completada_en`, y una
    segunda corrida NO pisa la fecha existente;
  * 403 para un usuario que no es admin.

    cd backend && py -3.12 -m pytest tests/test_migracion_activacion_envio.py -q --noconftest
"""
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import migracion_boxmagic  # noqa: E402
from app.core.dependencies import (  # noqa: E402
    get_current_admin, get_current_user, get_db,
)
from app.models.candidato_boxmagic import CandidatoBoxmagic  # noqa: E402
from app.models.configuracion import ConfiguracionNegocio  # noqa: E402
from app.models.token_migracion_boxmagic import TokenMigracionBoxmagic  # noqa: E402
from app.services import email_service  # noqa: E402

TENANT = 1
ADMIN_ID = 7
RUTA = "/api/v1/migracion-boxmagic/activacion/enviar"


class _ConsultaConfig:
    def __init__(self, config):
        self._config = config

    def filter(self, *criterios):
        return self

    def first(self):
        return self._config


class _SesionFalsa:
    """Sólo lo que toca el endpoint: config y la cola de `add`/`commit`."""

    def __init__(self, config=None):
        self.config = config
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, modelo):
        if modelo is ConfiguracionNegocio:
            return _ConsultaConfig(self.config)
        return _ConsultaConfig(None)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        pass


def _candidato(id_, nombre, correo, estado="Activo"):
    return CandidatoBoxmagic(
        id=id_, tenant_id=TENANT, nombre=nombre, correo=correo,
        estado_boxmagic=estado, grupo="activacion",
    )


async def _admin_falso():
    return {"usuario_id": ADMIN_ID, "tenant_id": TENANT, "rol": "admin"}


def _cliente(sesion, rol="admin"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(migracion_boxmagic.router,
                       prefix="/api/v1/migracion-boxmagic")
    app.dependency_overrides[get_db] = lambda: sesion
    if rol == "admin":
        app.dependency_overrides[get_current_admin] = _admin_falso
    else:
        async def _no_admin():
            return {"usuario_id": 1, "tenant_id": TENANT, "rol": rol}
        app.dependency_overrides[get_current_user] = _no_admin
    return TestClient(app)


def _sin_espera(monkeypatch):
    monkeypatch.setattr(email_service, "espaciar_envio", lambda *a, **k: 0.0)


def _preparar(monkeypatch, candidatos, con_token=None, enviar_ok=None,
              config=None, sesion=None):
    sesion = sesion or _SesionFalsa(config=config)
    monkeypatch.setattr(migracion_boxmagic, "_candidatos_activos",
                        lambda db, tenant: candidatos)
    monkeypatch.setattr(migracion_boxmagic, "_ids_con_token_vigente",
                        lambda db, ahora: set(con_token or ()))
    monkeypatch.setattr(migracion_boxmagic, "url_frontend",
                        lambda path: "https://app.test" + path)

    enviados = {}

    def _enviar_falso(candidato, link):
        enviados[candidato["correo"]] = link
        if enviar_ok is None:
            return True
        return bool(enviar_ok(candidato["correo"]))

    monkeypatch.setattr(email_service, "enviar_email_migracion_boxmagic",
                        _enviar_falso)
    _sin_espera(monkeypatch)
    return sesion, enviados


def test_envia_solo_a_los_que_tienen_correo_y_cuadra_los_conteos(monkeypatch):
    candidatos = [
        _candidato(1, "Ana", "ana@test.com"),
        _candidato(2, "Beto", "beto@test.com"),
        _candidato(3, "Sin Correo", ""),
        _candidato(4, "Ya Tiene Token", "token@test.com"),
    ]
    sesion, enviados = _preparar(monkeypatch, candidatos, con_token=[4])

    r = _cliente(sesion).post(RUTA)

    assert r.status_code == 200, r.text
    assert r.json() == {"enviados": 2, "fallidos": 0, "omitidos": 2, "total": 4}
    assert set(enviados) == {"ana@test.com", "beto@test.com"}
    assert candidatos[0].correo_migracion_enviado_en is not None
    assert candidatos[1].correo_migracion_enviado_en is not None
    assert candidatos[2].correo_migracion_enviado_en is None
    assert candidatos[3].correo_migracion_enviado_en is None


def test_guarda_solo_el_hash_del_token_que_viaja_en_el_link(monkeypatch):
    candidato = _candidato(11, "Ana", "ana@test.com")
    sesion, enviados = _preparar(monkeypatch, [candidato])

    r = _cliente(sesion).post(RUTA)

    assert r.status_code == 200, r.text
    link = enviados["ana@test.com"]
    token = link.split("token=", 1)[1]
    assert link.startswith("https://app.test/migracion/activar?token=")

    filas = [o for o in sesion.added
             if isinstance(o, TokenMigracionBoxmagic)]
    assert len(filas) == 1
    esperado = hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert filas[0].token_hash == esperado
    assert token not in filas[0].token_hash
    assert filas[0].used_at is None
    assert filas[0].expires_at > datetime.now(timezone.utc)


def test_envio_fallido_invalida_el_token_y_no_marca_al_candidato(monkeypatch):
    candidato = _candidato(21, "Falla", "falla@test.com")
    sesion, _ = _preparar(
        monkeypatch, [candidato], enviar_ok=lambda correo: False)

    r = _cliente(sesion).post(RUTA)

    assert r.status_code == 200, r.text
    assert r.json() == {"enviados": 0, "fallidos": 1, "omitidos": 0, "total": 1}
    assert candidato.correo_migracion_enviado_en is None
    filas = [o for o in sesion.added
             if isinstance(o, TokenMigracionBoxmagic)]
    assert len(filas) == 1
    # Un token vigente de un envío fallido bloquearía el reintento: queda usado.
    assert filas[0].used_at is not None


def test_primera_corrida_guarda_la_fecha_del_box(monkeypatch):
    config = ConfiguracionNegocio(tenant_id=TENANT)
    sesion, _ = _preparar(
        monkeypatch, [_candidato(31, "Ana", "ana@test.com")], config=config)

    r = _cliente(sesion).post(RUTA)

    assert r.status_code == 200, r.text
    assert config.migracion_completada_en is not None


def test_si_ya_hay_fecha_no_se_pisa(monkeypatch):
    anterior = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
    config = ConfiguracionNegocio(tenant_id=TENANT,
                                  migracion_completada_en=anterior)
    sesion, _ = _preparar(
        monkeypatch, [_candidato(41, "Ana", "ana@test.com")], config=config)

    r = _cliente(sesion).post(RUTA)

    assert r.status_code == 200, r.text
    assert config.migracion_completada_en == anterior


def test_sin_enviados_no_marca_la_migracion(monkeypatch):
    config = ConfiguracionNegocio(tenant_id=TENANT)
    sesion, _ = _preparar(
        monkeypatch, [_candidato(51, "Sin Correo", "")], config=config)

    r = _cliente(sesion).post(RUTA)

    assert r.status_code == 200, r.text
    assert r.json()["enviados"] == 0
    assert config.migracion_completada_en is None


@pytest.mark.parametrize("rol", ["alumno", "coach"])
def test_no_admin_403(monkeypatch, rol):
    sesion, _ = _preparar(
        monkeypatch, [_candidato(61, "Ana", "ana@test.com")])

    r = _cliente(sesion, rol=rol).post(RUTA)

    assert r.status_code == 403, r.text
