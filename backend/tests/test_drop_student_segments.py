"""D6 — borrar `student_segments` (decisión de negocio 2026-10-28).

QUÉ FIJA ESTE ARCHIVO
---------------------
`student_segments` (migración 021) era un data mart de "nivel de atleta" con 6 filas de seed y
CERO consumidores: ningún endpoint, servicio, modelo relacionado ni FK de otra tabla. El nivel
real vive en `usuarios.nivel_*` desde la 060 (D3).

1. La migración 062 la elimina (idempotente: sólo si existe) y su `downgrade` la recrea igual
   que la 021.
2. El modelo `app/models/student_segments.py` ya no existe y nadie lo importa.
3. Los scripts de bootstrap/sync/borrado dejaron de nombrarla (si la nombraran, el `DELETE` o el
   `ALTER TABLE` fallaría en una base migrada).
4. `segmentacion_alumnos` (arquetipos de retención, 026) NO se toca: otra semántica y SÍ tiene
   consumidores.
5. La cadena de Alembic queda con UN solo head (062).

Correr (aislado, sin DB):
    cd backend && py -3.12 -m pytest tests/test_drop_student_segments.py -q --noconftest
"""
import ast
import glob
import os
import sys
import warnings
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
RAIZ = BACKEND.parent
os.environ.setdefault("ENVIRONMENT", "test")


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_la_migracion_062_borra_y_sabe_recrear_la_tabla():
    migracion = _fuente("backend/alembic/versions/062_drop_student_segments.py")
    assert 'revision = "062_drop_student_segments"' in migracion
    assert 'down_revision = "061_rm_gimnasia_reps"' in migracion
    assert 'TABLA = "student_segments"' in migracion
    assert "op.drop_table(TABLA)" in migracion
    # Idempotente: si la tabla ya no está, no falla.
    assert "if _existe():" in migracion
    # Downgrade completo (tabla + los dos índices de la 021).
    assert "op.create_table(" in migracion
    assert "ix_student_segments_tenant" in migracion
    assert "ix_student_segments_usuario" in migracion


def test_el_modelo_ya_no_existe():
    assert not (BACKEND / "app/models/student_segments.py").exists()


def test_ningun_modulo_la_declara_ni_la_importa():
    for archivo in glob.glob(str(BACKEND / "app/**/*.py"), recursive=True):
        texto = Path(archivo).read_text(encoding="utf-8")
        assert '__tablename__ = "student_segments"' not in texto, archivo
        assert "import app.models.student_segments" not in texto, archivo
        assert "from app.models.student_segments" not in texto, archivo


def test_los_scripts_de_bootstrap_y_sync_ya_no_la_nombran():
    bootstrap = _fuente("backend/run_setup_test_db.py")
    assert "app.models.student_segments" not in bootstrap
    assert "ALTER TABLE student_segments" not in bootstrap

    sync = _fuente("backend/scripts/sync_test_from_prod.py")
    assert "student_segments" not in sync

    # `segmentacion_alumnos` sigue (esa NO se borra).
    assert "app.models.segmentacion_alumno" in bootstrap
    assert "segmentacion_alumnos" in sync


def test_la_tabla_de_arquetipos_sigue_intacta():
    assert (BACKEND / "app/models/segmentacion_alumno.py").exists()
    assert (BACKEND / "alembic/versions/026_segmentacion_alumnos.py").exists()
    modelo = _fuente("backend/app/models/segmentacion_alumno.py")
    assert '__tablename__ = "segmentacion_alumnos"' in modelo


def test_la_cadena_de_alembic_tiene_un_solo_head():
    revisiones: dict = {}
    padres: list = []

    for archivo in glob.glob(str(BACKEND / "alembic/versions/*.py")):
        # Alguna migración vieja tiene `\d` en un docstring: el warning no es del test.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            arbol = ast.parse(Path(archivo).read_text(encoding="utf-8-sig"))
        for nodo in arbol.body:
            if not isinstance(nodo, (ast.Assign, ast.AnnAssign)):
                continue
            objetivo = nodo.targets[0] if isinstance(nodo, ast.Assign) else nodo.target
            if not isinstance(objetivo, ast.Name):
                continue
            if objetivo.id not in ("revision", "down_revision"):
                continue
            try:
                valor = ast.literal_eval(nodo.value)
            except (ValueError, SyntaxError):
                valor = None
            if objetivo.id == "revision":
                revisiones[archivo] = valor
            elif valor:
                padres.extend(valor if isinstance(valor, tuple) else [valor])

    assert "062_drop_student_segments" in revisiones.values()
    # Sin revisiones duplicadas y un único head (si no, `alembic upgrade head` falla).
    assert len(revisiones.values()) == len(set(revisiones.values()))
    heads = sorted(set(revisiones.values()) - set(padres))
    # No se fija CUÁL es el head: las migraciones siguientes (063, …) lo mueven.
    assert len(heads) == 1, heads


def test_los_docs_historicos_no_se_reescriben():
    """Las migraciones 021/026 son historia: se leen, no se editan."""
    mig021 = _fuente("backend/alembic/versions/021_data_marts_bi.py")
    mig026 = _fuente("backend/alembic/versions/026_segmentacion_alumnos.py")
    assert "'student_segments'" in mig021          # la 021 sigue creándola
    assert "student_segments" in mig026            # la 026 explica por qué NO la reusa
    assert "021_data_marts_bi" in mig021           # sigue siendo la migración que la crea
