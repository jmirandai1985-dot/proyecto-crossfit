// ─── Pantalla unificada "Pendientes" del admin (Tanda 4) ──────────────────────
// JS PURO (sin JSX ni React) a propósito: `scripts/test-pendientes.mjs` lo importa
// con Node, igual que `config/menu.js`. Acá vive TODO lo que decide la pantalla:
// qué pestañas hay, cuál se abre por defecto según los contadores, cómo se lee el
// `?tab=` de la URL y cómo se traduce el enlace viejo (`?cola=`) al nuevo.
//
// POR QUÉ EXISTE: los pendientes del box estaban repartidos en TRES pantallas
// (registros + solicitudes en `/admin/alumnos-pendientes`, pedidos en
// `/admin/pedidos`, premios en Configuración → Referidos). El admin tenía que
// acordarse de cuál mirar y los badges no coincidían entre sí. Ahora hay UNA
// pantalla con cuatro pestañas y UN endpoint de contadores
// (`GET /admin/pendientes/resumen`), que son las MISMAS tablas que alimentan las
// listas: si el badge dijera 3 y la lista mostrara 2, nadie confiaría en el badge.

// Orden de las pestañas = orden en que el admin las trabaja: primero lo que el
// alumno está esperando para ENTRAR (su comprobante de plan), después lo que
// espera para llevarse algo (Bazar), después el alta de alumnos y al final el
// premio de referidos (que no bloquea a nadie). `cola` es el nombre del contador
// en el resumen; `key` es el valor de `?tab=`.
export const TABS_PENDIENTES = [
    {
        key: 'solicitudes', cola: 'solicitudes', icono: '🧾', label: 'Solicitudes',
        descripcion: 'Solicitudes de plan con comprobante esperando aprobación',
    },
    {
        key: 'pedidos', cola: 'pedidos', icono: '📦', label: 'Pedidos',
        descripcion: 'Pedidos del Bazar con comprobante sin validar',
    },
    {
        key: 'registros', cola: 'registros', icono: '📝', label: 'Registros',
        descripcion: 'Alumnos nuevos que se registraron solos y esperan activación',
    },
    {
        key: 'premios', cola: 'premios', icono: '🎁', label: 'Premios',
        descripcion: 'Alumnos que alcanzaron el umbral de una promoción de referidos',
    },
];

// Los cuatro contadores + `total`. En cero, SIN red: es el valor mientras carga
// la primera respuesta (un badge vacío es mejor que un badge con "...").
export const CONTADORES_VACIOS = {
    solicitudes: 0, pedidos: 0, registros: 0, premios: 0, total: 0,
};

// ── Lectura defensiva del resumen ────────────────────────────────────────────
// El backend ya manda enteros, pero la campana y el menú lateral consumen esto
// con la respuesta en caché: un `undefined` o un `null` NO puede convertirse en
// `NaN` en pantalla (`NaN` en un badge se ve como un error del panel).
export function normalizarResumen(resumen) {
    const fuente = resumen && typeof resumen === 'object' ? resumen : {};
    const limpio = {};
    let suma = 0;
    for (const tab of TABS_PENDIENTES) {
        const valor = Number(fuente[tab.cola]);
        const n = Number.isFinite(valor) && valor > 0 ? Math.floor(valor) : 0;
        limpio[tab.cola] = n;
        suma += n;
    }
    // `total` se recalcula acá en vez de confiar en el del backend: si algún día
    // una pestaña suma un contador nuevo, el badge del menú lo incluye solo.
    limpio.total = suma;
    return limpio;
}

export function totalPendientes(resumen) {
    return normalizarResumen(resumen).total;
}

// Cuántos pendientes tiene una pestaña concreta (0 si la clave no existe).
export function pendientesDe(tab, resumen) {
    return normalizarResumen(resumen)[tab] || 0;
}

// ── Pestaña por defecto ──────────────────────────────────────────────────────
// La PRIMERA con pendientes (en el orden de trabajo). Si no hay ninguno, la
// primera: la pantalla igual se abre en "Solicitudes" con su estado vacío.
export function tabPorDefecto(resumen) {
    const contadores = normalizarResumen(resumen);
    const conPendientes = TABS_PENDIENTES.find((tab) => contadores[tab.cola] > 0);
    return (conPendientes || TABS_PENDIENTES[0]).key;
}

export function esTabValida(valor) {
    return TABS_PENDIENTES.some((tab) => tab.key === valor);
}

// `?tab=` de la URL → pestaña realmente mostrada. Un valor viejo o inventado
// (`?tab=foo`) NO deja la pantalla en blanco: cae en la pestaña por defecto.
export function resolverTab(valor, resumen) {
    return esTabValida(valor) ? valor : tabPorDefecto(resumen);
}

// Enlace interno a una pestaña (lo usan el menú, la campana, el Dashboard y las
// tarjetas del Inicio móvil para que TODOS apunten a lo mismo).
export function rutaPendientes(tab) {
    return `/admin/pendientes?tab=${esTabValida(tab) ? tab : TABS_PENDIENTES[0].key}`;
}

