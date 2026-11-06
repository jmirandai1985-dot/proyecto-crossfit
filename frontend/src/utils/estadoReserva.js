// Etiquetas y estilos del estado VISIBLE de una reserva en "Mis Reservas".
//
// El estado NO se calcula acá: lo decide el backend en `GET /reservas` con el
// campo `estado_visible`, que reutiliza la MISMA función que el Historial del
// alumno (`historial_alumno_service.estado_asistencia`). Sus 5 valores son:
//   asistio | falto | cancelada | cancelada_tarde | reservada
// Este módulo sólo los traduce a texto y color para ESTA pantalla. Los rótulos
// de "Mis Reservas" ("No asistió"/"Confirmada") difieren a propósito de los del
// Historial ("Faltó"/"Reservada"), pero el CRITERIO es el mismo: un único origen.

export const TRADUCIR_ESTADO = {
    asistio: 'Asistió',
    falto: 'No asistió',
    cancelada: 'Cancelada',
    cancelada_tarde: 'Cancelada tarde',
    reservada: 'Confirmada',
};

export const COLORES_ESTADO = {
    asistio: 'bg-green-100 text-green-700 border-green-300',
    falto: 'bg-red-100 text-red-700 border-red-300',
    cancelada: 'bg-red-50 text-red-500 border-red-200',
    cancelada_tarde: 'bg-amber-100 text-amber-700 border-amber-300',
    reservada: 'bg-green-100 text-green-700 border-green-300',
};

const COLOR_DEFECTO = 'bg-gray-100 text-gray-600 border-gray-200';

// Una reserva "activa" es la que todavía va a ocurrir: el backend la marca
// `reservada`. Todo lo demás (asistió, faltó, cancelada) es historial.
export const ESTADO_ACTIVO = 'reservada';

// El estado VISIBLE de una reserva: SIEMPRE lo que devuelve el backend.
export const estadoVisible = (reserva) => reserva?.estado_visible || '';

export const esActiva = (reserva) => estadoVisible(reserva) === ESTADO_ACTIVO;

export const getEstadoDisplay = (estado) => {
    const key = (estado || '').toLowerCase();
    return TRADUCIR_ESTADO[key] || estado || 'Desconocido';
};

export const getEstadoColor = (estado) => {
    const key = (estado || '').toLowerCase();
    return COLORES_ESTADO[key] || COLOR_DEFECTO;
};

// ── Filtro por estado del HISTORIAL (sólo "Mis Reservas", no toca activas) ──
// Los chips son fijos (a diferencia del filtro de disciplina, que es dinámico).
// "Cancelada" agrupa a propósito `cancelada` + `cancelada_tarde`: para el alumno
// es el mismo desenlace ("la cancelaste"), así que se ven juntas en un solo chip.
export const ESTADOS_HISTORIAL = [
    { id: 'Todas', label: 'Todas' },
    { id: 'asistio', label: 'Asistió' },
    { id: 'falto', label: 'No asistió' },
    { id: 'cancelada', label: 'Cancelada' },
];

// ¿Una reserva de historial coincide con el chip elegido? (el chip "cancelada"
// agrupa los dos estados de cancelación).
export function coincideEstado(reserva, filtro) {
    if (!filtro || filtro === 'Todas') return true;
    const estado = estadoVisible(reserva);
    if (filtro === 'cancelada') return estado === 'cancelada' || estado === 'cancelada_tarde';
    return estado === filtro;
}

export function filtrarPorEstado(reservas, filtro) {
    return (reservas || []).filter((reserva) => coincideEstado(reserva, filtro));
}
