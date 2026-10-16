"""El tab Progreso del coach enriquece la página visible con UNA request (lote), no con 50.

QUÉ CAMBIÓ (auditoría 2026-10-15)
--------------------------------
La tabla de Progreso pedía, por CADA alumno de la página (25), dos requests: sus RMs
(`/historial-rm/alumnos/{id}/rms`) y su nivel (`/historial-rm/alumnos/{id}/nivel-general`) = 50
requests por página, con ~4 consultas cada uno. Ahora es UNA request
(`GET /historial-rm/progreso-lote?alumno_ids=…`) y 5 consultas para toda la página.

Los VALORES no cambian: `mejor_rm_por_movimiento` delega en `mejor_rm_por_movimiento_lote` y
`calcular_nivel_general` en `nivel_desde_mejores` + `_mejores_rms_lote` — las versiones de lote
son el MISMO código con `IN (...)`. El buscador, el filtro de nivel y la paginación siguen igual.

QUÉ SE FIJA ACÁ
  A. PURAS (sin BD): `nivel_desde_mejores` —el reductor de nivel— con datos sintéticos: el nivel
     por movimiento, el "más bajo" entre movimientos, "Sin datos" sin peso/género y que el orden
     de las marcas no altera el resultado.
  B. FUENTE (sin BD): las cuatro delegaciones (RMs y nivel, individual -> lote) y el endpoint, con
     el ORDEN de rutas que necesita (`/progreso-lote` antes de `/{historial_id}`).
  C. FRONTEND (sin BD): el hook hace UNA request al lote y ya no tiene el bucle por alumno.

Correr (aislado y sin base):
    cd backend && py -3.12 -m pytest tests/test_progreso_lote.py -q --noconftest
"""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
API = "backend/app/api/v1/historial_rm.py"
NIVELES = "backend/app/services/nivel_service.py"
RMS = "backend/app/services/rms_service.py"
QUERIES = "frontend/src/hooks/queries.js"

# Movimientos REALES de las tablas de niveles (M 80 kg: Back Squat Elite = 2.5x).
BACK_SQUAT = "Back Squat (Sentadilla Trasera)"
FRONT_SQUAT = "Front Squat (Sentadilla Frontal)"
PULL_UPS = "Pull-ups (Dominadas)"


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def _cuerpos(fuente: str) -> dict:
    return {n.name: ast.get_source_segment(fuente, n)
            for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)}


def _hook_progreso() -> str:
    """El código del hook de Progreso (de `export function` al siguiente `export`)."""
    fuente = _fuente(QUERIES)
    desde = fuente.index("export function useProgresoAlumnosCoach")
    resto = fuente[desde:]
    hasta = resto.find("\nexport ", 1)
    return resto[:hasta if hasta != -1 else len(resto)]


# ── A. El reductor de nivel (puro) ────────────────────────────────────────────
def test_a1_nivel_por_movimiento():
    from app.services.nivel_service import nivel_desde_mejores

    # Back Squat 200 kg con 80 kg de peso corporal = ratio 2.5 -> Elite (M).
    fuerza = nivel_desde_mejores([(1, 200.0, BACK_SQUAT)], 80, "M")
    assert fuerza["nivel_fuerza"] == "Elite"
    assert fuerza["nivel_gimnastico"] == "Sin datos"

    # 10 pull-ups = Intermedio (M: 1 / 10 / 20 / 30).
    gimnasia = nivel_desde_mejores([(2, 10.0, PULL_UPS)], 80, "M")
    assert gimnasia["nivel_gimnastico"] == "Intermedio"
    assert gimnasia["nivel_fuerza"] == "Sin datos"


def test_a2_gana_el_nivel_mas_bajo_entre_movimientos():
    from app.services.nivel_service import nivel_desde_mejores

    # Back Squat (Elite) + Front Squat 60 kg (ratio 0.75 -> Principiante): el grupo cae al más bajo.
    resultado = nivel_desde_mejores(
        [(1, 200.0, BACK_SQUAT), (2, 60.0, FRONT_SQUAT)], 80, "M")
    assert resultado["nivel_fuerza"] == "Principiante"
    assert len(resultado["detalle_fuerza"]) == 2


def test_a3_el_orden_de_las_marcas_no_altera_el_nivel():
    from app.services.nivel_service import nivel_desde_mejores

    marcas = [(1, 200.0, BACK_SQUAT), (2, 60.0, FRONT_SQUAT), (3, 10.0, PULL_UPS)]
    directo = nivel_desde_mejores(marcas, 80, "M")
    invertido = nivel_desde_mejores(list(reversed(marcas)), 80, "M")
    assert (directo["nivel_fuerza"], directo["nivel_gimnastico"]) == (
        invertido["nivel_fuerza"], invertido["nivel_gimnastico"])
    assert directo["nivel_gimnastico"] == "Intermedio"


