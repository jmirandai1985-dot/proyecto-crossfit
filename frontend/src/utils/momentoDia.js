// ─── El "momento del día" de la tarjeta "Tu clase de hoy" ───────────────────
//
// La tarjeta naranja del Inicio del alumno decía SIEMPRE lo mismo ("Al llegar,
// escanea el QR…"), a las 7 de la mañana y a las 10 de la noche. El saludo y el
// consejo ahora siguen el momento del día.
//
// La hora se lee en America/Santiago, NO en la del teléfono: el alumno puede
// estar de viaje o con el reloj mal y la clase sigue siendo la del box (mismo
// criterio que `utils/fecha.js` y el backend).
//
// JS PURO (sin JSX): `scripts/test-momento-dia.mjs` lo importa con Node.

export const MOMENTOS = Object.freeze({
    MANANA: 'manana',
    TARDE: 'tarde',
    NOCHE: 'noche',
});

// Franjas: 05:00–11:59 mañana · 12:00–19:59 tarde · 20:00–04:59 noche. Los
// bordes son en punto: a las 12:00 ya es "Buenas tardes" y a las 20:00, "Buenas
// noches".
const HORA_MANANA = 5;
const HORA_TARDE = 12;
const HORA_NOCHE = 20;

// Hora (0–23) del día CHILENO de un instante.
function horaChile(fecha) {
    // `hourCycle: 'h23'` evita el "24" que devuelven algunos navegadores a
    // medianoche con `hour12: false` (24 no entra en ninguna franja).
    const partes = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'America/Santiago',
        hour: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(fecha);
    const hora = partes.find((parte) => parte.type === 'hour');
    return Number(hora?.value ?? 0);
}

// `'manana' | 'tarde' | 'noche'` para ese instante (default: ahora).
// Una fecha inválida cae en "mañana": nunca un texto vacío en la tarjeta.
export function momentoDelDia(ahora = new Date()) {
    const fecha = ahora instanceof Date ? ahora : new Date(ahora);
    if (Number.isNaN(fecha.getTime())) return MOMENTOS.MANANA;
    const hora = horaChile(fecha);
    if (hora >= HORA_MANANA && hora < HORA_TARDE) return MOMENTOS.MANANA;
    if (hora >= HORA_TARDE && hora < HORA_NOCHE) return MOMENTOS.TARDE;
    return MOMENTOS.NOCHE;
}

const SALUDOS = {
    [MOMENTOS.MANANA]: 'Buenos días',
    [MOMENTOS.TARDE]: 'Buenas tardes',
    [MOMENTOS.NOCHE]: 'Buenas noches',
};

export function saludoDelMomento(momento) {
    return SALUDOS[momento] || SALUDOS[MOMENTOS.MANANA];
}

// El texto del recuadro de la tarjeta, por ESTADO de la reserva (los mismos de
// `utils/estadoReserva.js`) y por momento del día. Sólo "reservada" y "sin
// clase" cambian con la hora: la asistencia, el no-show y la cancelación son
// hechos, no dependen de cuándo se mire la pantalla.
const COPY = {
    reservada: {
        [MOMENTOS.MANANA]: 'Llega 10 minutos antes: el QR de la entrada te espera',
        [MOMENTOS.TARDE]: 'Al llegar, escanea el QR de la entrada con la cámara de tu celular',
        [MOMENTOS.NOCHE]: 'Al llegar, escanea el QR de la entrada y marca tu asistencia',
    },
    sin_clase: {
        [MOMENTOS.MANANA]: 'Aún no tienes clase hoy: reserva en “Clases disponibles”',
        [MOMENTOS.TARDE]: 'No tienes clase esta tarde: mira “Clases disponibles”',
        [MOMENTOS.NOCHE]: 'Sin clase hoy: revisa “Clases disponibles” para mañana',
    },
};

const COPY_FIJO = {
    asistio: 'Asistencia marcada',
    falto: 'No registramos tu asistencia en esta clase',
    cancelada: 'Esta clase fue cancelada',
    cancelada_tarde: 'Esta clase fue cancelada',
};

// `estado` = null/undefined cuando el alumno no tiene clase hoy.
export function copyClaseHoy(estado, momento) {
    const clave = estado || 'sin_clase';
    if (COPY_FIJO[clave]) return COPY_FIJO[clave];
    const franja = SALUDOS[momento] ? momento : MOMENTOS.MANANA;
    return (COPY[clave] || COPY.sin_clase)[franja];
}
