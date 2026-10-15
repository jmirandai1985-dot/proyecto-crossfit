// Navegación "volver atrás" de la flecha Volver (components/BotonVolver), que desde el
// Bloque 6 se ve en TODOS los anchos: el cálculo no depende del tamaño de la pantalla.
//
// POR QUÉ EXISTE: la flecha "Volver" (components/BotonVolver) tiene que decidir
// entre volver a la pantalla anterior (`history.back()`) o caer a un destino de
// respaldo. No se puede preguntar con `window.history.length`: cuenta la sesión
// ENTERA del navegador (otras webs incluidas), así que da "sí se puede volver"
// en una pestaña recién abierta con la URL pegada, y la flecha sacaría al
// usuario de la app. Lo que sí importa es si YA hubo navegación dentro de la
// app: React Router marca la PRIMERA ubicación de cada carga con
// `key === 'default'` y le pone una key propia a todas las siguientes.
//
// Util = cálculo (acá), componente = pintado (components/BotonVolver).

export const CLAVE_PRIMERA_UBICACION = 'default';

// `-1` es lo que entiende el router para "un paso atrás" (history.back()).
export const VOLVER_ATRAS = -1;

/** ¿Hay una pantalla de la app por detrás a la que volver? */
export const puedeVolverAtras = (key) => Boolean(key) && key !== CLAVE_PRIMERA_UBICACION;

/** Destino de la flecha "Volver": `-1` (atrás) o la ruta de respaldo. */
export const destinoVolver = (key, fallback) => (puedeVolverAtras(key) ? VOLVER_ATRAS : fallback);
