/**
 * niveles — el "nivel de atleta" que se puede mostrar HOY, y de dónde sale.
 *
 * ESTADO REAL DEL DATO (D3, 2026-10-28):
 *   · el backend persiste el nivel en `usuarios` (`nivel_fuerza`, `nivel_gimnastico`,
 *     `nivel_atleta`, `nivel_movs_fuerza`, `nivel_movs_gimnasia`, `nivel_confianza`,
 *     `nivel_calculado_en`, `nivel_version`) y lo recalcula al escribir un RM, al cambiar el
 *     perfil (peso/género) y en el job nocturno;
 *   · `GET /historial-rm/progreso-lote` devuelve esas columnas. Este módulo NORMALIZA lo que
 *     manda el backend (`"Sin datos"` -> null) y NO vuelve a derivar el nivel: la regla del
 *     badge (el menor de los ejes publicados) vive en `nivel_service.nivel_desde_mejores`.
 *
 * D1: un eje publica nivel solo con >=2 movimientos clasificables; con menos queda "Sin datos"
 * aunque haya una marca. Por eso `nivel` puede ser null aun con RMs cargados: el tooltip de la
 * tabla muestra los conteos (`movs_fuerza` / `movs_gimnasia`) para explicarlo.
 */

export const NIVELES_ATLETA = ['Principiante', 'Intermedio', 'Avanzado', 'Elite'];
export const SIN_DATOS_NIVEL = 'Sin datos';

/** Nivel de atleta que manda el backend (`nivel_atleta` persistido); null = "Sin datos". */
export const nivelDesdeBackend = (fila = {}) => {
    const nivel = fila?.nivel_atleta;
    return NIVELES_ATLETA.includes(nivel) ? nivel : null;
};

/** Etiqueta para la UI: el nivel o "Sin datos" (nunca `undefined`). */
export const etiquetaNivelAtleta = (nivel) => nivel || SIN_DATOS_NIVEL;

/** Chips del filtro: los cuatro niveles reales + el bucket de los que no tienen cálculo. */
export const OPCIONES_NIVEL = [
    { key: 'todos', label: 'Todos' },
    ...NIVELES_ATLETA.map((nivel) => ({ key: nivel, label: nivel })),
    { key: 'sin_datos', label: SIN_DATOS_NIVEL },
];

/** ¿El alumno pasa el filtro de nivel? ('todos' no filtra; 'sin_datos' = sin nivel calculado). */
export const pasaFiltroNivel = (nivel, filtro) => {
    if (!filtro || filtro === 'todos') return true;
    if (filtro === 'sin_datos') return !nivel;
    return nivel === filtro;
};

/** Clases del badge por nivel (el gris queda para los que no tienen cálculo). */
export const colorNivel = (nivel) => {
    if (nivel === 'Elite') return 'text-purple-700 bg-purple-50 border-purple-300';
    if (nivel === 'Avanzado') return 'text-green-700 bg-green-50 border-green-300';
    if (nivel === 'Intermedio') return 'text-sky-700 bg-sky-50 border-sky-300';
    if (nivel === 'Principiante') return 'text-orange-700 bg-orange-50 border-orange-300';
    return 'text-gray-500 bg-gray-50 border-gray-200';
};
