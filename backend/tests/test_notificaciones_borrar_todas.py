"""Borrar todas las notificaciones (soft delete con confirmación por N).

QUÉ FIJA ESTE ARCHIVO
---------------------
Antes la campana solo OCULTABA las leídas en el cliente: el backend no tenía DELETE y la lista
crecía para siempre. Ahora `DELETE /notificaciones?confirmar=N` hace SOFT DELETE:

1. Migración 063: `notificaciones.eliminada_en` (NULL = viva) + índice parcial
   `(alumno_id) WHERE eliminada_en IS NULL`, el predicado exacto del listado y del badge.
2. El listado, el contador y `leer-todas` solo miran las vivas.
3. La confirmación es por CANTIDAD: el panel muestra N y manda `confirmar=N`; si cambió
   (llegó un aviso nuevo), 409 con `total_actual` y no borra nada.
4. No hay DELETE físico (ni en el endpoint ni en la migración): la fila queda para auditoría.

Correr (aislado, sin DB):
    cd backend && py -3.12 -m pytest tests/test_notificaciones_borrar_todas.py -q --noconftest
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
RAIZ = BACKEND.parent
os.environ.setdefault("ENVIRONMENT", "test")


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_la_migracion_063_agrega_la_columna_y_el_indice_parcial():
    migracion = _fuente("backend/alembic/versions/063_notificaciones_soft_delete.py")
    assert 'revision = "063_notificaciones_soft_delete"' in migracion
    assert 'down_revision = "062_drop_student_segments"' in migracion
    assert "eliminada_en" in migracion
    assert "ALTER TABLE {TABLA} ADD COLUMN IF NOT EXISTS {COLUMNA}" in migracion
    assert "WHERE {COLUMNA} IS NULL" in migracion            # índice parcial
    # Soft delete: no se borran filas.
    assert "DELETE FROM" not in migracion
    assert "DROP COLUMN IF EXISTS" in migracion


def test_el_modelo_declara_eliminada_en():
    modelo = _fuente("backend/app/models/notificacion.py")
    assert "eliminada_en = Column(" in modelo


def test_el_listado_y_el_badge_solo_miran_las_vivas():
    api = _fuente("backend/app/api/v1/notificaciones.py")
    assert "def _vivas(" in api
    assert "Notificacion.eliminada_en.is_(None)" in api
    # GET / y PUT /leer-todas usan el helper (no repiten el filtro a mano).
    desde_get = api.index("def listar_notificaciones(")
    get = api[desde_get:api.index('@router.put("/{notificacion_id}/leer"', desde_get)]
    assert "query = _vivas(db, alumno_id)" in get

    desde_leer = api.index("def marcar_todas_como_leidas(")
    leer = api[desde_leer:api.index('@router.delete("")', desde_leer)]
    assert "_vivas(db, alumno_id)" in leer


def test_el_delete_es_soft_y_exige_la_cantidad_confirmada():
    api = _fuente("backend/app/api/v1/notificaciones.py")
    desde = api.index("def borrar_todas_las_notificaciones(")
    endpoint = api[desde:api.index("@router.post(", desde)]

    assert "confirmar: int = Query(" in endpoint
    assert "if confirmar != len(filas):" in endpoint
    assert "status_code=status.HTTP_409_CONFLICT" in endpoint
    assert '"total_actual": len(filas)' in endpoint
    assert "fila.eliminada_en = ahora" in endpoint
    assert "db.delete(" not in endpoint
    assert "DELETE FROM" not in endpoint
    assert "_filas_borrables(db, alumno_id)" in endpoint
    assert '"eliminadas": len(filas)' in endpoint


def test_el_tope_del_borrado_es_el_del_listado():
    api = _fuente("backend/app/api/v1/notificaciones.py")
    assert "MAX_BORRAR_NOTIFICACIONES = 50" in api
    # El listado usa el MISMO 50: si no, el N confirmado no coincidiría.
    desde = api.index("def listar_notificaciones(")
    get = api[desde:api.index('@router.put("/{notificacion_id}/leer"', desde)]
    assert ".limit(50)" in get


def test_el_panel_pide_confirmacion_por_n():
    campana = _fuente("frontend/src/components/CampanaNotificaciones.jsx")
    assert 'data-testid="borrar-todas-notificaciones"' in campana
    assert 'data-testid="confirmar-borrar-todas"' in campana
    assert "params: { confirmar: cantidad }" in campana
    assert "const cantidad = notificaciones.length;" in campana
    # 409: muestra el total real y recarga la lista.
    assert "total_actual" in campana
    assert "cargarLista();" in campana
    # Ya no dice que el backend no tiene DELETE.
    assert "el backend no tiene DELETE de notificaciones" not in campana
