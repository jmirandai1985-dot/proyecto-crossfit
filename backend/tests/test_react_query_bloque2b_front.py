"""Fase 2 · Bloque 2 parte B (Pizarra de WOD del coach).

Guard de fuente del FRONTEND (sin red y sin base):

  A. Los hooks del bloque EXISTEN y usan SU clave (todas en el objeto `claves`).
  B. La Pizarra consume `useMovimientos` (la MISMA caché que el Dashboard del coach y
     las pantallas de marcas) y ya no pide el catálogo con axios ni sincroniza
     `cargando/error` a mano: el estado de carga sale de la mutación.
  C. Las mutaciones mueven las familias correctas: crear un movimiento ->
     `['movimientos']`; publicar/editar un WOD -> `['wods']` + `['clases']`; el parser
     no invalida NADA (devuelve una propuesta, no guarda).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_react_query_bloque2b_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
QUERIES = "frontend/src/hooks/queries.js"
PIZARRA = "frontend/src/pages/coach/Pizarra.jsx"

# (hook, clave que debe usar en el queryKey de su useQuery)
HOOKS_QUERY = [("useMovimientos", "claves.movimientos")]
HOOKS_MUTACION = ["useCrearMovimiento", "useParsearWod", "useCrearWod"]


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_a_los_hooks_existen_y_usan_su_clave():
    q = _fuente(QUERIES)
    for hook, clave in HOOKS_QUERY:
        assert f"export function {hook}(" in q, f"falta el hook {hook}"
        assert f"queryKey: {clave}," in q, f"{hook} no usa la clave {clave}"
    for hook in HOOKS_MUTACION:
        assert f"export function {hook}(" in q, f"falta la mutación {hook}"
    assert "    movimientos: ['movimientos']," in q, "falta la clave del catálogo"


def test_b_la_pizarra_consume_los_hooks():
    fuente = _fuente(PIZARRA)
    # Se fue el axios a mano y con él los efectos de carga.
    for prohibido in ("services/api", "api.get(", "api.post(", "api.put(",
                      "api.delete(", "useEffect(", "useCallback("):
        assert prohibido not in fuente, f"Pizarra todavía usa {prohibido}"
    # Catálogo compartido: se DERIVA de la consulta (no se siembra en un estado propio).
    assert "const movimientosQ = useMovimientos();" in fuente
    assert "const movimientosDisponibles = movimientosQ.data || [];" in fuente
    assert "setMovimientosDisponibles" not in fuente, (
        "el catálogo ya no se guarda en un estado propio (viene de la consulta)")
    # Las tres mutaciones y el "cargando" derivado de ellas.
    for linea in ("const crearMovimiento = useCrearMovimiento();",
                  "const parsearWod = useParsearWod();",
                  "const publicarWod = useCrearWod();",
                  "const procesando = parsearWod.isPending;",
                  "const guardando = publicarWod.isPending;",
                  "await parsearWod.mutateAsync(",
                  "await crearMovimiento.mutateAsync(",
                  "await publicarWod.mutateAsync(payload);"):
        assert linea in fuente, f"falta: {linea}"
    for muerto in ("setGuardando", "setProcesando"):
        assert muerto not in fuente, f"quedó el estado sincronizado a mano {muerto}"


def test_c_las_mutaciones_mueven_las_familias_correctas():
    q = _fuente(QUERIES)
    # Crear un movimiento refresca el catálogo (el combo de las tres pantallas).
    assert "onSuccess: () => qc.invalidateQueries({ queryKey: claves.movimientos })," in q
    # Publicar/editar un WOD: la familia de WODs Y la de clases (el vínculo clase↔wod).
    assert ("function invalidarWodsYClases(qc) {\n"
            "    qc.invalidateQueries({ queryKey: ['wods'] });\n"
            "    qc.invalidateQueries({ queryKey: ['clases'] });\n"
            "}") in q
    for hook in ("useCrearWod", "useGuardarWod", "useCrearWodsBatch"):
        bloque = q.split(f"export function {hook}(")[1].split("\nexport function")[0]
        assert "onSuccess: () => invalidarWodsYClases(qc)," in bloque, (
            f"{hook} no refresca WODs + clases")
    # El parser es una ORDEN (no guarda): no invalida nada.
    parser = q.split("export function useParsearWod(")[1].split("\nexport function")[0]
    assert "invalidateQueries" not in parser, (
        "el parser no debe invalidar caché: devuelve una propuesta, no guarda nada")
