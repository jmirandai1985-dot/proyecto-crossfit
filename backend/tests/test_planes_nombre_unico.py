"""`planes (tenant_id, nombre)` es ÚNICO: el índice que respalda el "si no existe, créalo" del pase.

Regla (migración 040)
---------------------
Dos planes con el mismo nombre en el MISMO box son el mismo plan dos veces: el catálogo del box no
puede tenerlo. Y sin este índice no se puede escribir el alta idempotente del plan del pase
(`beneficios_service._crear_plan_del_pase`): Postgres rechaza el
`INSERT … ON CONFLICT (tenant_id, nombre)` con "there is no unique or exclusion constraint matching
the ON CONFLICT specification", que era el motivo del `SELECT … FOR UPDATE` del box que la 040
reemplazó.

Lo que fija este test (contra TEST: escribe y REVIERTE)
-------------------------------------------------------
  1. el índice existe y es UNIQUE (o sea: la 040 corrió) — si no, el test no prueba nada;
  2. dos planes con el mismo nombre en el MISMO box → `IntegrityError` (y el error nombra el índice);
  3. el MISMO nombre en DOS boxes → entra sin problema: el nombre es único DENTRO del box (cada box
     arma su catálogo; "Plan mensual" existe en los dos y eso está bien).

No deja nada en TEST: todo el escenario se descarta con `rollback()` (nunca hay `commit`).

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_planes_nombre_unico.py -q
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                     # noqa: E402
from app.models.plan import Plan                         # noqa: E402

INDICE = "planes_tenant_nombre"
# El nombre es descartable y dice de dónde salió: si alguna fila quedara, se ve que es de un test.
NOMBRE = "PLAN TEST nombre unico 040"


@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(revisa .env.test / ENVIRONMENT)")
    print("\n[OK] base de datos de TEST confirmada\n")
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="module")
def boxes(db):
    """Dos boxes DISTINTOS de TEST: el caso 3 necesita dos (no importa cuáles)."""
    ids = [r[0] for r in db.execute(
        text("SELECT id FROM tenants ORDER BY id LIMIT 2")).all()]
    if len(ids) < 2:
        pytest.skip("TEST necesita 2 boxes para probar que el nombre es único POR BOX")
    return ids


def _plan(tenant_id: int) -> Plan:
    """Un plan mínimo y descartable de un box (no se vende: sólo existe para chocar con el índice)."""
    return Plan(tenant_id=tenant_id, nombre=NOMBRE, creditos=1, es_ilimitado=False,
                precio_clp=0, duracion_dias=30, activo=False, es_comercial=False)


def test_el_nombre_de_plan_es_unico_por_box_y_no_entre_boxes(db, boxes):
    """Casos 1-3 de la regla: el índice está, el duplicado DENTRO del box falla y entre boxes no."""
    box_a, box_b = boxes

    # 1. El índice existe y es UNIQUE: sin él el `ON CONFLICT` del plan del pase es un error de SQL.
    ddl = db.execute(text(
        "SELECT indexdef FROM pg_indexes WHERE tablename = 'planes' AND indexname = :n"),
        {"n": INDICE}).scalar()
    assert ddl, (f"falta el índice {INDICE} en TEST: aplicá la migración 040 "
                 f"(ENVIRONMENT=test alembic upgrade head)")
    assert "UNIQUE" in ddl.upper() and "(tenant_id, nombre)" in ddl, ddl

    # 2. Mismo box, mismo nombre: el primero entra, el segundo NO (unique violation del índice).
    db.add(_plan(box_a))
    db.flush()
    db.add(_plan(box_a))
    with pytest.raises(IntegrityError) as err:
        db.flush()
    assert INDICE in str(err.value), \
        f"el error tiene que nombrar el índice ({INDICE}): {err.value}"
    db.rollback()       # se descarta el escenario: en TEST no queda ninguna fila

    # 3. Mismo nombre, boxes DISTINTOS: los dos entran (el nombre es único DENTRO del box).
    db.add(_plan(box_a))
    db.add(_plan(box_b))
    db.flush()
    filas = db.query(Plan).filter(Plan.nombre == NOMBRE).all()
    assert {f.tenant_id for f in filas} == {box_a, box_b} and len(filas) == 2
    assert filas[0].id != filas[1].id
    db.rollback()       # nada queda: la regla se probó y el catálogo de TEST sigue igual
