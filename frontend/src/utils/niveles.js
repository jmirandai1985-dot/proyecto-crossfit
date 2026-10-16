/**
 * niveles — el "nivel de atleta" que se puede mostrar HOY, y de dónde sale.
 *
 * ESTADO REAL DEL DATO (auditado antes de construir el filtro del coach):
 *   · el perfil del alumno NO tiene un campo de nivel: `usuarios` no tiene columna `nivel` ni
 *     nada equivalente, y el formulario del admin no lo edita;
 *   · la tabla `student_segments` (migración 021, BASICO/INTERMEDIO/AVANZADO + scores) existe
 *     pero está documentada como SIN CONSUMIDORES: nadie la escribe, nadie la lee y no hay
 *     endpoint que la exponga.
 *
 * Lo que SÍ existe y el coach puede leer es el cálculo EN VIVO del backend:
 * `GET /historial-rm/alumnos/{id}/nivel-general` devuelve `nivel_fuerza` y `nivel_gimnastico`
 * (escala de `nivel_service.NIVELES`), o "Sin datos" cuando falta peso corporal/género o no
 * hay marcas.
 *
 * Este módulo deriva UN nivel de atleta con el MISMO criterio que usa el servicio —"el nivel
 * más bajo" entre los movimientos de cada grupo—: el MENOR de los dos. Es una ESTIMACIÓN con
 * los RMs cargados, no un campo del perfil, y así se rotula en el panel.
 */

export const NIVELES_ATLETA = ['Principiante', 'Intermedio', 'Avanzado', 'Elite'];
export const SIN_DATOS_NIVEL = 'Sin datos';

/** Nivel estimado del alumno: el MENOR de fuerza/gimnasia (null si ninguno se pudo calcular). */
export const nivelDeAtleta = ({ nivel_fuerza, nivel_gimnastico } = {}) => {
    const presentes = [nivel_fuerza, nivel_gimnastico]
        .filter((n) => NIVELES_ATLETA.includes(n));
    if (presentes.length === 0) return null;
    return presentes.reduce((min, n) => (
        NIVELES_ATLETA.indexOf(n) < NIVELES_ATLETA.indexOf(min) ? n : min));
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
