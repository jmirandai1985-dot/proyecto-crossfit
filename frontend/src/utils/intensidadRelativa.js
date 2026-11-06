/**
 * Intensidad relativa (%RM) de los WODs — cuánto de su propio RM usa el alumno.
 *
 * POR QUÉ EXISTE: el Performance Hub ya muestra la evolución de RMs PUROS (cuánto
 * levantó en un test). Esta métrica es DISTINTA y complementaria: cuánto representa
 * la carga que el alumno movió DENTRO de un WOD real respecto a su RM vigente en esa
 * fecha. Fórmula:
 *
 *     %RM = valor_prescrito_en_el_wod / RM_vigente_en_esa_fecha × 100
 *
 * Solo aplica a `fuerza` (kg) y `gimnastico` (reps); cardio/metabólico se excluyen
 * a propósito (decisión explícita). "RM vigente" es el RM MÁS RECIENTE de ese
 * movimiento con `fecha <= fecha_del_wod` (nunca el RM actual para un WOD viejo).
 *
 * El valor del RM sale de `rm.js` (`valorRM`), la MISMA fuente de verdad que el resto
 * de la pantalla (no se reimplementa la heurística por categoría).
 */
import { valorRM } from './rm.js';
import { fechaSolaAInstante } from './fecha.js';

/**
 * El RM VIGENTE de un movimiento a una fecha: el más reciente con
 * `fecha <= fechaPrescripcion`. Devuelve `null` si todavía no había RM previo.
 */
export function rmVigente(rmsDelMovimiento, fechaPrescripcion) {
    const instante = fechaSolaAInstante(fechaPrescripcion);
    if (Number.isNaN(instante.getTime())) return null;
    let vigente = null;
    (rmsDelMovimiento || []).forEach((rm) => {
        const t = rm?.fecha ? fechaSolaAInstante(rm.fecha).getTime() : NaN;
        if (Number.isNaN(t)) return;
        if (t <= instante.getTime()) {
            if (!vigente || t > fechaSolaAInstante(vigente.fecha).getTime()) {
                vigente = rm;
            }
        }
    });
    return vigente;
}

/**
 * Intensidad relativa por movimiento.
 *
 * `prescripciones` es lo que devuelve `GET /api/v1/wods/intensidad-relativa`
 * (`{ fecha, wod_id, movimiento_id, movimiento_nombre, categoria, valor_prescrito }`);
 * `historialRm` es el historial de RMs del alumno. Devuelve, por movimiento, sus
 * puntos (ordenados cronológicamente) y el %RM del WOD más reciente y del anterior.
 *
 * Sin RM previo a la fecha del WOD → esa prescripción se descarta.
 */
export function intensidadRelativaPorMovimiento(prescripciones, historialRm) {
    const rmsPorMovimiento = new Map();
    (historialRm || []).forEach((rm) => {
        const id = rm?.movimiento_id;
        if (id === null || id === undefined) return;
        if (!rmsPorMovimiento.has(id)) rmsPorMovimiento.set(id, []);
        rmsPorMovimiento.get(id).push(rm);
    });

    const grupos = new Map();
    (prescripciones || []).forEach((p) => {
        const id = p?.movimiento_id;
        if (id === null || id === undefined) return;
        const vigente = rmVigente(rmsPorMovimiento.get(id) || [], p.fecha);
        if (!vigente) return;
        const rm = valorRM(vigente);
        if (!rm) return;  // RM sin valor legible: no se puede calcular el %
        const pctRM = Math.round((Number(p.valor_prescrito) / rm) * 100 * 10) / 10;

        if (!grupos.has(id)) {
            grupos.set(id, {
                movimiento_id: id,
                movimiento_nombre: p.movimiento_nombre || null,
                categoria: p.categoria || null,
                unidad: p.categoria === 'gimnastico' ? 'reps' : 'kg',
                puntos: [],
            });
        }
        grupos.get(id).puntos.push({
            fecha: p.fecha,
            wod_id: p.wod_id,
            valor_prescrito: p.valor_prescrito,
            pctRM,
        });
    });

    const resumenes = [];
    grupos.forEach((grupo) => {
        // Cronológico ascendente (por fecha del WOD).
        grupo.puntos.sort((a, b) => {
            const ta = a.fecha ? fechaSolaAInstante(a.fecha).getTime() : NaN;
            const tb = b.fecha ? fechaSolaAInstante(b.fecha).getTime() : NaN;
            return (Number.isNaN(ta) ? Infinity : ta) - (Number.isNaN(tb) ? Infinity : tb);
        });
        const ultimo = grupo.puntos[grupo.puntos.length - 1];
        const anterior = grupo.puntos.length >= 2 ? grupo.puntos[grupo.puntos.length - 2] : null;
        resumenes.push({
            ...grupo,
            ultimoPct: ultimo.pctRM,
            anteriorPct: anterior ? anterior.pctRM : null,
            ultimaFecha: ultimo.fecha || null,
        });
    });

    // Por movimiento: el del WOD más reciente primero.
    resumenes.sort((a, b) => {
        const ta = a.ultimaFecha ? fechaSolaAInstante(a.ultimaFecha).getTime() : NaN;
        const tb = b.ultimaFecha ? fechaSolaAInstante(b.ultimaFecha).getTime() : NaN;
        return (Number.isNaN(tb) ? -Infinity : tb) - (Number.isNaN(ta) ? -Infinity : ta);
    });

    return resumenes;
}
