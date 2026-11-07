/**
 * Vista "Mes a mes" de Evolución — agrupa TODAS las marcas de RM por año/mes.
 *
 * POR QUÉ EXISTE: el resto de Evolución resume por movimiento; acá se muestran las
 * marcas tal cual cayeron en el calendario, mes a mes, con un buscador de movimiento
 * y una barra que indica qué % del mejor RM del movimiento es cada marca.
 *
 * Las fechas se agrupan en horario de CHILE (reusa `utils/fecha.js`, igual que el
 * resto de la app). El valor/unidad de cada RM sale de `utils/rm.js` (fuente única).
 */
import { valorRM, unidadRM } from './rm.js';
import { fechaSolaAInstante, toChileFechaStr } from './fecha.js';

const MESES = [
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
];

const etiquetaMes = (clave) => {
    const [anio, mes] = String(clave || '').split('-');
    const idx = Number(mes) - 1;
    return MESES[idx] != null ? `${MESES[idx]} ${anio}` : clave || '';
};

/**
 * Agrupa las marcas por año y mes ('YYYY-MM'), el más reciente primero. Cada grupo
 * trae `clave`, `anio`, `mes`, `label` ('Noviembre 2026') y `registros` (marcas con
 * `valor`/`unidad` ya resueltos). Las fechas ilegibles se descartan (no hay mes).
 */
export function agruparPorAnioYMes(rms) {
    const grupos = new Map();
    (rms || []).forEach((rm) => {
        const fecha = toChileFechaStr(fechaSolaAInstante(rm?.fecha));
        if (!fecha) return;
        const clave = fecha.slice(0, 7); // 'YYYY-MM'
        if (!grupos.has(clave)) grupos.set(clave, []);
        grupos.get(clave).push({ ...rm, valor: valorRM(rm), unidad: unidadRM(rm) });
    });
    return [...grupos.entries()]
        .sort((a, b) => b[0].localeCompare(a[0])) // 'YYYY-MM' descendente
        .map(([clave, registros]) => ({
            clave,
            anio: clave.slice(0, 4),
            mes: clave.slice(5, 7),
            label: etiquetaMes(clave),
            registros,
        }));
}

/**
 * Filtra los grupos por nombre de movimiento (case-insensitive). Devuelve la misma
 * forma que `agruparPorAnioYMes`; los meses que quedan sin marcas se descartan.
 */
export function filtrarPorMovimiento(gruposPorMes, textoBusqueda) {
    const q = String(textoBusqueda || '').trim().toLowerCase();
    if (!q) return gruposPorMes || [];
    return (gruposPorMes || [])
        .map((g) => ({
            ...g,
            registros: (g.registros || []).filter((r) =>
                String(r?.movimiento_nombre || '').toLowerCase().includes(q)),
        }))
        .filter((g) => g.registros.length > 0);
}

/**
 * % de la mejor marca de un movimiento que representa `valor` (para la barra de
 * progreso). El mejor RM del movimiento es el 100%; sin mejor marca → 0.
 */
export function pctDeMejora(valor, mejorMarcaDelMovimiento) {
    const v = Number(valor) || 0;
    const m = Number(mejorMarcaDelMovimiento) || 0;
    if (!m) return 0;
    return Math.round((v / m) * 100);
}
