/**
 * capas — z-index de los overlays, en UN solo lugar.
 *
 * POR QUÉ EXISTE (stacking móvil de Avisos/Notificaciones): en el teléfono la campana es un
 * panel `fixed` y los avisos del carrusel abren modales `fixed inset-0`. Los dos usaban `z-50`:
 * cuál quedaba arriba dependía del ORDEN en el DOM, y la campana vive en el header (que es
 * `relative z-30` en Layout), así que un modal abierto desde el carrusel podía quedar debajo
 * del panel de notificaciones. Con la capa explícita el modal SIEMPRE pinta arriba.
 *
 * Son clases LITERALES (no `z-[${n}]`) porque Tailwind necesita ver el string en el código
 * para generar la utilidad. `scripts/test-avisos-capas.mjs` verifica que el orden se respete.
 */
export const CLASES_CAPA = {
    // Panel de la campana (header). Debe quedar por encima del contenido y del backdrop.
    notificaciones: 'z-50',
    // Modales de aviso (Marketing/Bazar y aviso rápido del coach): por encima de la campana.
    modalAviso: 'z-[60]',
};

/** Orden numérico de las capas (para tests y documentación). */
export const ORDEN_CAPAS = {
    notificaciones: 50,
    modalAviso: 60,
};
