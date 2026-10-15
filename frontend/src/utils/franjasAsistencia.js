/**
 * franjasAsistencia — agrupación por franja del día para el panel admin móvil (<768px).
 *
 * POR QUÉ EXISTE: la tarjeta "Asistencia de hoy" del mockup muestra las clases del día
 * separadas en Mañana / Tarde / Noche, con la ocupación de cada franja y cuál está en
 * curso. Ese corte es un CÁLCULO (no depende del navegador ni de la red), así que vive
 * acá —puro y compartido— para poder probarlo aislado.
 *
 * Lo usan DOS pantallas que muestran lo mismo y no pueden contradecirse:
 *   · el Inicio móvil del admin (<768px), con la franja del reloj elegida por el admin;
 *   · la pestaña Asistencia (`AsistenciaClases franjas`) en <768px, que dibuja las franjas
 *     una debajo de la otra (mockup 6b). En ≥768px esa pestaña sigue con el acordeón por
 *     disciplina: el corte por franja es SOLO la vista de teléfono.
 *
 * Reglas:
 *   · Las horas son las del backend, que ya vienen en hora de CHILE (America/Santiago):
 *     acá NO se convierte nada, solo se lee la hora del string "HH:MM[:SS]".
 *   · Franjas del mockup: Mañana 05-11:59 · Tarde 12-17:59 · Noche 18-23:59.
 *   · Una hora sin dato (no debería pasar: `clases.hora_inicio` es NOT NULL en la BD)
 *     cae en la PRIMERA franja: preferimos mostrar la clase en el lugar aproximado antes
 *     que esconderla de la pantalla.
 */

export const FRANJAS = [
    { id: 'manana', label: 'Mañana', desde: 5, hasta: 12 },
    { id: 'tarde', label: 'Tarde', desde: 12, hasta: 18 },
    { id: 'noche', label: 'Noche', desde: 18, hasta: 24 },
];

export const IDS_FRANJAS = FRANJAS.map((f) => f.id);

/** Hora (0-23) de un valor de hora del backend ("HH:MM" o "HH:MM:SS"). */
export const horaDe = (valor) => {
    if (valor === null || valor === undefined || valor === '') return null;
    const h = parseInt(String(valor).split(':')[0], 10);
    return Number.isInteger(h) && h >= 0 && h <= 23 ? h : null;
};

/** "HH:MM" desde "HH:MM:SS" (lo que se pinta en la fila de la clase). */
export const horaCorta = (valor) => {
    if (!valor) return '';
    const partes = String(valor).split(':');
    return partes.length >= 2 ? `${partes[0]}:${partes[1]}` : String(valor);
};

/** Franja de una clase por su hora de inicio ('manana' | 'tarde' | 'noche'). */
export const franjaDe = (horaInicio) => {
    const h = horaDe(horaInicio);
    if (h === null) return 'manana';          // sin dato: no se pierde la clase
    if (h < 12) return 'manana';
    if (h < 18) return 'tarde';
    return 'noche';
};

/** { manana: [...], tarde: [...], noche: [...] } — listas NUEVAS, sin mutar la entrada. */
export const agruparPorFranja = (clases) => {
    const salida = { manana: [], tarde: [], noche: [] };
    (clases || []).forEach((c) => { salida[franjaDe(c?.hora_inicio)].push(c); });
    return salida;
};

/** Franja del reloj a esa hora ('HH:MM'): la que se abre por defecto y lleva el punto. */
export const franjaActual = (horaHHMM) => franjaDe(horaHHMM);

/**
 * Reservas de una clase, desde CUALQUIERA de las dos fuentes del panel:
 *   · `reservas_count` — lo que devuelve `GET /asistencia/clases-hoy` (la pantalla de hoy);
 *   · `asistentes_confirmados` — lo que devuelve `GET /clases` (la semana, ver A3).
 * El backend NO manda los dos campos a la vez: si vinieran, manda `reservas_count`
 * (incluso si es 0: un 0 real no debe caer al otro contador). Nunca devuelve NaN.
 */
export const reservasDe = (clase) => {
    const bruto = clase?.reservas_count ?? clase?.asistentes_confirmados;
    const n = Number(bruto);
    return Number.isFinite(n) && n > 0 ? n : 0;
};

/**
 * Los TRES números del mockup 6b por clase: los que reservaron, los que YA marcaron y los
 * que faltan. Fuente de cada uno:
 *   · conReserva — `reservas_count` del backend (reservas vigentes de la clase);
 *   · yaMarcaron — `marcados_count` del backend (`asistio = true`: el MISMO dato con el que
 *     la tarjeta ancha del Resumen del coach cuenta el "ya marcaron");
 *   · faltan      — la resta (nunca negativa): no viaja por la API para no tener dos cuentas.
 * Los dos conteos se acotan (nunca NaN, nunca "ya marcaron > con reserva") porque son de
 * requests distintos y una clase puede cambiar entre una y otra.
 */
