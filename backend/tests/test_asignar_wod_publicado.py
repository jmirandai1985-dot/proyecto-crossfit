"""Asignar un WOD a una clase exige que el WOD esté PUBLICADO — aislado.

Sin BD ni red: app mínima con el router REAL de `wods.py`, una sesión falsa que
devuelve la clase y el WOD del escenario. Se fija que:

  * un WOD `draft` NO se puede asignar → 400 con el mensaje de negocio y la clase
    queda intacta (sin commit);
  * un WOD `publicado` sigue asignándose → 200 (control de no-regresión);
  * el endpoint batch (`/wods/batch`) aplica la misma regla (misma operación);
  * `POST /wods/batch-create` también rechaza un body con `estado="draft"` antes
    de crear el WOD o consultar/enlazar clases.

    cd backend && py -3.12 -m pytest tests/test_asignar_wod_publicado.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import wods as wods_api
from app.core.dependencies import get_current_coach, get_db
from app.models.clase import Clase
from app.models.wod import EstadoWod, Wod

TENANT = 1
CLASE_ID = 201
WOD_ID = 101
DETALLE = "No se puede asignar un WOD que no ha sido publicado"


class _Consulta:
    def __init__(self, fila):
        self._fila = fila

    def filter(self, *criterios, **kwargs):
        return self

    def first(self):
        return self._fila


class _SesionFalsa:
    """`query(Clase)` / `query(Wod)` devuelven el escenario; cuenta escrituras."""

    def __init__(self, clase, wod):
        self.clase = clase
        self.wod = wod
        self.commits = 0
        self.queries = []
        self.added = []

    def query(self, modelo=None, *args, **kwargs):
        self.queries.append(modelo)
        if modelo is Clase:
            return _Consulta(self.clase)
        if modelo is Wod:
            return _Consulta(self.wod)
        return _Consulta(None)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


def _cliente(sesion, rol="coach"):
    app = FastAPI()
    app.include_router(wods_api.router)
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[get_current_coach] = lambda: {
        "usuario_id": 7, "tenant_id": TENANT, "rol": rol,
        "correo": "coach@test.com", "activo": True, "estado": "activo",
    }
    return TestClient(app)


def _escenario(estado):
    clase = SimpleNamespace(id=CLASE_ID, tenant_id=TENANT, disciplina_id=None,
                            coach_id=None, wod_id=None, fecha="2026-11-13")
    wod = SimpleNamespace(id=WOD_ID, tenant_id=TENANT, estado=estado,
                          titulo="WOD de prueba")
    return _SesionFalsa(clase, wod)


def _asignar(cliente):
    return cliente.post(
        f"/api/v1/wods/clases/{CLASE_ID}/asignar-wod/{WOD_ID}")


def test_wod_draft_no_se_asigna_a_la_clase():
    sesion = _escenario(EstadoWod.draft)
    cliente = _cliente(sesion)

    r = _asignar(cliente)

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == DETALLE
    assert sesion.clase.wod_id is None, "un borrador no puede quedar enlazado"
    assert sesion.commits == 0, "no se persiste nada si la validación falla"


def test_wod_publicado_sigue_asignandose():
    sesion = _escenario(EstadoWod.publicado)
    cliente = _cliente(sesion)

    r = _asignar(cliente)

    assert r.status_code == 200, r.text
    assert r.json()["wod_id"] == WOD_ID
    assert sesion.clase.wod_id == WOD_ID
    assert sesion.commits == 1


def test_batch_tambien_rechaza_un_wod_draft():
    """`/wods/batch` es la otra vía de asignación: no puede saltarse la regla."""
    sesion = _escenario(EstadoWod.draft)
    cliente = _cliente(sesion)

    r = cliente.post("/api/v1/wods/batch",
                     json={"wod_id": WOD_ID, "clase_ids": [CLASE_ID]})

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == DETALLE
    assert sesion.clase.wod_id is None
    assert sesion.commits == 0


def test_batch_create_draft_no_crea_wod_ni_enlaza_clases():
    """El cuarto punto de entrada: crear+enlazar en una transacción."""
    sesion = _escenario(EstadoWod.draft)
    # Admin: evita la validación de disciplina del coach; el foco es el estado.
    cliente = _cliente(sesion, rol="administrador")

    r = cliente.post("/api/v1/wods/batch-create", json={
        "wods": [{
            "fecha": "2026-11-13",
            "titulo": "Borrador batch",
            "wod_principal": "21-15-9",
            "tipo_metcon": "FOR TIME",
            "estado": "draft",
        }],
    })

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == DETALLE
    assert sesion.added == [], "no se debe crear ningún WOD"
    assert sesion.queries == [], "la validación corta ANTES de consultar clases"
    assert sesion.clase.wod_id is None, "la clase queda intacta"
    assert sesion.commits == 0