def test_a4_sin_peso_o_genero_no_hay_nivel_de_fuerza():
    from app.services.nivel_service import nivel_desde_mejores

    sin_peso = nivel_desde_mejores([(1, 200.0, BACK_SQUAT)], None, "M")
    assert sin_peso["nivel_fuerza"] == "Sin datos"
    # La gimnasia NO necesita peso corporal: sigue calculando.
    assert nivel_desde_mejores([(2, 10.0, PULL_UPS)], None, "M")["nivel_gimnastico"] == "Intermedio"


def test_a5_sin_marcas_todo_sin_datos():
    from app.services.nivel_service import nivel_desde_mejores

    vacio = nivel_desde_mejores([], 80, "M")
    assert vacio == {"nivel_fuerza": "Sin datos", "nivel_gimnastico": "Sin datos",
                     "detalle_fuerza": [], "detalle_gimnastico": []}


# ── B. UNA definición: la de a uno delega en la del lote ──────────────────────
def test_b1_los_rms_de_uno_son_el_lote_de_un_id():
    svc = _fuente(RMS)
    cuerpos = _cuerpos(svc)
    assert "mejor_rm_por_movimiento_lote(" in cuerpos["mejor_rm_por_movimiento"]
    assert "HistorialRM.alumno_id.in_(ids)" in svc
    # DISTINCT ON de PostgreSQL por (alumno, movimiento): el mismo criterio, con el lote.
    assert ".distinct(HistorialRM.alumno_id, HistorialRM.movimiento_id)" in svc
    # `Row` no soporta slicing: la fila se convierte a tupla antes de recortar el `alumno_id`.
    assert "_fila_a_dict(tuple(fila)[1:])" in svc


def test_b2_el_nivel_de_uno_es_el_lote_de_un_id():
    svc = _fuente(NIVELES)
    cuerpos = _cuerpos(svc)
    assert "nivel_desde_mejores(" in cuerpos["calcular_nivel_general"]
    assert "_mejores_rms_lote(" in cuerpos["calcular_nivel_general"]
    assert "nivel_desde_mejores(" in cuerpos["calcular_niveles_lote"]
    assert "HistorialRM.alumno_id.in_(ids)" in cuerpos["_mejores_rms_lote"]
    assert "Usuario.id.in_(ids)" in cuerpos["calcular_niveles_lote"]


def test_b3_el_endpoint_del_lote_esta_antes_del_de_un_id():
    """FastAPI resuelve por orden: si `/{historial_id}` quedara primero, "progreso-lote" -> 422."""
    fuente = _fuente(API)
    assert '@router.get("/progreso-lote"' in fuente
    assert (fuente.index('@router.get("/progreso-lote"')
            < fuente.index('@router.get("/{historial_id}"'))
    lote = _cuerpos(fuente)["progreso_lote"]
    assert "mejor_rm_por_movimiento_lote(" in lote
    assert "calcular_niveles_lote(" in lote
    assert "MAX_ALUMNOS_LOTE" in lote                     # tope defensivo
    assert "_verificar_acceso_alumno(current_user, alumno_id)" in lote   # candado por alumno
    assert "Usuario.tenant_id == tenant_id" in lote       # sólo alumnos del box del token


def test_b4_el_endpoint_no_recalcula_a_mano():
    """El endpoint sólo compone: el RM lo define `rms_service` y el nivel `nivel_service`."""
    lote = _cuerpos(_fuente(API))["progreso_lote"]
    assert "CROSSFIT_RATIOS" not in lote and "CROSSFIT_HABILIDADES" not in lote
    assert "HistorialRM" not in lote


# ── C. El frontend pide el lote ───────────────────────────────────────────────
def test_c1_el_hook_hace_una_sola_request():
    hook = _hook_progreso()
    assert "'/api/v1/historial-rm/progreso-lote'" in hook
    assert "alumno_ids: ids" in hook
    assert hook.count("api.get(") == 1, "el hook volvió a pedir por alumno"


def test_c2_el_hook_ya_no_pide_por_alumno():
    hook = _hook_progreso()
    assert "/nivel-general" not in hook
    assert "alumnos/${alumno.id}" not in hook
    assert "Promise.all(lista.map" not in hook


def test_c3_el_hook_conserva_el_contrato_de_la_tabla():
    """Las claves que consume `DashboardCoach` (y el filtro de nivel) siguen saliendo del hook."""
    hook = _hook_progreso()
    for clave in ("total_rms", "rms", "nivel_fuerza", "nivel_gimnastico", "estado",
                  "nivel: nivelDeAtleta("):
        assert clave in hook, f"el hook dejó de exponer {clave}"

