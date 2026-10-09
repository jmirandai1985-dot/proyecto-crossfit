/**
 * fidelizacionMovil — tarjetas COMPACTAS con acordeón de la pantalla Fidelización en
 * móvil (<768px).
 *
 * POR QUÉ EXISTE: en el teléfono la tabla de 7 columnas obliga a scroll horizontal y cada
 * alumno ocupa media pantalla; con 300+ alumnos en riesgo, ver "a quién le toca" es
 * imposible. Acá viven las dos reglas de esa vista para que el JSX y los tests no repitan
 * literales:
 *
 *  1. UNA sola tarjeta abierta a la vez (`alternarTarjeta`): abrir otra cierra la
 *     anterior y volver a tocar la abierta la cierra. Con cientos de alumnos, dos paneles
 *     abiertos a la vez hacen perder el hilo de a quién se le está mandando el correo.
 *  2. La fila CERRADA no muestra todo (nombre, riesgo y UNA línea del motivo). El resto
 *     —arquetipo, motivo completo, recomendación y los dos botones— NO se pierde: se
 *     renderiza de los MISMOS datos del alumno cuando la tarjeta se abre
 *     (`detalleAbierto`), sin estado propio que pueda quedar viejo ni copia mutada.
 *
 * La pantalla de escritorio (>=768px) no usa nada de esto: sigue con la tabla de siempre
 * (regla de oro del rediseño móvil).
 */

/** Caracteres del motivo que entran en la fila cerrada (una línea a 360px). */
export const MAX_MOTIVO_CERRADO = 68;

/** Qué se muestra cuando el alumno no tiene motivo registrado (igual que la tabla: '—'). */
export const SIN_MOTIVO = '—';

/**
 * La regla del acordeón. Devuelve el id que debe quedar abierto:
 *  · el id tocado si estaba cerrada o si la abierta era OTRA (cierra la anterior),
 *  · `null` si se tocó la que ya estaba abierta (toggle).
 * Compara como texto para no depender de si el id llega como número o string.
 */
export const alternarTarjeta = (abierta, id) => (
    abierta != null && String(abierta) === String(id) ? null : id
);

/** ¿Esta tarjeta es la (única) abierta? */
export const estaAbierta = (abierta, id) => (
    abierta != null && String(abierta) === String(id)
);

/**
 * El motivo en UNA línea: espacios colapsados y corte en la última palabra completa,
 * con "…" (no corta una palabra al medio ni miente con un texto que no cabe).
 */
export const motivoCorto = (motivo, max = MAX_MOTIVO_CERRADO) => {
    const texto = String(motivo ?? '').replace(/\s+/g, ' ').trim();
    if (!texto) return SIN_MOTIVO;
    if (texto.length <= max) return texto;
    let corte = texto.slice(0, max);
    // Sólo se retrocede si justo después del corte sigue una palabra EMPEZADA: si el
    // corte ya cayó en un espacio, las palabras de `corte` están completas.
    if (texto[max] !== ' ') {
        const ultimoEspacio = corte.lastIndexOf(' ');
        if (ultimoEspacio > 0) corte = corte.slice(0, ultimoEspacio);
    }
    return `${corte.trimEnd()}…`;
};

/** "50.3%" — el mismo formato que la columna Riesgo de la tabla de escritorio. */
export const probabilidadTexto = (valor) => `${Number(valor || 0).toFixed(1)}%`;

/** Lo que muestra la fila CERRADA (nombre, riesgo y 1 línea de motivo). */
export const resumenCerrado = (alumno, max = MAX_MOTIVO_CERRADO) => ({
    nombre: alumno?.alumno_nombre || `Alumno #${alumno?.usuario_id ?? ''}`,
    riesgo_nivel: alumno?.riesgo_nivel || null,
    probabilidad: probabilidadTexto(alumno?.probabilidad_churn),
    motivoCorto: motivoCorto(alumno?.motivo, max),
});

/**
 * Header + línea de la recomendación, con la MISMA regla que la columna de escritorio
 * (`plantilla ? label : motivo`): el panel y la tabla no pueden decir cosas distintas.
 */
export const textoRecomendacion = (sugerencia) => {
    const plantilla = sugerencia?.plantilla || null;
    return {
        plantilla,
        encabezado: plantilla || 'Sin correo que mandar',
        principal: plantilla
            ? (sugerencia?.label || sugerencia?.motivo || '')
            : (sugerencia?.motivo || SIN_MOTIVO),
        // El motivo del correo sólo se agrega cuando YA se mostró la etiqueta: si no,
        // sería la misma frase dos veces.
        motivo: plantilla ? (sugerencia?.motivo || '') : '',
    };
};

/**
 * Todo lo que aparece al ABRIR la tarjeta, derivado del alumno (y de su sugerencia): es
 * la misma información de la fila de escritorio, así que colapsar no la pierde — se
 * vuelve a calcular del mismo dato en cada render.
 */
export const detalleAbierto = (alumno, sugerencia) => ({
    arquetipo: alumno?.arquetipo ?? null,
    motivo: String(alumno?.motivo ?? '').replace(/\s+/g, ' ').trim() || SIN_MOTIVO,
    gestion: alumno?.estado_gestion || 'PENDIENTE',
    recomendacion: textoRecomendacion(sugerencia),
});
