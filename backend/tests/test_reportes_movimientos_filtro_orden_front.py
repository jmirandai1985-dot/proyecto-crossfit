"""
Reportes → "Detalle de Movimientos": filtro por tipo/categoría y orden por
columna — guard de fuente (test AISLADO: sin red, sin base de datos).

QUÉ FIJA Y POR QUÉ:

  * La tabla del mes se podía LEER pero no ACOTAR: con decenas de movimientos
    había que buscar a ojo. Ahora hay dos selects (tipo y categoría) y las
    columnas Fecha y Monto se ordenan tocando el encabezado.
  * Todo se resuelve EN MEMORIA sobre la lista que la pantalla ya carga
    (`useTransaccionesFinanzas`): no hay endpoint ni request nuevos, así que el
    filtro no puede desincronizarse de los totales del resto de la pantalla.
  * El orden NO muta la lista original: `movimientosList` puede ser el array
    ESTABLE de la caché (`SIN_DATOS`) o el de la query, y ordenarlo in-place
    rompería los memo del hook. Por eso se ordena una copia (`[...filas]`).
  * "Monto" ordena por el NÚMERO, no por el texto: como texto, 1000 < 900.
  * Las categorías del select salen de las filas cargadas (no de una lista fija):
    un movimiento con una categoría nueva se puede filtrar sin tocar la pantalla.
  * El encabezado ordenable es un `<button>` DENTRO del `<th>` (así se toca y se
    teclea sin perder la semántica de la tabla) y el `<th>` lleva `aria-sort`
    (`ascending`/`descending`/`none`), que es lo que anuncia el lector de
    pantalla; conserva `scope="col"`.
  * "Sin resultados por el filtro" tiene mensaje propio + botón para quitarlo:
    mostrar el "Sin movimientos este mes" haría creer que se borraron los datos.
  * Los estados que ya existían ("Cargando..." y "Sin movimientos este mes")
    siguen ahí.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_reportes_movimientos_filtro_orden_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

REPORTES = "frontend/src/pages/admin/Reportes.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── A. Filtro: dos selects que trabajan sobre lo YA cargado ──────────────────

def test_a1_la_tabla_tiene_filtro_por_tipo_y_por_categoria():
    fuente = _fuente(REPORTES)
    assert "const [filtroTipo, setFiltroTipo] = useState('todos');" in fuente
    assert "const [filtroCategoria, setFiltroCategoria] = useState('todas');" in fuente
    assert '<option value="ingreso">Ingresos</option>' in fuente
    assert '<option value="egreso">Egresos</option>' in fuente


def test_a2_el_filtro_es_en_memoria_sobre_la_lista_del_hook():
    fuente = _fuente(REPORTES)
    # Una sola fuente de datos para el detalle (sin un segundo endpoint).
    assert fuente.count("useTransaccionesFinanzas(") == 1
    assert "const movimientosVisibles = useMemo(() => {" in fuente
    assert "movimientosList.filter((m) => (" in fuente
    # La derivación depende SÓLO de la lista cargada + los dos filtros y el orden.
    assert "}, [movimientosList, filtroTipo, filtroCategoria, ordenMovs]);" in fuente


def test_a3_las_categorias_del_select_salen_de_las_filas_cargadas():
    fuente = _fuente(REPORTES)
    assert "[...new Set(movimientosList.map((m) => m.categoria).filter(Boolean))]" in fuente
    assert "{categoriasMovs.map((c) => (" in fuente


# ── B. Orden: copia, número y accesible ─────────────────────────────────────

def test_b1_el_orden_no_muta_la_lista_de_la_cache():
    fuente = _fuente(REPORTES)
    assert "const [ordenMovs, setOrdenMovs] = useState({ campo: 'fecha', dir: 'desc' });" in fuente
    assert "return [...filas].sort((a, b) => {" in fuente, (
        "ordenar in-place el array de la caché rompería los memo del hook")


def test_b2_monto_ordena_por_numero_y_fecha_por_fecha():
    fuente = _fuente(REPORTES)
    assert "if (ordenMovs.campo === 'monto') {" in fuente
    assert "return ((Number(a.monto) || 0) - (Number(b.monto) || 0)) * signo;" in fuente
    # 'YYYY-MM-DD' se compara como fecha, no como texto.
    assert "const fa = Date.parse(a.fecha) || 0;" in fuente
    assert "const fb = Date.parse(b.fecha) || 0;" in fuente


def test_b3_el_encabezado_ordenable_es_boton_con_aria_sort():
    fuente = _fuente(REPORTES)
    assert '<ThOrden campo="fecha" etiqueta="Fecha"' in fuente
    assert '<ThOrden campo="monto" etiqueta="Monto"' in fuente
    assert 'aria-sort={activo ? (orden.dir === \'asc\' ? \'ascending\' : \'descending\') : \'none\'}>' in fuente
    assert 'scope="col"' in fuente
    assert "<button type=\"button\" onClick={() => onOrdenar(campo)}" in fuente


# ── C. Tabla: se pinta lo filtrado y los vacíos se distinguen ───────────────

def test_c1_las_filas_salen_de_la_lista_filtrada_y_ordenada():
    fuente = _fuente(REPORTES)
    assert "movimientosVisibles.map((m, i) => (" in fuente
    assert "${movimientosVisibles.length} de ${movimientosList.length} movimientos" in fuente


def test_c2_sin_resultados_por_el_filtro_no_se_confunde_con_el_mes_vacio():
    fuente = _fuente(REPORTES)
    assert "Sin movimientos este mes" in fuente           # el mes no tiene nada
    assert "Cargando movimientos..." in fuente            # sigue esperando la API
    assert "Ningún movimiento del mes coincide con el filtro." in fuente
    assert "Quitar filtros" in fuente


def test_c3_limpiar_filtros_vuelve_al_estado_inicial():
    fuente = _fuente(REPORTES)
    inicio = fuente.index("const limpiarFiltrosMovs = () => {")
    bloque = fuente[inicio:fuente.index("};", inicio)]
    assert "setFiltroTipo('todos')" in bloque
    assert "setFiltroCategoria('todas')" in bloque
    # El botón de "Limpiar" sólo aparece si hay algo filtrado.
    assert "{hayFiltroMovs && (" in fuente
