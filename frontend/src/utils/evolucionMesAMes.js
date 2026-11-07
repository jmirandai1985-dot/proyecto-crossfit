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

// Meses en 3 letras para la etiqueta corta de cada barra del grid "Mes a mes".
const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

const etiquetaMesCorta = (claveMes) => {
    const mes = Number(String(claveMes || '').slice(5, 7)) - 1;
    return MESES_CORTOS[mes] || claveMes || '';
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
 * Agrupa las marcas por MOVIMIENTO (no por mes) y arma, para cada uno, una serie
 * mensual: una marca representativa por mes (la de mayor valor si hay varias en el
 * mismo mes). Cada punto de la serie trae `mesLabel` ('ago', 'sep'...) y `pct`
 * (% respecto al valor MÁXIMO de la serie de ESE movimiento, reusando pctDeMejora).
 *
 * Devuelve [{ movimiento_id, movimiento_nombre, unidad, valorActual, ultimaFecha,
 * serie: [{ claveMes, mesLabel, valor, pct }] }], ordenado por fecha del último
 * registro (el movimiento con actividad más reciente primero).
 */
export function agruparPorMovimiento(rms) {
    const porMovimiento = new Map();
    (rms || []).forEach((rm) => {
        const id = rm?.movimiento_id;
        if (id === null || id === undefined) return;
        const fecha = toChileFechaStr(fechaSolaAInstante(rm?.fecha));
        if (!fecha) return;
        if (!porMovimiento.has(id)) porMovimiento.set(id, []);
        porMovimiento.get(id).push({
            ...rm,
            valor: valorRM(rm),
            unidad: unidadRM(rm),
            fechaChile: fecha,
            claveMes: fecha.slice(0, 7),
        });
    });

    const resultado = [];
    porMovimiento.forEach((marcas, id) => {
        // Cronológico ascendente (por el día chileno normalizado).
        marcas.sort((a, b) => a.fechaChile.localeCompare(b.fechaChile));

        // Una marca representativa por mes: la de MAYOR valor de ese mes.
        const porMes = new Map();
        marcas.forEach((m) => {
            const actual = porMes.get(m.claveMes);
            if (!actual || m.valor > actual.valor) porMes.set(m.claveMes, m);
        });

        const serie = [...porMes.entries()]
            .sort((a, b) => a[0].localeCompare(b[0]))
            .map(([claveMes, m]) => ({
                claveMes,
                mesLabel: etiquetaMesCorta(claveMes),
                valor: m.valor,
                pct: 0,
            }));

        // pct respecto al valor MÁXIMO de la serie del movimiento.
        const maximo = serie.length ? Math.max(...serie.map((s) => s.valor)) : 0;
        serie.forEach((s) => { s.pct = pctDeMejora(s.valor, maximo); });

        const ultimo = marcas[marcas.length - 1];
        resultado.push({
            movimiento_id: id,
            movimiento_nombre: ultimo?.movimiento_nombre || '',
            unidad: ultimo?.unidad || '',
            valorActual: ultimo?.valor ?? 0,
            ultimaFecha: ultimo?.fechaChile || null,
            serie,
        });
    });

    // El movimiento con actividad más reciente primero.
    resultado.sort((a, b) => {
        const ta = a.ultimaFecha ? fechaSolaAInstante(a.ultimaFecha).getTime() : NaN;
        const tb = b.ultimaFecha ? fechaSolaAInstante(b.ultimaFecha).getTime() : NaN;
        return (Number.isNaN(tb) ? -Infinity : tb) - (Number.isNaN(ta) ? -Infinity : ta);
    });

    return resultado;
}

/**
 * Marcas de UN movimiento (para el panel de detalle del grid "Mes a mes").
 *
 * Filtra `rms` por `movimiento_id`, resuelve `valor`/`unidad` de cada marca y las
 * ordena cronológicamente (más antigua primero). Marca `esMejor: true` en la(s)
 * marca(s) que igualan el valor MÁXIMO de ese movimiento.
 */
export function marcasDeMovimiento(rms, movimientoId) {
    const marcas = (rms || [])
        .filter((rm) => rm?.movimiento_id === movimientoId)
        .map((rm) => ({ ...rm, valor: valorRM(rm), unidad: unidadRM(rm) }))
        .sort((a, b) => fechaSolaAInstante(a.fecha).getTime() - fechaSolaAInstante(b.fecha).getTime());

    const maximo = marcas.length ? Math.max(...marcas.map((m) => m.valor)) : 0;
    return marcas.map((m) => ({ ...m, esMejor: m.valor === maximo }));
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
