"""Buscador server-side de la tabla de Fidelización: nombre o correo, SIN mayúsculas ni tildes.

La tabla del churn (GET /kpis/churn) ahora acepta `buscar`: filtra por nombre o correo del
alumno en el BACKEND, sin distinguir mayúsculas ni tildes (`unaccent` no está instalado en
la base, así que se normaliza con translate()+lower()). El input del panel tiene debounce.

  A. PURAS (sin BD): `normalizar()` (Python) y la tabla de acentos.
  B. SERVICIO contra TEST (escribe y RESTAURA): un alumno "Josefa Muñoz" se encuentra
     buscando "munoz" (sin tilde, minúsculas) y NO con un término que no aparece.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_busqueda_fidelizacion.py -q --noconftest
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1 import kpis as kpis_api                                    # noqa: E402
from app.models.usuario import Usuario                                     # noqa: E402
from app.utils import busqueda as b                                        # noqa: E402

TENANT_ID = 1


# ══════════════════════════════════════════════════════════════════════════════
# A. Puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_normalizar_quita_tildes_y_baja_mayusculas():
    assert b.normalizar("José Muñoz") == "jose munoz"
    assert b.normalizar("MUÑOZ") == "munoz"
    assert b.normalizar("María José Peña") == "maria jose pena"


def test_a2_normalizar_vacio_es_cadena_vacia():
    assert b.normalizar(None) == ""
    assert b.normalizar("") == ""


def test_a3_la_tabla_de_acentos_es_consistente():
    """Cada acentuada (minúscula o MAYÚSCULA) cae en su letra simple."""
    assert len(b._ORIGEN) == len(b._DESTINO)
    for origen, destino in zip(b._ORIGEN, b._DESTINO):
        assert b.normalizar(origen) == destino


def test_a4_columna_normalizada_usa_translate_y_lower():
    sql = str(b.columna_normalizada(Usuario.nombre))
    assert "translate(" in sql and "lower(" in sql


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
def alumno_buscable(db):
    """Alumno con predicción de churn y un nombre CON tilde y mayúsculas."""
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    correo = f"busqueda.{sufijo}@test.local"
    aid = None
    try:
        aid = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Josefa Muñoz Busqueda', :c, 'x', 'alumno', true, 'activo', now())
            RETURNING id"""),
            {"t": TENANT_ID, "r": f"96{sufijo[-8:]}-9", "c": correo}).scalar()
        db.execute(text("""
            INSERT INTO predictions_churn (tenant_id, usuario_id, probabilidad_churn,
                                           riesgo_nivel, motivo, created_at)
            VALUES (:t, :u, 50, 'ALTO', 'TEST · búsqueda', now())"""),
            {"t": TENANT_ID, "u": aid})
        db.commit()
        yield {"alumno_id": aid, "correo": correo}
    finally:
        db.rollback()
        try:
            db.execute(text("DELETE FROM predictions_churn WHERE usuario_id = :a"), {"a": aid})
            if aid:
                db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": aid})
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"\n[WARN] limpieza: {e}")


def _buscar(db, termino):
    """Ids devueltos por el endpoint del panel (llamada directa, sin levantar servidor)."""
    data = kpis_api.get_predictions_churn(
        buscar=termino, db=db,
        current_user={"tenant_id": TENANT_ID, "usuario_id": 1})
    return {p["usuario_id"] for p in data["predicciones"]}


def test_b1_encuentra_sin_mayusculas_ni_tildes(db, alumno_buscable):
    aid = alumno_buscable["alumno_id"]
    assert aid in _buscar(db, "munoz")          # sin tilde y en minúsculas
    assert aid in _buscar(db, "MUÑOZ")          # con tilde y en mayúsculas
    assert aid in _buscar(db, "josefa muñoz")   # nombre completo


def test_b2_no_aparece_con_termino_ajeno(db, alumno_buscable):
    assert alumno_buscable["alumno_id"] not in _buscar(db, "zzzznoexiste")


def test_b3_sin_buscar_trae_a_todos(db, alumno_buscable):
    aid = alumno_buscable["alumno_id"]
    assert aid in _buscar(db, None)
    assert aid in _buscar(db, "")


def test_b4_los_contadores_son_del_box_completo(db, alumno_buscable):
    """Buscar NO cambia los contadores de las tarjetas (siguen siendo del box COMPLETO)."""
    completo = kpis_api.get_predictions_churn(
        buscar=None, db=db,
        current_user={"tenant_id": TENANT_ID, "usuario_id": 1})
    filtrado = kpis_api.get_predictions_churn(
        buscar="munoz", db=db,
        current_user={"tenant_id": TENANT_ID, "usuario_id": 1})
    assert filtrado["total"] == completo["total"]
    assert filtrado["altos"] == completo["altos"]
    assert len(filtrado["predicciones"]) <= len(completo["predicciones"])