export const contadoresDe = (conReserva, yaMarcaron) => {
    const reservas = Math.max(Number(conReserva) || 0, 0);
    const marcados = Math.min(Math.max(Number(yaMarcaron) || 0, 0), reservas);
    return { conReserva: reservas, yaMarcaron: marcados, faltan: reservas - marcados };
};

/** Los mismos 3 números, desde una fila de `GET /asistencia/clases-hoy`. */
export const contadoresClase = (clase) => contadoresDe(
    reservasDe(clase), clase?.marcados_count,
);

/** Resumen de una franja: cantidad de clases, rango horario y ocupación (0-100). */
export const resumenFranja = (clases) => {
    const lista = clases || [];
    const reservas = lista.reduce((a, c) => a + reservasDe(c), 0);
    const cupos = lista.reduce((a, c) => a + (Number(c?.cupo_maximo) || 0), 0);
    const horas = lista.map((c) => horaDe(c?.hora_inicio)).filter((h) => h !== null);
    return {
        clases: lista.length,
        reservas,
        cupos,
        desde: horas.length ? Math.min(...horas) : null,
        hasta: horas.length ? Math.max(...horas) : null,
        ocupacion: cupos > 0 ? Math.round(reservas / cupos * 100) : 0,
    };
};

/**
 * Índice de la clase "en curso" dentro de la franja (la última cuya hora ya pasó),
 * o -1 si todavía no empezó ninguna. Solo se usa en la franja ACTUAL del reloj.
 */
export const claseEnCurso = (clases, horaHHMM) => {
    if (!clases || !clases.length) return -1;
    const ahora = horaDe(horaHHMM);
    if (ahora === null) return -1;
    let indice = -1;
    clases.forEach((c, i) => {
        const h = horaDe(c?.hora_inicio);
        if (h !== null && h <= ahora) indice = i;
    });
    return indice;
};

/** { pct, nivel } para la barra de ocupación (nivel = '' | 'mid' | 'low' del mockup). */
export const ocupacion = (reservas, cupoMaximo) => {
    const cap = Number(cupoMaximo) || 0;
    if (cap <= 0) return { pct: 0, nivel: 'low' };
    const pct = Math.round((Number(reservas) || 0) / cap * 100);
    const nivel = pct >= 70 ? '' : pct >= 40 ? 'mid' : 'low';
    return { pct, nivel };
};

/** ¿La clase ya tiene la asistencia marcada? (badge "N ok" del botón Marcar). */
export const estaMarcada = (clase) => Boolean(clase?.marcada);

// ── La fila de la lista móvil por franja (mockup 6b) ─────────────────────────

/**
 * Estado de la fila, en el orden en que se decide:
 *   · 'hecha'     — la asistencia ya está marcada (lo dice el backend: `marcada`);
 *   · 'en-curso'  — el backend la marca `estado === 'en_curso'` (hora de CHILE, una sola
 *                   definición en `clases_service.estado_clase`): el front NO lee el reloj;
 *   · 'pendiente' — el resto (todavía no empieza, o ya terminó y quedó sin marcar).
 */
export const ESTADOS_FILA = {
    hecha: 'Hecha',
    'en-curso': 'En curso',
    pendiente: 'Pendiente',
};

export const estadoFila = (clase) => {
    if (estaMarcada(clase)) return 'hecha';
    if (clase?.estado === 'en_curso') return 'en-curso';
    return 'pendiente';
};

/** Etiqueta del estado (nunca `undefined`: un estado desconocido se lee "Pendiente"). */
export const etiquetaEstado = (estado) => ESTADOS_FILA[estado] || ESTADOS_FILA.pendiente;

/**
 * El progreso de la clase como lo escribe el mockup 6b:
 *   · marcada   -> "12/12 presentes"
 *   · pendiente -> "9/14 marcados"
 * Son los CONFIRMADOS sobre el CUPO de la clase (no las reservas: en esta fila importa
 * cuánta asistencia falta marcar). Sin cupo cargado cae a "N presentes/marcados": nunca
 * aparece un "/0" ni un NaN. `cupo` permite pasar el cupo ya ampliado en esta visita.
 */
export const textoProgreso = (clase, cupo) => {
    const confirmados = Number(clase?.asistentes_confirmados) || 0;
    const tope = Number(cupo ?? clase?.cupo_maximo) || 0;
    const palabra = estadoFila(clase) === 'hecha' ? 'presentes' : 'marcados';
    return tope > 0 ? `${confirmados}/${tope} ${palabra}` : `${confirmados} ${palabra}`;
};
