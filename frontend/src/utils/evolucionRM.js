/**
 * Evolución de RMs por MOVIMIENTO — cálculos del Performance Hub (Fase 2, Bloque 2).
 *
 * POR QUÉ EXISTE: los cuadrantes del Performance Hub agrupan por CATEGORÍA y el gráfico
 * semanal mezcla movimientos distintos. Acá se compara, por cada movimiento individual,
 * el último registro contra el anterior de ESE MISMO movimiento. Eso es una mejora real:
 * a diferencia de un WOD (cuyo contenido cambia cada vez), un RM es siempre el mismo
 * ejercicio.
 *
 * H-03: la categoría/valor/unidad de un RM NO se recalculan acá; salen de `utils/rm.js`
 * (la única fuente de verdad). `hoy` se inyecta (default: calendario de Chile) para que
 * los días sin testear se puedan probar sin depender del reloj.
 */
import { inferirCategoriaRM, unidadRM, valorRM } from './rm.js';
import { fechaSolaAInstante, hoyChileStr } from './fecha.js';

const MS_DIA = 24 * 60 * 60 * 1000;

/**
 * Días enteros entre dos fechas 'YYYY-MM-DD', ancladas a MEDIODÍA UTC (misma regla que
 * `fmtFechaCortaChile`) para que la zona horaria del navegador no las corra un día.
 * Devuelve `null` si alguna fecha es ilegible.
 */
export function diasEntre(fechaDesde, fechaHasta) {
    const a = fechaSolaAInstante(fechaDesde);
    const b = fechaSolaAInstante(fechaHasta);
    if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
    return Math.max(0, Math.round((b.getTime() - a.getTime()) / MS_DIA));
}

/**
 * Nombre de un movimiento normalizado para comparar pares conocidos: minúsculas y sin la
 * aclaración entre paréntesis ("Back Squat (Sentadilla Trasera)" → "back squat").
 */
export function nombreComparable(nombre) {
    return String(nombre || '')
        .toLowerCase()
        .replace(/\s*\([^)]*\)/g, '')
        .trim();
}

// Pares de movimientos que se comparan en el tip gris ("comparación"). Hardcodeados a
// propósito: son las relaciones de fuerza que más miran los coaches; no hace falta tabla.
const PARES_COMPARACION = [
    ['Back Squat', 'Front Squat'],
    ['Snatch', 'Clean'],
    ['Deadlift', 'Back Squat'],
];

/**
 * Agrupa el historial de RMs por `movimiento_id` y devuelve, por movimiento, el resumen
 * para la sección "Evolución por movimiento". Orden: por fecha del último registro, el más
 * reciente primero (los que no tienen fecha legible quedan al final).
 */
export function evolucionPorMovimiento(registros, hoyStr = hoyChileStr()) {
    const grupos = new Map();
    (registros || []).forEach((rm) => {
        const id = rm?.movimiento_id;
        if (id === null || id === undefined) return;
        if (!grupos.has(id)) grupos.set(id, []);
        grupos.get(id).push(rm);
    });

    const resumenes = [];
    grupos.forEach((registrosMov, movimientoId) => {
        const ordenados = registrosMov.slice().sort((a, b) => {
            const ta = a?.fecha ? fechaSolaAInstante(a.fecha).getTime() : NaN;
            const tb = b?.fecha ? fechaSolaAInstante(b.fecha).getTime() : NaN;
            return (Number.isNaN(ta) ? Infinity : ta) - (Number.isNaN(tb) ? Infinity : tb);
        });

        const ultimo = ordenados[ordenados.length - 1];
        const penultimo = ordenados.length >= 2 ? ordenados[ordenados.length - 2] : null;
        const valores = ordenados.map(valorRM);
        const maximo = valores.length ? Math.max(...valores) : null;

        const valorActual = valorRM(ultimo);
        const valorAnterior = penultimo ? valorRM(penultimo) : null;
        // % de mejora contra el registro anterior de ESE MISMO movimiento; null cuando no
        // hay registro previo (el movimiento se lista igual, como "primera marca").
        const pctCambio = valorAnterior
            ? ((valorActual - valorAnterior) / valorAnterior) * 100
            : null;

        resumenes.push({
            movimiento_id: movimientoId,
            movimiento_nombre: ultimo?.movimiento_nombre || '',
            categoria: inferirCategoriaRM(ultimo),
            valorActual,
            valorAnterior,
            pctCambio,
            esPR: maximo !== null && valorActual === maximo,
            diasSinTestear: ultimo?.fecha ? diasEntre(ultimo.fecha, hoyStr) : null,
            registros: ordenados.length,
            ultimaFecha: ultimo?.fecha || null,
            unidad: unidadRM(ultimo),
        });
    });

    resumenes.sort((a, b) => {
        const ta = a.ultimaFecha ? fechaSolaAInstante(a.ultimaFecha).getTime() : NaN;
        const tb = b.ultimaFecha ? fechaSolaAInstante(b.ultimaFecha).getTime() : NaN;
        return (Number.isNaN(tb) ? -Infinity : tb) - (Number.isNaN(ta) ? -Infinity : ta);
    });

    return resumenes;
}

