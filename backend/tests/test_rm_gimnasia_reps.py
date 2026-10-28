"""D4 — gimnasia por repeticiones, no por `peso_kg` (decisión de negocio 2026-10-28).

QUÉ FIJA ESTE ARCHIVO
---------------------
El valor de un RM gimnástico (reps de un unbroken set, metros de HSW) vivía en `peso_kg`, una
columna NOT NULL que obligaba a mandar un peso donde no hay peso. El formulario copiaba el
número en las dos columnas (o mandaba 1) y el cálculo ordenaba por `max(peso_kg)`: funcionaba
"de casualidad" mientras `repeticiones == peso_kg`.

1. Migración 061: `peso_kg` nullable + backfill `repeticiones = round(peso_kg)` en gimnasia
   (idempotente) + downgrade que rellena antes de volver a NOT NULL.
2. Modelo y schemas: `peso_kg` opcional (fuerza lo exige a nivel endpoint; gimnasia lo rechaza).
3. POST/PUT validan por categoría con `categoria_de` (H-03), no por heurística de nombre.
4. `nivel_service._mejores_rms_lote` y `rms_service` ordenan gimnasia por
   `COALESCE(repeticiones, peso_kg)` y fuerza por `peso_kg` — la MISMA expresión en los dos.
5. El formulario manda `peso_kg = null` fuera de fuerza.

Correr (aislado, sin DB):
    cd backend && py -3.12 -m pytest tests/test_rm_gimnasia_reps.py -q --noconftest
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


# ── 1. Migración ──────────────────────────────────────────────────────────────
def test_la_migracion_061_hace_nullable_el_peso_y_migra_las_reps():
    migracion = _fuente("backend/alembic/versions/061_rm_gimnasia_reps.py")
    assert 'revision = "061_rm_gimnasia_reps"' in migracion
    assert 'down_revision = "060_nivel_atleta_persistido"' in migracion
    assert "ALTER COLUMN peso_kg DROP NOT NULL" in migracion
    assert "SET repeticiones = round(h.peso_kg)::int" in migracion
    # Idempotente: solo toca las filas sin reps (la 0 también, es el dummy viejo).
    assert "h.repeticiones IS NULL OR h.repeticiones = 0" in migracion
    # Downgrade: rellena antes de volver a NOT NULL (no pierde el valor canónico).
    assert "COALESCE(peso_kg, repeticiones, 1)" in migracion
    assert "ALTER COLUMN peso_kg SET NOT NULL" in migracion


def test_el_modelo_permite_peso_null():
    modelo = _fuente("backend/app/models/historial_rm.py")
    assert "peso_kg = Column(Float, nullable=True)" in modelo


# ── 2. Schemas ────────────────────────────────────────────────────────────────
def test_los_schemas_de_entrada_y_salida_aceptan_peso_null():
    from app.schemas.historial_rm import (
        HistorialRMCreate, HistorialRMListItem, RMPorMovimiento,
    )

    assert HistorialRMCreate.model_fields["peso_kg"].annotation != float
    assert HistorialRMListItem.model_fields["peso_kg"].default is None
    assert RMPorMovimiento.model_fields["peso_kg"].default is None

    # Gimnasia: sin peso, con reps.
    datos = HistorialRMCreate(
        alumno_id=1, movimiento_id=2, fecha="2026-10-28",
        repeticiones=12, tenant_id=1)
    assert datos.peso_kg is None


# ── 3. Validación por categoría en los endpoints ──────────────────────────────
def test_el_post_valida_por_categoria():
    fuente = _fuente("backend/app/api/v1/historial_rm.py")
    desde = fuente.index("def crear_historial_rm(")
    post = fuente[desde:fuente.index('@router.get("/progreso-lote"', desde)]
    assert 'categoria = categoria_de(movimiento)' in post
    assert 'if categoria == "gimnastico":' in post
    assert '"Gimnasia: las repeticiones son obligatorias' in post
    assert '"Gimnasia: no envíes peso_kg' in post
    assert 'elif categoria == "fuerza" and not historial_data.peso_kg:' in post


def test_el_put_rechaza_peso_en_gimnasia_pero_acepta_null():
    fuente = _fuente("backend/app/api/v1/historial_rm.py")
    desde = fuente.index("def actualizar_historial_rm(")
    put = fuente[desde:fuente.index('@router.delete("/{historial_id}"', desde)]
    assert 'categoria_de(movimiento) == "gimnastico"' in put
    assert 'update_data.get("peso_kg") is not None' in put
    assert "no envíes peso_kg" in put


# ── 4. Una sola expresión de "mejor valor" ────────────────────────────────────
def test_el_nivel_elige_gimnasia_por_reps():
    svc = _fuente("backend/app/services/nivel_service.py")
    desde = svc.index("def _mejores_rms_lote(")
    cuerpo = svc[desde:svc.index("def _usuario_nivel(", desde)]
    assert "case(" in cuerpo
    assert "func.coalesce(func.cast(HistorialRM.repeticiones, Float)" in cuerpo
    assert "func.max(valor_nivel)" in cuerpo
    # Ya no queda el `max(peso_kg)` que ordenaba también la gimnasia.
    assert "func.max(HistorialRM.peso_kg)" not in svc


def test_los_mejores_rms_ordenan_igual_que_el_nivel():
    svc = _fuente("backend/app/services/rms_service.py")
    assert "case(" in svc
    assert "func.coalesce(func.cast(HistorialRM.repeticiones, Float)" in svc
    assert "valor_orden.desc()" in svc
    assert "HistorialRM.peso_kg.desc()" not in svc


# ── 5. Formulario ─────────────────────────────────────────────────────────────
def test_el_formulario_manda_peso_solo_en_fuerza():
    fuente = _fuente("frontend/src/pages/alumno/PizarraRMs.jsx")
    assert "const pesoDelFormRM = (form, cat) => (cat === 'fuerza'" in fuente
    assert ": null);" in fuente
    # El alta y la edición usan la misma regla.
    assert fuente.count("peso_kg: pesoDelFormRM(rmForm, cat)") == 2
    # Ya no copia las reps en peso_kg (el dummy de RM-01).
    assert "parseInt(form.repeticiones) || 1" not in fuente
