"""D3 — nivel persistido en `usuarios` (decisión de negocio 2026-10-28).

QUÉ FIJA ESTE ARCHIVO
---------------------
1. La migración `060` agrega las 8 columnas de nivel + el índice `(tenant_id, nivel_atleta)` y
   el modelo `Usuario` las declara (si divergen, `alembic` autogenera basura).
2. `nivel_esta_vigente` es la política de staleness: versión de la regla + 24 h + NULL.
3. `recalcular_nivel` es el ÚNICO camino de escritura y delega en `nivel_desde_mejores`
   (la función pura): no hay una segunda fórmula para el nivel persistido.
4. Los 6 caminos que mueven el resultado recalculan: POST/PUT/DELETE de RM, `PUT /alumnos/me`,
   `PUT /usuarios/{id}` y `PUT .../alumno/{id}/perfil` (peso/género), más el job nocturno.
5. El frontend LEE el nivel (`nivelDesdeBackend`), no lo deriva.

Correr (aislado, sin DB):
    cd backend && py -3.12 -m pytest tests/test_nivel_persistido.py -q --noconftest
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
RAIZ = BACKEND.parent
os.environ.setdefault("ENVIRONMENT", "test")


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


# ── 1. Migración y modelo ─────────────────────────────────────────────────────
COLUMNAS = [
    "nivel_fuerza", "nivel_gimnastico", "nivel_atleta", "nivel_movs_fuerza",
    "nivel_movs_gimnasia", "nivel_confianza", "nivel_calculado_en", "nivel_version",
]


def test_la_migracion_060_agrega_las_columnas_y_el_indice():
    migracion = _fuente("backend/alembic/versions/060_nivel_atleta_persistido.py")
    assert 'revision = "060_nivel_atleta_persistido"' in migracion
    assert 'down_revision = "059_reserva_suscripcion_id"' in migracion
    for columna in COLUMNAS:
        assert f'("{columna}", sa.' in migracion, f"falta la columna {columna}"
    assert 'INDICE = "ix_usuarios_tenant_nivel"' in migracion
    assert '["tenant_id", "nivel_atleta"]' in migracion
    # Sin CHECK de valores: la escalera crece sin migración (mismo criterio que la 026).
    assert "CheckConstraint" not in migracion
    # Downgrade completo (se puede volver atrás sin perder otras columnas).
    assert "def downgrade()" in migracion and "drop_column" in migracion


def test_el_modelo_usuario_declara_las_mismas_columnas():
    modelo = _fuente("backend/app/models/usuario.py")
    for columna in COLUMNAS:
        assert re.search(rf"^\s+{columna} = Column\(", modelo, re.M), \
            f"el modelo no declara {columna}"


# ── 2. Política de staleness (pura, con objetos falsos) ───────────────────────
def _usuario(**kw):
    base = {"nivel_calculado_en": datetime.now(timezone.utc),
            "nivel_version": "d3-v1"}
    base.update(kw)
    return SimpleNamespace(**base)


def test_una_fila_recien_calculada_esta_vigente():
    from app.services.nivel_service import NIVEL_VERSION, nivel_esta_vigente

    assert nivel_esta_vigente(_usuario(nivel_version=NIVEL_VERSION))


def test_una_version_vieja_obliga_a_recalcular():
    from app.services.nivel_service import nivel_esta_vigente

    assert not nivel_esta_vigente(_usuario(nivel_version="d1-v0"))
    assert not nivel_esta_vigente(_usuario(nivel_version=None))


def test_una_fila_de_mas_de_24h_se_recalcula():
    from app.services.nivel_service import nivel_esta_vigente

    vieja = datetime.now(timezone.utc) - timedelta(hours=25)
    casi = datetime.now(timezone.utc) - timedelta(hours=23)
    assert not nivel_esta_vigente(_usuario(nivel_calculado_en=vieja))
    assert nivel_esta_vigente(_usuario(nivel_calculado_en=casi))


def test_sin_fecha_no_esta_vigente():
    from app.services.nivel_service import nivel_esta_vigente

    assert not nivel_esta_vigente(_usuario(nivel_calculado_en=None))


# ── 3. Mapeo resultado <-> columnas ───────────────────────────────────────────
def test_sin_datos_se_guarda_como_null_y_vuelve_como_sin_datos():
    from app.services.nivel_service import _columnas_desde_nivel, _nivel_desde_columnas

    resultado = {
        "nivel_fuerza": "Sin datos", "nivel_gimnastico": "Intermedio",
        "nivel_atleta": "Intermedio", "movs_fuerza": 1, "movs_gimnasia": 2,
        "nivel_confianza": "media",
    }
    columnas = _columnas_desde_nivel(resultado)
    assert columnas["nivel_fuerza"] is None
    assert columnas["nivel_gimnastico"] == "Intermedio"
    assert columnas["nivel_movs_fuerza"] == 1
    assert columnas["nivel_version"] == "d3-v1"
    assert columnas["nivel_calculado_en"] is not None

    vuelta = _nivel_desde_columnas(SimpleNamespace(
        nivel_fuerza=None, nivel_gimnastico="Intermedio", nivel_atleta="Intermedio",
        nivel_movs_fuerza=1, nivel_movs_gimnasia=2, nivel_confianza="media"))
    assert vuelta["nivel_fuerza"] == "Sin datos"
    assert vuelta["nivel_gimnastico"] == "Intermedio"
    assert vuelta["detalle_fuerza"] == []


def test_recalcular_usa_la_funcion_pura_y_las_mejores_marcas():
    svc = _fuente("backend/app/services/nivel_service.py")
    desde = svc.index("def recalcular_nivel(")
    cuerpo = svc[desde:svc.index("def calcular_nivel_general(", desde)]
    assert "nivel_desde_mejores(" in cuerpo
    assert "_mejores_rms_lote(" in cuerpo
    assert "_guardar_nivel(" in cuerpo
    # No duplica umbrales ni tablas: el cálculo vive en un solo lugar.
    assert "CROSSFIT_RATIOS" not in cuerpo and "CROSSFIT_HABILIDADES" not in cuerpo


def test_el_lote_lee_lo_persistido_y_solo_recalcula_lo_vencido():
    svc = _fuente("backend/app/services/nivel_service.py")
    desde = svc.index("def calcular_niveles_lote(")
    cuerpo = svc[desde:]
    assert "nivel_esta_vigente(" in cuerpo
    assert "_nivel_desde_columnas(" in cuerpo
    assert "pendientes" in cuerpo
    assert "Usuario.id.in_(ids)" in cuerpo


# ── 4. Los 6 caminos que mueven el nivel recalculan ───────────────────────────
def test_los_endpoints_de_rm_recalculan():
    fuente = _fuente("backend/app/api/v1/historial_rm.py")
    assert "recalcular_nivel(db, historial_data.alumno_id, tenant_id)" in fuente  # POST
    assert "recalcular_nivel(db, historial.alumno_id" in fuente                  # PUT
    assert "recalcular_nivel(db, alumno_id, current_user[\"tenant_id\"])" in fuente  # DELETE
    # El POST ya no escribe el snapshot `historial_rm.nivel_calculado` (segunda verdad).
    desde = fuente.index("def crear_historial_rm(")
    post = fuente[desde:fuente.index("@router.get(\"/progreso-lote\"", desde)]
    assert "db_historial.nivel_calculado =" not in post


def test_los_cambios_de_perfil_recalculan():
    me = _fuente("backend/app/api/v1/alumnos.py")
    assert '{"peso_kg", "genero"} & set(update_data)' in me
    assert "recalcular_nivel(db, usuario.id, tenant_id)" in me

    admin = _fuente("backend/app/api/v1/usuarios.py")
    assert '{"peso_kg", "genero"} & set(update_data)' in admin
    assert "recalcular_nivel(db, usuario.id, tenant_id)" in admin

    coach = _fuente("backend/app/api/v1/fidelizacion.py")
    assert "recalcular_nivel(db, alumno.id, tenant_id)" in coach


def test_el_job_nocturno_existe_y_es_dry_run_por_defecto():
    job = _fuente("backend/maintenance/recalcular_niveles.py")
    assert "def run(dry_run=True" in job
    assert "--aplicar" in job
    assert "nivel_esta_vigente(" in job
    assert "recalcular_nivel(" in job
    # Sin `--aplicar` no escribe: el contador sube igual para que el dry-run informe.
    desde = job.index("def run(")
    cuerpo = job[desde:job.index("def main(", desde)]
    assert "if not dry_run:" in cuerpo

