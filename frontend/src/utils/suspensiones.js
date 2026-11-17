// Reglas puras del modal "+ Nueva suspensión" (pages/admin/Suspensiones.jsx).
//
// POR QUÉ EXISTEN: el panel `SuspensionSaludPanel` es COMPARTIDO con la ficha del
// alumno y no se modifica, así que no avisa "creé la suspensión". El modal padre se
// entera mirando la mutación en la caché de React Query (`useMutationState`) y
// compara los ids de las suspensiones creadas ANTES de elegir al alumno con los de
// ahora: si aparece uno nuevo, la creación salió bien y corresponde cerrar el modal y
// refrescar el listado. Ese "¿apareció una nueva?" vive acá para poder probarlo sin
// navegador (`scripts/test-suspensiones-nueva.mjs`).

/** Ids numéricos de las suspensiones creadas (descarta null/undefined/basura). */
export const idsSuspensionesCreadas = (ids) => (Array.isArray(ids) ? ids : [])
    // `Number(null)` es 0: sin este filtro, un hueco se colaría como id 0.
    .filter((id) => id !== null && id !== undefined && id !== '')
    .map((id) => Number(id))
    .filter((id) => Number.isFinite(id));

/**
 * ¿Hay alguna suspensión que NO estaba en la foto anterior?
 *
 * `previas` es el Set que el modal guardó al abrir el paso 2 (puede llegar como
 * array o Set); `actuales` es lo que devuelve `useMutationState` en este render.
 * Los ids que se repiten no cuentan: reabrir el modal para el mismo alumno NO debe
 * cerrarse solo por una suspensión creada en una visita anterior.
 */
export const haySuspensionNueva = (previas, actuales) => {
    const vistas = previas instanceof Set
        ? previas
        : new Set(idsSuspensionesCreadas(previas));
    return idsSuspensionesCreadas(actuales).some((id) => !vistas.has(id));
};
