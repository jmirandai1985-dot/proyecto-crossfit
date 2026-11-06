"""Intensidad relativa (%RM) de WODs — la carga prescrita que luego cruza el frontend.

    `GET /api/v1/wods/intensidad-relativa` entrega, por cada WOD al que el alumno
    asistió de verdad, la prescripción cruda (fecha, movimiento, categoría y valor).
    El % sobre el RM lo calcula el frontend; acá se fija el CONTRATO de qué filas se
    devuelven y cuáles se descartan.

    Corre con `TestClient(app)` (sin levantar servidor). Las reglas de dato se prueban
    con las funciones puras del router, SIN base, para que sean deterministas:

      1. fuerza válido (kg) → devuelve la fila;
      2. gimnástico con texto no parseable ("AMRAP") → se descarta sin romper;
      3. WOD sin asistencia `presente=True` → no aparece (lo garantiza el WHERE).

    Correr (aislado):
        cd backend && py -3.12 -m pytest tests/test_wods_intensidad_relativa.py -q
    """
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1 import wods  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# Funciones puras del router (sin base de datos)
# ══════════════════════════════════════════════════════════════════════════════
def _fila(**kwargs):
    """Fila del JOIN con los campos que consume `_filas_intensidad_relativa`."""
    base = dict(
        fecha=date(2026, 6, 1), wod_id=1, movimiento_id=1,
        nombre='Back Squat', categoria='fuerza', peso=80.0, repeticiones=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_primer_entero_parsea_el_primer_numero():
    assert wods._primer_entero('8-10') == 8
    assert wods._primer_entero('3x5') == 3
    assert wods._primer_entero('10') == 10
    assert wods._primer_entero('AMRAP') is None
    assert wods._primer_entero('') is None
    assert wods._primer_entero(None) is None


def test_fuerza_valido_se_devuelve():
    filas = wods._filas_intensidad_relativa([_fila()])
    assert len(filas) == 1
    assert filas[0]['categoria'] == 'fuerza'
    assert filas[0]['valor_prescrito'] == 80.0
    assert filas[0]['movimiento_nombre'] == 'Back Squat'


def test_fuerza_peso_nulo_o_cero_se_descarta():
    assert wods._filas_intensidad_relativa([_fila(peso=None)]) == []
    assert wods._filas_intensidad_relativa([_fila(peso=0.0)]) == []


def test_gimnastico_texto_no_parseable_se_descarta_sin_romper():
    assert wods._filas_intensidad_relativa(
        [_fila(categoria='gimnastico', peso=None, repeticiones='AMRAP')]) == []


def test_gimnastico_valido_parsea_el_primer_entero():
    filas = wods._filas_intensidad_relativa(
        [_fila(categoria='gimnastico', peso=None, repeticiones='8-10')])
    assert len(filas) == 1
    assert filas[0]['valor_prescrito'] == 8.0


def test_cardio_y_metabolico_se_excluyen_a_proposito():
    assert wods._filas_intensidad_relativa([_fila(categoria='cardio')]) == []
    assert wods._filas_intensidad_relativa([_fila(categoria='metabolico')]) == []


def test_sin_asistencia_presente_no_aparece_por_el_where():
    """El endpoint sólo trae asistencias `presente=True`: un WOD con la asistencia
    ausente directamente no entra en el JOIN. Se fija el filtro en el código."""
    src = (_BACKEND / 'app/api/v1/wods.py').read_text(encoding='utf-8')
    assert 'Asistencia.presente.is_(True)' in src, \
        "el endpoint tiene que filtrar `presente=True` (si no, trae WODs no asistidos)"


def test_query_tiene_asistencia_en_el_from():
    """El FROM arranca en `asistencias` (`.select_from(Asistencia)`).

    Es el fix del 500 en producción: antes el primer `.join(Clase, ...)` referenciaba
    `asistencias` en el ON sin que estuviera en el FROM, y Postgres tiraba
    "missing FROM-clause entry for table 'asistencias'". Este test compila el SQL
    (dialecto Postgres) SIN base y verifica que el FROM quede bien formado.
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Query

    class _Db:
        def query(self, *entidades):
            return Query(entidades)

    q = wods._query_intensidad_relativa(_Db(), 1, 1, date(2026, 1, 1))
    sql = str(q.statement.compile(dialect=postgresql.dialect()))
    assert "FROM asistencias" in sql, f"FROM sin asistencia:\n{sql}"
    assert "asistencias.clase_id = clases.id" in sql, \
        f"el primer JOIN (clases) no está anclado a asistencias:\n{sql}"


def test_intensidad_relativa_se_registra_antes_que_wod_id():
    """La ruta ESTÁTICA `/intensidad-relativa` tiene que estar ANTES de `/{wod_id}`.

    Es el fix del 422 en producción: FastAPI matchea rutas en orden de declaración, así
    que si `/{wod_id}` (path param int) estuviera antes, interceptaría la request y
    trataría de parsear "intensidad-relativa" como int. Se verifica el orden real del
    router (sin red ni base).
    """
    caminos = [r.path for r in wods.router.routes]
    i_estatica = next(i for i, p in enumerate(caminos) if p.endswith("/intensidad-relativa"))
    i_param = next(i for i, p in enumerate(caminos) if p.endswith("/{wod_id}"))
    assert i_estatica < i_param, \
        f"/intensidad-relativa ({i_estatica}) debe ir antes que /{{wod_id}} ({i_param})"


# ══════════════════════════════════════════════════════════════════════════════
# TestClient(app): la ruta existe y exige autenticación
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_endpoint_exige_token(cliente):
    r = cliente.get('/api/v1/wods/intensidad-relativa')
    assert r.status_code == 401, r.text


def test_get_intensidad_relativa_responde_200_no_422(cliente):
    """GET /intensidad-relativa con token válido responde 200 (no 422).

    Es justo el bug de producción: con la ruta estática después de `/{wod_id}`,
    FastAPI interceptaba la request y devolvía 422 ("Input should be a valid
    integer"). Acá se mockean auth y DB (dependencias) para verificar el contrato
    SIN depender de la rama TEST.
    """
    from app.core.dependencies import get_current_user
    from app.db.database import get_db
    from app.main import app

    class _FakeQuery:
        def select_from(self, *a): return self
        def join(self, *a, **k): return self
        def filter(self, *a, **k): return self
        def order_by(self, *a): return self
        def limit(self, *a): return self
        def all(self): return []

    class _FakeDb:
        def query(self, *a, **k): return _FakeQuery()

    def _user_override():
        return {
            "usuario_id": 1, "tenant_id": 1, "rol": "alumno", "nombre": "Test",
            "correo": "t@t.com", "activo": True, "estado": "activo",
        }

    def _db_override():
        return _FakeDb()

    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_db] = _db_override
    try:
        r = cliente.get('/api/v1/wods/intensidad-relativa')
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    assert isinstance(r.json(), list)


def test_endpoint_responde_200_con_token_valido(cliente):
    """Smoke: con un alumno REAL de la rama TEST devuelve una lista JSON (vacía o no)."""
    from app.core.config import is_test_db_url, settings
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.skip("DATABASE_URL no es una rama de TEST: sin acceso a datos reales")

    from sqlalchemy import text
    from app.db.database import SessionLocal
    from app.core.security import create_access_token

    session = SessionLocal()
    try:
        fila = session.execute(text(
            "SELECT id FROM usuarios WHERE tenant_id = 1 AND rol = 'alumno' "
            "AND estado = 'activo' ORDER BY id LIMIT 1")).first()
    finally:
        session.close()

    if not fila:
        pytest.skip("TEST no tiene un alumno activo para el smoke")

    token = create_access_token({
        "usuario_id": int(fila[0]), "tenant_id": 1, "rol": "alumno",
        "correo": "alumno@test.com",
    })
    r = cliente.get('/api/v1/wods/intensidad-relativa',
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
