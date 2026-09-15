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
    // Altas y solicitudes -> pantalla de aprobación
    solicitud_registro: { path: '/admin/alumnos-pendientes', label: 'Pendientes' },
    solicitud_prueba_clase: { path: '/admin/alumnos-pendientes', label: 'Pendientes' },
    // Bazar
    confirmacion_pedido: { path: '/admin/bazar', label: 'Bazar' },
    stock_bajo: { path: '/admin/bazar', label: 'Bazar' },
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
    confirmacion_pedido: 'Confirmación de pedido (bazar)',
    stock_bajo: 'Alerta de stock bajo',
    confirmacion_renovacion: 'Confirmación de renovación',
    confirmacion_plan: 'Confirmación de plan',
    bienvenida: 'Bienvenida',
    activacion: 'Cuenta activada',
    bienvenida_activacion: 'Bienvenida y activación',
    cumplimiento: 'Hito de cumplimiento',
    acompanamiento: 'Acompañamiento',
    emergencia_cobertura: 'Cobertura de emergencia',
    reset_password: 'Restablecer contraseña',
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