// ── Compatibilidad con el enlace viejo ───────────────────────────────────────
// `/admin/alumnos-pendientes?cola=solicitudes` era el deep-link de la campana y
// del Dashboard, y quedó guardado en teléfonos y correos. La pantalla vieja ahora
// es un redirect: esta función decide a qué pestaña equivale cada `cola`.
// `cola` sólo distinguía registros de solicitudes (las otras dos pestañas son
// nuevas), así que cualquier otro valor cae en 'solicitudes', que era el default.
const COLA_A_TAB = {
    solicitudes: 'solicitudes',
    registros: 'registros',
    pedidos: 'pedidos',
    premios: 'premios',
};

export function mapearColaLegacy(cola) {
    return COLA_A_TAB[cola] || 'solicitudes';
}

// Texto del badge: 100+ pendientes no caben en un círculo de 18px. Es sólo
// presentación, el número real va en el `title`/`aria-label`.
export function textoBadge(cantidad) {
    const n = Number(cantidad);
    if (!Number.isFinite(n) || n <= 0) return '';
    return n > 99 ? '99+' : String(Math.floor(n));
}

// ── Publicación de una promoción de referidos ────────────────────────────────
// La tarjeta del carrusel es un `avisos_marketing` VINCULADO a la promoción
// (migración 056). Al publicar hay que elegir una ventana; estos dos helpers
// evitan que el modal invente fechas por su cuenta (y que el test las repita).

// Fecha `YYYY-MM-DD` en hora LOCAL. No se usa `toISOString()` porque convierte a
// UTC: en Chile (UTC-3/-4) publicar a las 21:00 dejaría la ventana empezando
// "mañana". El backend guarda `date`, no un instante.
export function fechaISO(fecha = new Date()) {
    const anio = fecha.getFullYear();
    const mes = String(fecha.getMonth() + 1).padStart(2, '0');
    const dia = String(fecha.getDate()).padStart(2, '0');
    return `${anio}-${mes}-${dia}`;
}

// Ventana sugerida al abrir el modal: desde hoy y durante `dias` días. Es sólo
// el valor inicial — el admin puede cambiarlo y el backend valida el orden.
export function ventanaPublicacionSugerida(desde = new Date(), dias = 30) {
    const inicio = new Date(desde.getFullYear(), desde.getMonth(), desde.getDate());
    const fin = new Date(inicio.getFullYear(), inicio.getMonth(), inicio.getDate() + dias);
    return { vigente_desde: fechaISO(inicio), vigente_hasta: fechaISO(fin) };
}

// Mismas reglas que `PublicarPromocionRequest` (schemas/referidos.py): el
// formulario las repite para dar feedback inmediato, pero quien manda es el
// backend. Devuelve la lista de errores; `[]` = se puede enviar.
export function validarPublicacion({ titulo, texto, vigente_desde, vigente_hasta } = {}) {
    const errores = [];
    const tituloLimpio = String(titulo ?? '').trim();
    const textoLimpio = String(texto ?? '').trim();
    if (!tituloLimpio) {
        errores.push('El título de la tarjeta es obligatorio.');
    } else if (tituloLimpio.length > 150) {
        errores.push('El título no puede pasar de 150 caracteres.');
    }
    if (!textoLimpio) {
        errores.push('El texto de la tarjeta es obligatorio.');
    } else if (textoLimpio.length > 1000) {
        errores.push('El texto no puede pasar de 1000 caracteres.');
    }
    if (!vigente_desde || !vigente_hasta) {
        errores.push('Indica desde y hasta cuándo se muestra la tarjeta.');
    } else if (String(vigente_hasta) < String(vigente_desde)) {
        // `YYYY-MM-DD` compara bien como texto; no hace falta convertir a Date
        // (y así no hay sorpresas de zona horaria).
        errores.push('La vigencia no puede terminar antes de empezar.');
    }
    return errores;
}

// Texto SUGERIDO de la tarjeta a partir de la promoción. El admin lo puede editar
// entero: es sólo el punto de partida, para no escribir el premio a mano (y para
// que el título y el texto no digan cosas distintas del umbral configurado).
export function tarjetaSugerida(promocion = {}) {
    const nombre = String(promocion.nombre ?? '').trim();
    const premio = String(promocion.premio_texto ?? '').trim();
    const umbral = Math.max(1, Math.floor(Number(promocion.umbral_referidos_convertidos) || 1));
    const referidos = umbral === 1 ? '1 referido convertido' : `${umbral} referidos convertidos`;
    return {
        titulo: nombre || 'Invita y gana',
        texto: premio
            ? `Invita a tus amigos al box: con ${referidos} en el mes ganas ${premio}.`
            : `Invita a tus amigos al box y gana premios al llegar a ${referidos} en el mes.`,
    };
}

// Estado de la TARJETA publicada, para el chip de la lista de promociones.
// `publicada` dice si existe el aviso vinculado; `publicada_hasta` si sigue
// vigente. Mismo criterio que el chip "Vigente/Vencido" de Marketing: se compara
// sólo la fecha (el backend guarda `date`, no un instante).
export function estadoPublicacion(promocion = {}, hoy = new Date()) {
    if (!promocion.publicada) {
        return { clave: 'sin_publicar', texto: 'Sin publicar', vencida: false };
    }
    const hasta = String(promocion.publicada_hasta ?? '').slice(0, 10);
    const vencida = Boolean(hasta) && hasta < fechaISO(hoy);
    return vencida
        ? { clave: 'vencida', texto: 'Publicación vencida', vencida: true }
        : { clave: 'vigente', texto: 'Publicada', vencida: false };
}
