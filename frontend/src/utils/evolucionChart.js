/**
 * Datos del gráfico "Progreso de RM" (Evolución) — puros, sin navegador ni red.
 *
 * POR QUÉ EXISTE como utilidad propia: Recharts indexa el tooltip por el valor
 * del `dataKey` del XAxis. Con `dataKey="fecha"`, dos registros del MISMO día
 * colapsan al primero (el tooltip siempre mostraba el primer valor de los
 * duplicados). Acá cada punto lleva una clave única `x` (su índice) y la fecha
 * se conserva aparte para formatearla, de modo que cada punto conserva su
 * propio valor aunque comparta fecha con otro.
 */
import { etiquetaValorRM, valorRM } from './rm.js';

export function getChartData(historialRM) {
    if (!historialRM || !historialRM.length) return [];
    return historialRM.map((r, idx) => {
        const valor = valorRM(r);
        let trend = 'neutral';
        if (idx > 0) {
            const prevValor = valorRM(historialRM[idx - 1]);
            trend = valor > prevValor ? 'up' : valor < prevValor ? 'down' : 'neutral';
        }
        return {
            // Clave única por punto: el XAxis usa `x`, no `fecha`.
            x: idx,
            fecha: r?.fecha,
            valor,
            label: etiquetaValorRM(r),
            trend,
        };
    });
}