/**
 * Tips de la sección "Para ti", derivados de los resúmenes de `evolucionPorMovimiento`.
 *
 *  - logro (verde):    el movimiento con mayor % de mejora, si hay alguno > 0.
 *  - alerta (naranja): el movimiento con más días sin testear, si > 30 y ya tiene al menos
 *                      un registro previo.
 *  - comparacion (gris): un par conocido cuyos % de mejora (ambos positivos) difieren en
 *                      más de 2x entre sí. Navega al movimiento que quedó más rezagado.
 */
export function tipsEvolucion(resumenes) {
    const tips = [];

    const mejor = (resumenes || [])
        .filter((r) => r.pctCambio !== null && r.pctCambio > 0)
        .reduce((acc, r) => (!acc || r.pctCambio > acc.pctCambio ? r : acc), null);
    if (mejor) {
        tips.push({
            tipo: 'logro',
            color: 'verde',
            icono: '🚀',
            titulo: 'Tu mayor mejora',
            detalle: `${mejor.movimiento_nombre} subió ${mejor.pctCambio.toFixed(1)}% respecto a tu registro anterior.`,
            movimientoId: mejor.movimiento_id,
        });
    }

    const sinTestear = (resumenes || [])
        .filter((r) => r.diasSinTestear !== null && r.diasSinTestear > 30 && r.registros >= 2)
        .reduce((acc, r) => (!acc || r.diasSinTestear > acc.diasSinTestear ? r : acc), null);
    if (sinTestear) {
        tips.push({
            tipo: 'alerta',
            color: 'naranja',
            icono: '⚠️',
            titulo: 'Hace tiempo que no lo testeás',
            detalle: `Llevás ${sinTestear.diasSinTestear} días sin registrar ${sinTestear.movimiento_nombre}.`,
            movimientoId: sinTestear.movimiento_id,
        });
    }

    PARES_COMPARACION.forEach(([nombreIzq, nombreDer]) => {
        const a = (resumenes || []).find((r) => nombreComparable(r.movimiento_nombre) === nombreComparable(nombreIzq));
        const b = (resumenes || []).find((r) => nombreComparable(r.movimiento_nombre) === nombreComparable(nombreDer));
        if (!a || !b) return;
        if (a.pctCambio === null || b.pctCambio === null) return;
        if (!(a.pctCambio > 0 && b.pctCambio > 0)) return;
        const mayor = a.pctCambio >= b.pctCambio ? a : b;
        const menor = a.pctCambio >= b.pctCambio ? b : a;
        if (mayor.pctCambio > menor.pctCambio * 2) {
            tips.push({
                tipo: 'comparacion',
                color: 'gris',
                icono: '📊',
                titulo: 'Un par desparejo',
                detalle: `${mayor.movimiento_nombre} avanzó ${mayor.pctCambio.toFixed(1)}% y ${menor.movimiento_nombre} solo ${menor.pctCambio.toFixed(1)}%. Revisá qué está frenando a ${menor.movimiento_nombre}.`,
                movimientoId: menor.movimiento_id,
            });
        }
    });

    return tips;
}

