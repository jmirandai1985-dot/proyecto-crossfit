/**
 * bazarMovil — secciones del Bazar en el Dashboard admin móvil (<768px).
 *
 * POR QUÉ EXISTE: el acceso rápido "Bazar" empezó a llevar DIRECTO a "Pedidos listos
 * para entrega", y con eso se perdió el acceso a la pantalla real del Bazar (publicar y
 * editar productos). Ahora son DOS pestañas de la MISMA sección; este módulo es la única
 * definición de cuáles son, cuál arranca y qué pestaña abre cada punto de entrada, para
 * que la barra, el acceso rápido y los tests no repitan literales.
 */

/** Las pestañas: el orden del array ES el orden de la barra. */
export const TABS_BAZAR = [
    { id: 'catalogo', label: 'Catálogo' },
    { id: 'entrega', label: 'Entregar pedido' },
];

/** Pestaña que se muestra al abrir el Bazar. El catálogo es la pantalla de siempre. */
export const TAB_INICIAL = 'catalogo';

/** ¿Es un id de pestaña conocido? */
export const esTabValida = (id) => TABS_BAZAR.some((t) => t.id === id);

/** Pestaña normalizada: cualquier cosa rara cae en la inicial (nunca `undefined`). */
export const tabNormal = (id) => (esTabValida(id) ? id : TAB_INICIAL);

/**
 * Qué pestaña abre cada acceso rápido:
 *   - el ÍCONO principal -> "Catálogo" (restablece el inventario, que era lo que se había
 *     perdido);
 *   - el BADGE con la cantidad de pedidos -> "Entregar pedido" (lo que el pulso anuncia).
 */
export const tabDelAcceso = (acceso) => (acceso === 'badge' ? 'entrega' : TAB_INICIAL);

/**
 * Rótulo de la pestaña. "Entregar pedido" suma la cantidad que espera retiro cuando hay
 * (el mismo número del pulso del acceso rápido); sin pedidos no se escribe un "(0)".
 */
export const etiquetaTab = (id, pendientes = 0) => {
    const tab = TABS_BAZAR.find((t) => t.id === tabNormal(id)) || TABS_BAZAR[0];
    const n = Number(pendientes);
    const muestra = tab.id === 'entrega' && Number.isFinite(n) && n > 0;
    return muestra ? `${tab.label} (${n})` : tab.label;
};
