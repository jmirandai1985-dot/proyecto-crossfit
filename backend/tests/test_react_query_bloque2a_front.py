"""Fase 2 · Bloque 2 parte A (Asistencia de clases + entrega de pedidos).

Guard de fuente del FRONTEND (sin red y sin base):

  A. Los hooks del bloque EXISTEN y usan SU clave (todas en el objeto `claves`).
  B. `AsistenciaClases` (pestaña compartida coach + admin) consume los hooks, ya no pide
     nada con axios ni sincroniza `cargando/error` a mano, y el marcado de la clase se
     DERIVA del backend: `overrides` guarda sólo lo que toca el usuario.
  C. Las mutaciones mueven las familias correctas: confirmar asistencia -> `['asistencia']`
     (lista del día + detalle de la clase); ampliar cupo -> `['clases']` y `['asistencia']`;
     entregar pedido -> `['pedidos']` (el panel del admin ve la entrega del coach).
  D. `ModalEntregarPedido` (compartido por el mesón del coach y el panel del admin) entrega
     con la mutación, no con un POST a mano.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_react_query_bloque2a_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
QUERIES = "frontend/src/hooks/queries.js"
ASISTENCIA = "frontend/src/components/AsistenciaClases.jsx"
MODAL = "frontend/src/components/ModalEntregarPedido.jsx"
ENTREGAR = "frontend/src/pages/coach/EntregarPedido.jsx"

# (hook, clave que debe usar)
HOOKS = [
    ("useClasesAsistenciaHoy", "claves.clasesAsistenciaHoy"),
    ("useAlumnosDeClase", "claves.alumnosDeClase(claseId)"),
    ("useConfirmarAsistenciaClase", None),      # mutación: no lleva queryKey
    ("useAmpliarCupo", None),                   # mutación
    ("useEntregarPedido", None),                # mutación
]


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_a_los_hooks_existen_y_usan_su_clave():
    q = _fuente(QUERIES)
    for hook, clave in HOOKS:
        assert f"export function {hook}(" in q, f"falta el hook {hook}"
        if clave:
            assert f"queryKey: {clave}," in q, f"{hook} no usa la clave {clave}"
    for clave in ("clasesAsistenciaHoy:", "alumnosDeClase:"):
        assert f"    {clave}" in q, f"falta la clave {clave} en el objeto `claves`"


def test_b_la_pestana_de_asistencia_consume_los_hooks():
    fuente = _fuente(ASISTENCIA)
    for hook in ("useClasesAsistenciaHoy(", "useAlumnosDeClase(",
                 "useConfirmarAsistenciaClase(", "useAmpliarCupo("):
        assert hook in fuente, f"AsistenciaClases no usa {hook}"
    for prohibido in ("services/api", "api.get(", "api.post(", "api.put(",
                      "api.delete(", "useEffect(", "useCallback("):
        assert prohibido not in fuente, f"AsistenciaClases todavía usa {prohibido}"
    # Cargando/error derivados de las consultas, no de estados sincronizados a mano.
    assert "const cargando = clasesQ.isPending;" in fuente
    assert "const error = clasesQ.isError" in fuente
    assert "const cargandoReservas = Boolean(claseSeleccionada) && alumnosQ.isPending;" in fuente
    # El marcado: base del backend + overrides sólo con lo que el usuario decide.
    assert "const [overrides, setOverrides] = useState({});" in fuente
    assert "reservaId in overrides ? overrides[reservaId]" in fuente
    assert "setAsistencias(" not in fuente, (
        "el marcado ya no se siembra en un estado propio (se deriva del backend)")
    # Y se fue el estado muerto que nadie leía.
    assert "clasesMarcadas" not in fuente


def test_c_las_mutaciones_mueven_las_familias_correctas():
    q = _fuente(QUERIES)
    # Confirmar asistencia: lista del día + detalle de la clase abierta.
    assert "onSuccess: () => qc.invalidateQueries({ queryKey: ['asistencia'] })," in q
    # Ampliar cupo: la lista de clases y la del día que se está mirando.
    assert "qc.invalidateQueries({ queryKey: ['clases'] });" in q
    # Entregar pedido: la lista del admin.
    assert "onSuccess: () => qc.invalidateQueries({ queryKey: ['pedidos'] })," in q
    # El detalle de la clase cuelga de `['asistencia']` para que confirmar lo refresque.
    assert "alumnosDeClase: (claseId) => ['asistencia', 'clase', claseId, 'alumnos']," in q


def test_d_el_modal_compartido_entrega_con_la_mutacion():
    fuente = _fuente(MODAL)
    assert "useEntregarPedido(" in fuente
    assert "await entregarPedido.mutateAsync(limpio)" in fuente
    assert "services/api" not in fuente and "api.post(" not in fuente
    assert "const entregando = entregarPedido.isPending;" in fuente
    # El mesón del coach monta el MISMO modal (no tiene llamadas propias a la API).
    pantalla = _fuente(ENTREGAR)
    assert "ModalEntregarPedido" in pantalla
    assert "services/api" not in pantalla and "api.post(" not in pantalla
