/**
 * Destino de navegación por tipo de notificación.
 *
 * Fuente única: la usan la tabla de Notificaciones Enviadas (fila clickeable), el
 * tooltip del destino y los click-tests. `path: null` = la fila NO navega (se
 * deja sin link a propósito, no se fuerza un destino).
 *
 * `conAlumno: true` = el destino soporta `?alumno_id=<id>` y abre la ficha del
 * alumno (Fidelización y Alumnos lo implementan).
 */
export const DESTINOS = {
    // Alertas de retención -> Fidelización con la ficha del alumno abierta
    inactividad: { path: '/admin/fidelizacion', conAlumno: true, label: 'Fidelización' },
    reactivacion: { path: '/admin/fidelizacion', conAlumno: true, label: 'Fidelización' },
    renovacion_plan: { path: '/admin/fidelizacion', conAlumno: true, label: 'Fidelización' },
    vencimiento: { path: '/admin/fidelizacion', conAlumno: true, label: 'Fidelización' },
    vencimiento_inminente: { path: '/admin/fidelizacion', conAlumno: true, label: 'Fidelización' },
    ultimo_credito: { path: '/admin/fidelizacion', conAlumno: true, label: 'Fidelización' },
    sin_creditos: { path: '/admin/fidelizacion', conAlumno: true, label: 'Fidelización' },
    // Altas y solicitudes -> pantalla unificada de aprobación (Tanda 4). El enlace
    // viejo (`/admin/alumnos-pendientes`) hoy es un redirect, pero acá vamos directo
    // a la pestaña que corresponde: los registros de alumno nuevo viven en `registros`.
    solicitud_registro: { path: '/admin/pendientes?tab=registros', label: 'Pendientes · Registros' },
    solicitud_prueba_clase: { path: '/admin/pendientes?tab=registros', label: 'Pendientes · Registros' },
    // Premio de referidos (umbral alcanzado): la notificación `promo_referido` de
    // `promociones_referidos_service` no tenía destino y la fila quedaba muerta.
    promo_referido: { path: '/admin/pendientes?tab=premios', label: 'Pendientes · Premios' },
    // Bazar
    confirmacion_pedido: { path: '/admin/bazar', label: 'Bazar' },
    // Pedido nuevo: es el aviso de CAMPANA del admin (pedidos.py). Va a la pestaña
    // "Pedidos" de Pendientes, que es donde se valida o rechaza el comprobante.
    pedido_nuevo: { path: '/admin/pendientes?tab=pedidos', label: 'Pendientes · Pedidos' },
    // El slug REAL que emite email_service es `alerta_stock_bajo` (antes acá decía
    // `stock_bajo`, que no existe => opción muerta en el filtro de tipo).
    alerta_stock_bajo: { path: '/admin/bazar', label: 'Bazar' },
    // Alumnos (ficha del alumno)
    confirmacion_renovacion: { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' },
    bienvenida: { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' },
    activacion: { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' },
    bienvenida_activacion: { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' },
    confirmacion_plan: { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' },
    cumplimiento: { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' },
    acompanamiento: { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' },
    // Supervisión
    emergencia_cobertura: { path: '/admin/supervision-clases', label: 'Supervisión' },
    // Sin destino propio (no se fuerza ninguno)
    reset_password: { path: null, label: null },
};

/** Etiquetas legibles del `tipo` (el slug crudo no se muestra al admin). */
export const ETIQUETAS = {
    inactividad: 'Alerta de inactividad',
    reactivacion: 'Reactivación',
    renovacion_plan: 'Plan por vencer (3 días)',
    vencimiento: 'Aviso de vencimiento de plan',
    vencimiento_inminente: 'Plan vencido / urgente',
    ultimo_credito: 'Último crédito del mes',
    sin_creditos: 'Sin créditos',
    solicitud_registro: 'Solicitud de registro',
    solicitud_prueba_clase: 'Solicitud de clase de prueba',
    // Premio de referidos (umbral alcanzado). Se listaba en la tabla con el slug crudo
    // porque faltaba acá y en DESTINOS.
    promo_referido: 'Premio de referidos',
    confirmacion_pedido: 'Confirmación de pedido (bazar)',
    pedido_nuevo: 'Pedido nuevo (bazar)',
    alerta_stock_bajo: 'Alerta de stock bajo (admin)',
    confirmacion_renovacion: 'Confirmación de renovación',
    confirmacion_plan: 'Confirmación de plan',
    bienvenida: 'Bienvenida',
    activacion: 'Cuenta activada',
    bienvenida_activacion: 'Bienvenida y activación',
    cumplimiento: 'Hito de cumplimiento',
    acompanamiento: 'Acompañamiento',
    emergencia_cobertura: 'Cobertura de emergencia (admin)',
    reset_password: 'Restablecer contraseña',
    // Hitos de racha: el tipo real que registra el cierre mensual es hito_racha_1/3/6/12.
    // Se listan para que se puedan filtrar desde la pantalla (antes sólo se veían en la
    // tabla, sin opción en el filtro).
    hito_racha_1: 'Hito de racha (1 mes)',
    hito_racha_3: 'Hito de racha (3 meses)',
    hito_racha_6: 'Hito de racha (6 meses)',
    hito_racha_12: 'Hito de racha (12 meses)',
};

/** "hito_racha_N" -> "Hito de racha (N)"; el resto, fallback al slug. */
export const etiquetaDe = (tipo) => {
    const t = String(tipo || '');
    if (ETIQUETAS[t]) return ETIQUETAS[t];
    if (t.startsWith('hito_racha')) {
        const n = t.replace('hito_racha_', '');
        return Number.isFinite(Number(n)) ? `Hito de racha (${n})` : 'Hito de racha';
    }
    return t || '—';
};

/** Destino de un tipo (acepta el prefijo hito_racha_*). null si no navega. */
export const destinoDe = (tipo) => {
    const t = String(tipo || '');
    if (DESTINOS[t]) return DESTINOS[t];
    if (t.startsWith('hito_racha')) {
        return { path: '/admin/alumnos', conAlumno: true, label: 'Alumnos' };
    }
    return null;
};

/** URL final del destino (agrega ?alumno_id= cuando corresponde). */
export const urlDestino = (tipo, alumnoId) => {
    const d = destinoDe(tipo);
    if (!d || !d.path) return null;
    return d.conAlumno && alumnoId ? `${d.path}?alumno_id=${alumnoId}` : d.path;
};
