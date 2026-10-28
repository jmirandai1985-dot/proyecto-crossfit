/**
 * notificacionesPanel — limpieza del panel de la campana (CampanaNotificaciones).
 *
 * POR QUÉ EXISTE: el panel listaba TODO lo que devolvía el endpoint, para siempre. En
 * un box con movimiento son cientos de filas: los avisos de hace tres meses siguen
 * ahí y las ya leídas tapan las nuevas. El backend sólo tiene GET /notificaciones,
 * PUT /{id}/leer y PUT /leer-todas (no hay DELETE), así que la limpieza es de VISTA:
 * no se borra ni se toca ningún dato.
 *
 * Dos reglas:
 *   1. "Ocultar leídas" (preferencia del usuario, guardada en localStorage): la lista
 *      muestra sólo lo pendiente. El badge ya contaba sólo las no leídas.
 *   2. Vigencia de 30 días: lo más viejo deja de mostrarse y deja de contar en el
 *      badge. Una notificación sin fecha válida se considera VIGENTE: si no se puede
 *      fechar, se muestra (mejor una fila de más que un aviso nuevo escondido).
 *
 * JS puro (sin React ni JSX) para poder testearlo con Node.
 */

/** Días que un aviso sigue apareciendo en la campana. */
export const DIAS_VIGENCIA_NOTIFICACION = 30;

// ── Severidad (orden de la lista) ────────────────────────────────────────────
// El backend ya devuelve lo más NUEVO primero, pero no todas las notificaciones pesan igual:
// un plan rechazado o una cobertura de emergencia exigen acción inmediata; un "pedido
// entregado" es informativo. La campana ordena por severidad y, dentro de cada nivel, por
// fecha (lo más nuevo arriba), así un aviso crítico viejo no queda tapado por diez
// informativos nuevos.
//
// 0 = crítica (hay que actuar), 1 = alta (importante, sin urgencia), 2 = informativa.
// Un tipo desconocido cae en 2: no se inventa urgencia.
export const SEVERIDAD_NOTIFICACION = {
    rechazado: 0,
    emergencia: 0,
    clase_liberada: 0,
    aprobado: 1,
    plan_solicitado: 1,
    pedido_nuevo: 1,
    config_bancaria: 1,
    clase_asignada: 1,
    clase_reasignada: 1,
    plan_activo: 2,
    alumno_nuevo: 2,
    pedido_validado: 2,
    pedido_entregado: 2,
};

/** Nivel de severidad de una notificación (2 por defecto: tipo desconocido = informativa). */
export const severidadDe = (notificacion) => (
    SEVERIDAD_NOTIFICACION[notificacion?.tipo] ?? 2
);

/** Clave de localStorage con la preferencia "ocultar leídas" ('1' / '0'). */
export const CLAVE_OCULTAR_LEIDAS = 'campana-ocultar-leidas';

const MS_POR_DIA = 24 * 60 * 60 * 1000;

/** Fecha (ms) de `created_at`; `null` si falta o no es una fecha válida. */
const fechaDe = (notificacion) => {
    const crudo = notificacion?.created_at;
    if (!crudo) return null;
    const ms = new Date(crudo).getTime();
    return Number.isNaN(ms) ? null : ms;
};

/**
 * ¿Sigue vigente? Sin fecha válida se responde `true` (ver el comentario de arriba).
 * Una fecha en el futuro también cuenta como vigente. Una entrada `null`/`undefined`
 * no es una notificación: `false`.
 */
export function esVigente(notificacion, { ahora = Date.now(), dias = DIAS_VIGENCIA_NOTIFICACION } = {}) {
    if (!notificacion) return false;
    const creada = fechaDe(notificacion);
    if (creada === null) return true;
    return ahora - creada <= dias * MS_POR_DIA;
}

/** Avisos sin leer y vigentes: es lo que muestra el badge de la campana. */
export function contarNoLeidas(notificaciones, { ahora = Date.now(), dias = DIAS_VIGENCIA_NOTIFICACION } = {}) {
    const lista = Array.isArray(notificaciones) ? notificaciones : [];
    return lista.filter(
        (n) => n && !n.leida && esVigente(n, { ahora, dias }),
    ).length;
}

/**
 * Filas que se pintan en el panel: fuera las vencidas y, si el usuario lo pidió,
 * también las leídas. No muta la lista y siempre devuelve un arreglo nuevo.
 */
export function filtrarVisibles(notificaciones, {
    ocultarLeidas = false,
    ahora = Date.now(),
    dias = DIAS_VIGENCIA_NOTIFICACION,
} = {}) {
    const lista = Array.isArray(notificaciones) ? notificaciones : [];
    return lista.filter((n) => {
        if (!n) return false;
        if (ocultarLeidas && n.leida) return false;
        return esVigente(n, { ahora, dias });
    });
}

/**
 * Orden de la lista: severidad (0 crítica primero) y, a igual severidad, lo más nuevo arriba.
 * No muta la entrada. Una notificación sin fecha válida queda al final de su grupo.
 */
export function ordenarPorSeveridad(notificaciones) {
    const lista = Array.isArray(notificaciones) ? [...notificaciones] : [];
    return lista.sort((a, b) => {
        const porSeveridad = severidadDe(a) - severidadDe(b);
        if (porSeveridad !== 0) return porSeveridad;
        const fa = fechaDe(a);
        const fb = fechaDe(b);
        return (fb ?? -Infinity) - (fa ?? -Infinity);
    });
}

/**
 * Preferencia guardada. `localStorage` puede no existir (SSR) o tirar (modo privado,
 * cuota llena): en ese caso se responde el valor por defecto `false`, nunca se rompe
 * el render de la campana.
 */
export function leerOcultarLeidas() {
    try {
        if (typeof window === 'undefined' || !window.localStorage) return false;
        return window.localStorage.getItem(CLAVE_OCULTAR_LEIDAS) === '1';
    } catch {
        return false;
    }
}

/** Guarda la preferencia. Igual que al leer, un fallo de `localStorage` no propaga. */
export function guardarOcultarLeidas(valor) {
    try {
        if (typeof window === 'undefined' || !window.localStorage) return;
        window.localStorage.setItem(CLAVE_OCULTAR_LEIDAS, valor ? '1' : '0');
    } catch {
        // Sin persistencia: la preferencia vive sólo en esta pestaña.
    }
}
