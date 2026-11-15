"""Buscador del PADRÓN de alumnos (GET /usuarios/?buscar=...): sin mayúsculas NI tildes.

Bug real: el admin escribía "Sebastian" y el padrón NO encontraba a "Sebastián". El filtro
usaba `ilike`, que ignora mayúsculas pero no tildes (en Postgres 'á' y 'a' son caracteres
distintos). Desde el fix, el padrón usa la MISMA normalización que Fidelización
(`columna_normalizada()` + `normalizar()`: translate()+lower(), porque `unaccent` no está
instalado en la base).

  A. PURAS (sin BD): `normalizar()` da el MISMO término desde "Sebastián" que desde
     "Sebastian", y el padrón ya NO filtra con `ilike` directo.
  B. SERVICIO contra TEST (escribe y RESTAURA): dos alumnos sembrados a mano —uno
     guardado como "Sebastián ..." y otro como "Sebastian ..."— se encuentran buscando
     CON tilde y SIN tilde, sin importar cómo esté guardado el nombre.

Correr (aislado, contra TEST):
    cd backend && py -3.12 -m pytest tests/test_busqueda_alumnos_tildes.py -q --noconftest
(con ENVIRONMENT=test en el entorno, para que se cargue `.env.test`)
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import Response
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1 import usuarios as usuarios_api                          # noqa: E402
from app.models.usuario import Usuario                                  # noqa: E402
from app.utils import busqueda as b                                     # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TENANT_ID = 1


# ══════════════════════════════════════════════════════════════════════════════
# A. Puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_el_termino_con_y_sin_tilde_se_normaliza_igual():
    """"Sebastián" y "Sebastian" producen el MISMO patrón: ése es el bug real."""
    assert b.normalizar("Sebastián") == "sebastian"
    assert b.normalizar("Sebastian") == "sebastian"
    assert b.normalizar("SEBASTIÁN") == "sebastian"


def test_a2_el_padron_filtra_con_columna_normalizada_y_no_con_ilike():
    """El listado del padrón usa el MISMO patrón que kpis.py (no un `ilike` nuevo)."""
    fuente = (RAIZ / "backend/app/api/v1/usuarios.py").read_text(encoding="utf-8")
    assert "columna_normalizada(Usuario.nombre).like(patron)" in fuente
    assert "columna_normalizada(Usuario.correo).like(patron)" in fuente
    assert "Usuario.nombre.ilike" not in fuente and "Usuario.correo.ilike" not in fuente
    assert "from app.utils.busqueda import columna_normalizada, normalizar" in fuente


def test_a3_la_expresion_sql_normaliza_la_columna():
    sql = str(b.columna_normalizada(Usuario.nombre))
    assert "translate(" in sql and "lower(" in sql


def test_a4_los_otros_buscadores_de_alumno_usan_la_misma_normalizacion():
    """Beneficios (`q`) y Suspensiones (`buscar`) también buscan alumnos por nombre."""
    for ruta in ("backend/app/api/v1/beneficios.py",
                 "backend/app/api/v1/suspensiones.py"):
        fuente = (RAIZ / ruta).read_text(encoding="utf-8")
        assert "columna_normalizada(Usuario.nombre).like(patron)" in fuente, ruta
        assert "Usuario.nombre.ilike" not in fuente, ruta


# ══════════════════════════════════════════════════════════════════════════════
# B. Servicio contra TEST (escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(usa ENVIRONMENT=test)")
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def alumnos_con_y_sin_tilde(db):
    """Dos alumnos con el MISMO nombre salvo la tilde, sembrados a mano.

    `con_tilde` se guarda "Sebastián ..." y `sin_tilde` "Sebastian ...": así se prueba
    también el camino inverso (buscar CON tilde a alguien guardado SIN tilde).
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    marca = sufijo[-4:]
    ids = []
    try:
        for i, nombre in enumerate((f"Sebastián Tilde Qa{marca}",
                                    f"Sebastian Tilde Qb{marca}"), start=1):
            aid = db.execute(text("""
                INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                      activo, estado, created_at)
                VALUES (:t, :r, :n, :c, 'x', 'alumno', true, 'activo', now())
                RETURNING id"""),
                {"t": TENANT_ID, "r": f"95{sufijo[-7:]}-{i}",
                 "n": nombre, "c": f"tilde.{sufijo}.{i}@test.local"}).scalar()
            ids.append(aid)
        db.commit()
        yield {"con_tilde": ids[0], "sin_tilde": ids[1], "marca": marca}
    finally:
        db.rollback()
        try:
            for aid in ids:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": aid})
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"\n[WARN] limpieza: {e}")


def _listar(db, termino):
    """Ids de la página del padrón (llamada directa al endpoint, sin levantar servidor).

    Los parámetros con `Query(...)` se pasan EXPLÍCITOS: al invocar la función directo,
    sus defaults son objetos `FieldInfo` (truthy / no-None), no los valores que pone
    FastAPI, y se aplicarían filtros de más.
    """
    usuarios = usuarios_api.listar_usuarios(
        response=Response(),
        tenant_id=None, skip=0, limit=1000, activo=None, rol=None,
        buscar=termino, estado=None, con_membresia=False,
        db=db, current_user={"tenant_id": TENANT_ID, "usuario_id": 1},
    )
    return {u.id for u in usuarios}


def test_b1_buscar_sin_tilde_encuentra_el_nombre_con_tilde(db, alumnos_con_y_sin_tilde):
    aid = alumnos_con_y_sin_tilde["con_tilde"]
    ids = _listar(db, "Sebastian")              # el admin escribe SIN tilde
    assert aid in ids, "buscar 'Sebastian' debe encontrar a 'Sebastián'"


def test_b2_buscar_con_tilde_encuentra_el_nombre_sin_tilde(db, alumnos_con_y_sin_tilde):
    aid = alumnos_con_y_sin_tilde["sin_tilde"]
    ids = _listar(db, "Sebastián")              # el admin escribe CON tilde
    assert aid in ids, "buscar 'Sebastián' debe encontrar a 'Sebastian'"


def test_b3_la_tilde_del_termino_da_igual_y_trae_a_los_dos(db, alumnos_con_y_sin_tilde):
    sin = alumnos_con_y_sin_tilde["sin_tilde"]
    con = alumnos_con_y_sin_tilde["con_tilde"]
    assert _listar(db, "SEBASTIAN") == _listar(db, "SEBASTIÁN"), (
        "el resultado no puede depender de si el término lleva tilde")
    ambos = _listar(db, "Sebastián")
    assert sin in ambos and con in ambos


def test_b4_el_nombre_completo_tambien_encuentra(db, alumnos_con_y_sin_tilde):
    aid = alumnos_con_y_sin_tilde["con_tilde"]
    marca = alumnos_con_y_sin_tilde["marca"]
    assert aid in _listar(db, f"sebastian tilde qa{marca}")   # sin ninguna tilde
    assert aid in _listar(db, f"SEBASTIÁN TILDE QA{marca}")   # todo en mayúsculas


def test_b5_un_termino_ajeno_no_los_trae(db, alumnos_con_y_sin_tilde):
    ids = _listar(db, "zzzznoexiste")
    assert alumnos_con_y_sin_tilde["con_tilde"] not in ids
    assert alumnos_con_y_sin_tilde["sin_tilde"] not in ids


def test_b6_buscar_solo_espacios_se_ignora(db):
    """`buscar='   '` no puede volverse un filtro que matchea nada: se ignora."""
    assert _listar(db, "   ") == _listar(db, None)
