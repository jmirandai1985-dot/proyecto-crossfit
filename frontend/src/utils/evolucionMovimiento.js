/**
 * Agrupación de RMs por MOVIMIENTO dentro de cada categoría, para el acordeón
 * de los cuadrantes del Performance Hub.
 *
 * Antes el cuadrante de categoría dibujaba UN BarChart que mezclaba todos los
 * movimientos de la categoría por semana (tomando el máximo sin importar a qué
 * movimiento pertenecía). Con varios movimientos las barras saltaban de uno a
 * otro sin etiqueta y no se podía ver la progresión real de ninguno.
 *
 * Acá cada movimiento queda separado: su propia lista de puntos (ordenada por
 * fecha) y su propio valor actual / PR. Es código PURO (sin navegador ni red)
 * para poder testearlo aislado.
 */
import { inferirCategoriaRM, valorRM, unidadRM } from './rm.js';
import { diasEntre } from './evolucionRM.js';
import { fechaSolaAInstante, hoyChileStr } from './fecha.js';

export const CATEGORIAS_RM_ORDEN = ['fuerza', 'gimnastico', 'cardio', 'metabolico'];

/**
 * Agrupa los registros de RMs por `movimiento_id` dentro de cada categoría.
 *
 * Devuelve `{ porCategoria, descartados }`:
 *   - porCategoria: { fuerza: [mov, ...], gimnastico: [...], ... }, cada `mov` con
 *     `movimiento_id`, `movimiento_nombre`, `categoria`, `unidad`, `valorActual`,
 *     `registros`, `ultimaFecha`, `puntos` ([{ fecha, valor }] ascendente), `esPR`
 *     y `diasDesdePR`. Dentro de cada categoría: PR más reciente primero.
 *   - descartados: registros con fecha presente pero inválida (misma regla que el
 *     gráfico semanal anterior: sin fecha se omite, fecha ilegible se descarta).
 */
export function agruparMovimientosPorCategoria(registros, hoyStr = hoyChileStr()) {
    const porCategoria = {
        fuerza: [],
        gimnastico: [],
        cardio: [],
        metabolico: [],
    };
    const descartados = [];

    // 1) Agrupar por movimiento_id (los registros que no traen id no se pueden
    //    atribuir a ningún movimiento y se omiten).
    const porMovimiento = new Map();
    (registros || []).forEach((rm) => {
        const id = rm?.movimiento_id;
        if (id === null || id === undefined) return;
        if (!porMovimiento.has(id)) porMovimiento.set(id, []);
        porMovimiento.get(id).push(rm);
    });

    porMovimiento.forEach((registrosMov, movimientoId) => {
        const categoria = inferirCategoriaRM(registrosMov[0]);
        if (!categoria || !porCategoria[categoria]) return;

        // 2) Descartar fechas inválidas y quedarse sólo con los registros útiles.
        const validos = [];
        registrosMov.forEach((rm) => {
            if (!rm?.fecha) return; // sin fecha: se omite (igual que el gráfico anterior)
            const fecha = new Date(rm.fecha);
            if (Number.isNaN(fecha.getTime())) {
                console.error('RM descartado de la evolución por movimiento:', rm?.movimiento_nombre, rm?.fecha);
                descartados.push(rm);
                return;
            }
            validos.push(rm);
        });

        validos.sort((a, b) => fechaSolaAInstante(a.fecha).getTime() - fechaSolaAInstante(b.fecha).getTime());

        if (validos.length === 0) return;

        const valores = validos.map(valorRM);
        const maximo = Math.max(...valores);
        const ultimo = validos[validos.length - 1];
        const valorActual = valorRM(ultimo);
        const esPR = valorActual === maximo;

        // Último PR: el registro más reciente cuyo valor iguala el máximo (no es lo
        // mismo que el último registro si hoy levantó menos que su mejor marca).
        const ultimoPR = [...validos].reverse().find((r) => valorRM(r) === maximo) || ultimo;
        const diasDesdePR = ultimoPR?.fecha ? diasEntre(ultimoPR.fecha, hoyStr) : null;

        porCategoria[categoria].push({
            movimiento_id: movimientoId,
            movimiento_nombre: ultimo?.movimiento_nombre || registrosMov[0]?.movimiento_nombre || '',
            categoria,
            unidad: unidadRM(ultimo),
            valorActual,
            registros: validos.length,
            ultimaFecha: ultimo.fecha,
            puntos: validos.map((r) => ({ fecha: r.fecha, valor: valorRM(r) })),
            esPR,
            diasDesdePR,
        });
    });

    // 3) Dentro de cada categoría: PR más reciente primero (menos días desde el PR).
    CATEGORIAS_RM_ORDEN.forEach((c) => {
        porCategoria[c].sort((a, b) => {
            const ta = a.diasDesdePR === null ? Infinity : a.diasDesdePR;
            const tb = b.diasDesdePR === null ? Infinity : b.diasDesdePR;
            return ta - tb;
        });
    });

    return { porCategoria, descartados };
}

/**
 * Texto corto de contexto del tip "tu RM es tu 100%": varía según cuántos días
 * pasaron desde el último PR. Español neutro (antes estaba en voseo argentino).
 */
export function textoObjetivo(o) {
    const objetivo = `${o.objetivoSugerido} ${o.unidad}`;
    if (o.diasDesdePR === null) {
        return `Primera marca. Tu próximo objetivo: ${objetivo}.`;
    }
    if (o.diasDesdePR <= 7) {
        return `Acabas de marcar un PR. Dale unos días a tu cuerpo antes de ir por ${objetivo} de nuevo.`;
    }
    if (o.diasDesdePR <= 21) {
        return `Vienes progresando bien. Tu próximo objetivo: ${objetivo}.`;
    }
    if (o.diasDesdePR <= 35) {
        return `Llevas ${o.diasDesdePR} días sin marca nueva. Antes de reintentar, prueba variar el estímulo (otro rango de reps o un tempo más lento).`;
    }
    return `Llevas ${o.diasDesdePR} días estancado. Conviene una semana de descarga (40-60% menos volumen) antes de ir por ${objetivo} de nuevo.`;
}
