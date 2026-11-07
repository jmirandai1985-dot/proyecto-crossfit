/**
 * Progreso de la barra de NIVEL por movimiento (Performance Hub).
 *
 * POR QUÉ EXISTE: el acordeón de Performance Hub muestra, para Fuerza/Gimnástico,
 * una barra que va del umbral del nivel actual al umbral del siguiente (misma
 * regla que el panel expandido de Evolución). El cálculo es puro y vive acá para
 * poder testearlo aislado (sin navegador ni React).
 */

/**
 * % de progreso entre `umbral_actual` y `umbral_siguiente` de un detalle de nivel.
 *   - sin umbrales (o `nivelInfo` ausente) → 0;
 *   - si el umbral siguiente no supera al actual, sólo "Elite" se dibuja al 100%.
 * Devuelve siempre un número entre 0 y 100.
 */
export function pctProgresoNivel(valorActual, nivelInfo) {
    if (!nivelInfo || nivelInfo.umbral_actual == null || nivelInfo.umbral_siguiente == null) {
        return 0;
    }
    const a = Number(nivelInfo.umbral_actual);
    const b = Number(nivelInfo.umbral_siguiente);
    if (b > a) {
        return Math.min(100, Math.max(0, ((Number(valorActual) - a) / (b - a)) * 100));
    }
    return nivelInfo.nivel === 'Elite' ? 100 : 0;
}
