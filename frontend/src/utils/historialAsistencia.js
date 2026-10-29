/**
 * historialAsistencia — las CUENTAS del "Historial de Asistencia" (coach + admin).
 *
 * POR QUÉ EXISTE: la pantalla pide UN mes al backend (`GET /asistencia/historial?anio&mes`) y
 * con esa lista dibuja tres cosas: el anillo de cada día de la semana, la grilla del calendario
 * y el detalle por bloque horario de un día. Los porcentajes NO viajan por la API (el backend
 * manda hechos: cupos, reservas y quién vino), así que la aritmética vive acá —pura y
 * compartida— para poder probarla sin navegador y para que las tres vistas no puedan contar
 * distinto lo mismo.
 *
 * Reglas (fijadas en `scripts/test-historial-asistencia.mjs`):
 *   · "presente" = `marcados_count` del backend (`reservas.asistio = true`), el MISMO dato con
 *     el que el Resumen del coach cuenta el "ya marcaron"; si el backend no manda el contador
 *     (backend viejo), se cuenta con la lista de `alumnos`. Nunca NaN.
 *   · "no show" (ausente) = reservas VIGENTES menos presentes: el que reservó y no llegó. Una
 *     cancelación no es un ausente (el backend ya no la manda).
 *   · porcentaje = presentes ÷ CUPOS de las clases, redondeado. Con cupo 0 (dato viejo) el
 *     porcentaje es 0, no una división por cero.
 *   · ANILLOS y TOTALES: se calculan con `clasesOcurridas` (fecha <= hoy). Una clase futura
 *     todavía no tiene asistencia que medir y no debe inflar el denominador. El calendario y
 *     el detalle diario sí muestran el mes completo.
 *   · las fechas son las del backend en hora de Chile ('YYYY-MM-DD'): acá NO se convierte nada
 *     (sólo se leen los componentes del string, igual que `franjasAsistencia` con las horas).
 *   · la semana empieza el LUNES (misma regla que la grilla del coach y `utils/fecha.semanaEnCurso`).
 */

export const MESES = [
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
];

// LUNES primero: es la regla del mockup y la del resto del panel.
export const DIAS_SEMANA = [
    { clave: 'lun', label: 'Lun', largo: 'Lunes' },
    { clave: 'mar', label: 'Mar', largo: 'Martes' },
    { clave: 'mie', label: 'Mié', largo: 'Miércoles' },
    { clave: 'jue', label: 'Jue', largo: 'Jueves' },
    { clave: 'vie', label: 'Vie', largo: 'Viernes' },
    { clave: 'sab', label: 'Sáb', largo: 'Sábado' },
    { clave: 'dom', label: 'Dom', largo: 'Domingo' },
];

/** "Octubre" desde 10 ('' si el mes no existe). */
export const nombreMes = (mes) => MESES[Number(mes) - 1] || '';

/**
 * Los años del selector: el año actual y los `cuantos - 1` anteriores (el box no tiene datos
 * de antes). Sin un año válido devuelve [] y la pantalla cae al año de hoy.
 */
export const aniosDisponibles = (anioActual, cuantos = 3) => {
    const base = Number(anioActual);
    if (!Number.isInteger(base) || base < 2000) return [];
    const total = Math.max(Number(cuantos) || 1, 1);
    return Array.from({ length: total }, (_, i) => base - i);
};

/** Los 12 meses como opciones { valor, label }. */
export const mesesDelAnio = () => MESES.map((label, i) => ({ valor: i + 1, label }));

/** Trocea 'YYYY-MM-DD' en números (null si no tiene la forma esperada). */
export const partesFecha = (fecha) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(fecha || ''));
    if (!m) return null;
    return { anio: Number(m[1]), mes: Number(m[2]), dia: Number(m[3]) };
};

/** Día de la semana de una fecha 'YYYY-MM-DD' con LUNES = 0 … DOMINGO = 6 (null si no es fecha). */
export const indiceDiaSemana = (fecha) => {
    const p = partesFecha(fecha);
    if (!p) return null;
    // `Date.UTC` + `getUTCDay` para no depender de la zona horaria del navegador.
    const js = new Date(Date.UTC(p.anio, p.mes - 1, p.dia)).getUTCDay();
    return (js + 6) % 7;
};

/** "Martes 15 de octubre" — sin `Date`, para que no la corra la zona horaria. */
export const fechaLarga = (fecha) => {
    const p = partesFecha(fecha);
    if (!p) return '';
    const indice = indiceDiaSemana(fecha);
    const dia = indice === null ? '' : `${DIAS_SEMANA[indice].largo} `;
    return `${dia}${p.dia} de ${nombreMes(p.mes).toLowerCase()}`;
};

/** 'HH:MM' desde 'HH:MM:SS' (los strings del backend). */
export const horaCorta = (valor) => {
    if (!valor) return '';
    const partes = String(valor).split(':');
    return partes.length >= 2 ? `${partes[0]}:${partes[1]}` : String(valor);
};

/**
 * Horarios de inicio presentes en el mes ('HH:MM'), únicos y ordenados: las opciones del
 * filtro "Horario" del Historial del admin. Sale de las MISMAS clases que ya trajo el mes.
 */
export const horariosDe = (clases) => Array.from(new Set(
    (clases || []).map((c) => horaCorta(c?.hora_inicio)).filter(Boolean),
)).sort((a, b) => a.localeCompare(b));

/** 'YYYY-MM-DD' de una fecha local del navegador (para marcar el día de HOY en la grilla). */
export const fechaSola = (fecha) => {
    const d = fecha instanceof Date ? fecha : new Date();
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    return `${d.getFullYear()}-${mm}-${dd}`;
};

/**
 * Clases que YA ocurrieron a la fecha de corte (por defecto, hoy): fecha <= hoy.
 *
 * Los anillos y los totales de asistencia miran SÓLO estas clases: una clase futura
 * todavía no tiene asistencia que medir y sumarla al denominador hunde el % del mes.
 * El calendario y el detalle diario NO usan este recorte: siguen mostrando todo el mes,
 * incluso lo que está por venir.
 *
 * Comparar 'YYYY-MM-DD' como texto ordena igual que las fechas (ISO 8601). Una fila sin
 * fecha válida queda fuera: no puede contarse como ocurrida.
 */
export const clasesOcurridas = (clases, hoy = fechaSola()) => {
    const corte = /^\d{4}-\d{2}-\d{2}/.test(String(hoy || ''))
        ? String(hoy).slice(0, 10)
        : fechaSola();
    return (clases || []).filter((c) => {
        const fecha = String(c?.fecha || '');
        return /^\d{4}-\d{2}-\d{2}/.test(fecha) && fecha <= corte;
    });
};

// ── Una clase ────────────────────────────────────────────────────────────────

/** Presentes de la clase: el contador del backend o, si falta, la lista de alumnos. */
export const presentesDe = (clase) => {
    const n = clase?.marcados_count;
    if (n !== null && n !== undefined && Number.isFinite(Number(n))) {
        return Math.max(Number(n), 0);
    }
    return (clase?.alumnos || []).filter((a) => a?.asistio).length;
};

/** Reservas vigentes de la clase (`reservas_count` del backend; si falta, la lista de alumnos). */
export const reservasDe = (clase) => {
    const n = clase?.reservas_count;
    if (n !== null && n !== undefined && Number.isFinite(Number(n))) {
        return Math.max(Number(n), 0);
    }
    return Array.isArray(clase?.alumnos) ? clase.alumnos.length : 0;
};

/**
 * ¿La clase NO tiene tope? (migración 066): `cupo_maximo` NULL = Musculación /
 * Open Box, salas de acceso libre. No hay denominador, así que la pantalla
 * muestra el CONTEO DE RESERVAS en vez de un porcentaje.
 *
 * Un `undefined` (backend viejo, sin el campo) también se lee como sin tope: el
 * `cuposDe` de abajo devolvía 0 y el % daba 0 igual, pero ahora al menos se dice
 * "sin cupo" en vez de fingir un 0 % de ocupación.
 */
export const sinTopeDe = (clase) => clase?.cupo_maximo === null || clase?.cupo_maximo === undefined;

/** Cupos de la clase (`cupo_maximo`: el mismo tope que pinta el donut del Resumen). */
export const cuposDe = (clase) => Math.max(Number(clase?.cupo_maximo) || 0, 0);

/** Los que reservaron y NO llegaron (nunca negativo; una cancelación no cuenta). */
export const ausentesDe = (clase) => Math.max(reservasDe(clase) - presentesDe(clase), 0);

/** Cupos que quedaron libres (cupo menos reservas vigentes; nunca negativo). */
export const libresDe = (clase) => Math.max(cuposDe(clase) - reservasDe(clase), 0);

/** Porcentaje entero (0-100). Base 0 = 0% (sin división por cero, sin NaN). */
export const porcentaje = (parte, base) => {
    const b = Number(base) || 0;
    if (b <= 0) return 0;
    const p = Math.round((Number(parte) || 0) / b * 100);
    return Math.min(Math.max(p, 0), 100);
};

/** Los alumnos de una clase repartidos en presentes / ausentes (las dos listas del detalle). */
export const alumnosDeClase = (clase) => {
    const lista = Array.isArray(clase?.alumnos) ? clase.alumnos : [];
    return {
        presentes: lista.filter((a) => a?.asistio),
        ausentes: lista.filter((a) => !a?.asistio),
    };
};

/** Ficha de UNA clase para el detalle diario: horas, contadores y las dos listas de alumnos. */
export const fichaClase = (clase) => {
    const { presentes, ausentes } = alumnosDeClase(clase);
    const sinTope = sinTopeDe(clase);
    return {
        clase,
        id: clase?.id,
        hora: horaCorta(clase?.hora_inicio),
        horaFin: horaCorta(clase?.hora_fin),
        disciplina: clase?.disciplina_nombre || 'Clase',
        coach: clase?.coach || 'Sin coach asignado',
        estado: clase?.estado || '',
        // Sin tope (Musculación / Open Box): no hay cupos ni "% del cupo"; la
        // pantalla pinta "acceso libre" y el conteo de reservas.
        sinTope,
        cupos: sinTope ? null : cuposDe(clase),
        reservas: reservasDe(clase),
        presentes: presentesDe(clase),
        ausentes: ausentesDe(clase),
        libres: sinTope ? null : libresDe(clase),
        pct: sinTope ? null : porcentaje(presentesDe(clase), cuposDe(clase)),
        marcada: Boolean(clase?.marcada),
        alumnosPresentes: presentes,
        alumnosAusentes: ausentes,
    };
};

/** Clases de un día, ordenadas por hora de inicio (el mismo orden que manda el backend). */
export const clasesDelDia = (clases, fecha) => (clases || [])
    .filter((c) => c?.fecha === fecha)
    .sort((a, b) => String(a?.hora_inicio || '').localeCompare(String(b?.hora_inicio || '')));

/**
 * Clases de UN horario de inicio ('HH:MM'); sin horario devuelve todas (opción "Todos").
 * Se compara `horaCorta` porque el backend manda 'HH:MM:SS'.
 */
export const filtrarPorHorario = (clases, horario) => (
    horario
        ? (clases || []).filter((c) => horaCorta(c?.hora_inicio) === horario)
        : (clases || [])
);

/**
 * Totales de un conjunto de clases (un día, un día de la semana o el mes entero).
 *
 * ── Migración 066: dos universos, un solo objeto ────────────────────────────
 * Las clases SIN tope (Musculación / Open Box, `cupo_maximo = NULL`) no tienen
 * denominador: sumarlas al `cupos` volvería a inflar el "X de Y cupos" (era el
 * 84 % del denominador y el KPI daba 2,4 %). Por eso:
 *   · `cupos`, `presentesConTope` y `pct` salen SÓLO de las clases con cupo;
 *   · `reservasSinTope` / `clasesSinTope` informan el uso de las salas libres
 *     como CONTEO (nunca como ratio);
 *   · `pct` es `null` cuando NINGUNA clase del conjunto tiene tope: no hay
 *     porcentaje honesto que mostrar y la pantalla dice "sin cupo".
 * `presentes`, `reservas`, `ausentes` y `clases` siguen siendo los totales de
 * TODAS las clases (es la gente real que vino / reservó).
 */
export const totalesDe = (clases) => {
    const lista = clases || [];
    const conTope = lista.filter((c) => !sinTopeDe(c));
    const sinTope = lista.filter(sinTopeDe);
    const presentes = lista.reduce((a, c) => a + presentesDe(c), 0);
    const ausentes = lista.reduce((a, c) => a + ausentesDe(c), 0);
    const reservas = lista.reduce((a, c) => a + reservasDe(c), 0);
    const cupos = conTope.reduce((a, c) => a + cuposDe(c), 0);
    const presentesConTope = conTope.reduce((a, c) => a + presentesDe(c), 0);
    const reservasSinTope = sinTope.reduce((a, c) => a + reservasDe(c), 0);
    return {
        clases: lista.length,
        presentes,
        ausentes,
        reservas,
        cupos,
        // Conteo aparte de las salas de acceso libre (migración 066).
        clasesSinTope: sinTope.length,
        reservasSinTope,
        presentesConTope,
        // `null` = hay clases pero NINGUNA tiene cupo -> no hay % que calcular.
        // Un conjunto VACÍO sigue dando 0 (no hay nada que medir, y así lo
        // esperan las pantallas y `scripts/test-historial-asistencia.mjs`).
        pct: lista.length === 0
            ? 0
            : (conTope.length === 0 ? null : porcentaje(presentesConTope, cupos)),
        libres: Math.max(cupos - (reservas - reservasSinTope), 0),
        // Clases con la asistencia ya cerrada (todas sus reservas vigentes marcadas).
        cerradas: lista.filter((c) => c?.marcada).length,
    };
};

// ── Un día / un día de la semana / el mes ────────────────────────────────────

/**
 * Cuenta por ALUMNO las veces que aparece presente (o ausente) en una lista de clases: son las
 * listas que se abren al tocar el anillo de un día de la semana (quién vino y quién no).
 * Orden: primero el que más veces aparece; a igual cantidad, por nombre.
 */
export const alumnosContados = (clases, asistio) => {
    const mapa = new Map();
    for (const c of (clases || [])) {
        for (const a of (c?.alumnos || [])) {
            if (Boolean(a?.asistio) !== asistio) continue;
            const clave = a?.alumno_id ?? a?.nombre;
            const previo = mapa.get(clave) || {
                alumno_id: a?.alumno_id ?? null,
                nombre: a?.nombre || 'Alumno',
                veces: 0,
            };
            previo.veces += 1;
            mapa.set(clave, previo);
        }
    }
    return [...mapa.values()]
        .sort((a, b) => b.veces - a.veces || a.nombre.localeCompare(b.nombre));
};

/** Ausentes que la clase NO puede nombrar (backend viejo, sin la lista de alumnos). */
export const ausentesSinNombre = (clases) => (clases || []).reduce((total, c) => {
    const nombrados = (c?.alumnos || []).filter((a) => !a?.asistio).length;
    return total + Math.max(ausentesDe(c) - nombrados, 0);
}, 0);

/**
 * Los 7 días de la semana (lunes→domingo) con sus totales y sus dos listas de alumnos: es lo
 * que dibuja el anillo de cada círculo. Un día sin clases queda con ceros (y el anillo vacío),
 * NUNCA se esconde: el mockup muestra los 7 siempre.
 */
export const resumenPorDiaSemana = (clases) => DIAS_SEMANA.map((dia, indice) => {
    const delDia = (clases || []).filter((c) => indiceDiaSemana(c?.fecha) === indice);
    const totales = totalesDe(delDia);
    return {
        ...dia,
        indice,
        clases: delDia,
        totales,
        pct: totales.pct,
        alumnosPresentes: alumnosContados(delDia, true),
        alumnosAusentes: alumnosContados(delDia, false),
        sinNombre: ausentesSinNombre(delDia),
    };
});

/** El detalle de UN día: sus totales y una ficha por bloque horario (ya ordenadas por hora). */
export const resumenDia = (clases, fecha) => {
    const delDia = clasesDelDia(clases, fecha);
    return {
        fecha,
        titulo: fechaLarga(fecha),
        totales: totalesDe(delDia),
        fichas: delDia.map(fichaClase),
    };
};

/**
 * La grilla del mes para el calendario: semanas de 7 celdas (LUNES primero) y `null` en los
 * huecos del primer y del último tramo (lo que dibuja un espacio vacío, no un día de otro mes).
 * Cada celda trae lo del día (`clases`, `totales`) y las tres banderas que el calendario pinta:
 * `hoy`, `esFuturo` (un día que todavía no ocurrió: sin asistencia que mirar) y `enMes`.
 *
 * `hoy` se pasa desde afuera ('YYYY-MM-DD' del navegador) para que la función siga siendo pura
 * y el test pueda fijarlo.
 */
export const calendarioDelMes = (anio, mes, clases, hoy = fechaSola()) => {
    const a = Number(anio);
    const m = Number(mes);
    if (!Number.isInteger(a) || !Number.isInteger(m) || m < 1 || m > 12) return [];
    const primerDiaSemana = new Date(Date.UTC(a, m - 1, 1)).getUTCDay();
    const huecos = (primerDiaSemana + 6) % 7;              // lunes primero
    const ultimoDia = new Date(Date.UTC(a, m, 0)).getUTCDate();
    const celdas = [];
    for (let i = 0; i < huecos; i++) celdas.push(null);
    for (let dia = 1; dia <= ultimoDia; dia++) {
        const fecha = `${a}-${String(m).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
        const delDia = clasesDelDia(clases, fecha);
        celdas.push({
            fecha,
            dia,
            enMes: true,
            hoy: fecha === hoy,
            // Comparar 'YYYY-MM-DD' como texto ordena igual que las fechas (ISO 8601).
            esFuturo: fecha > hoy,
            clases: delDia,
            totales: totalesDe(delDia),
        });
    }
    while (celdas.length % 7 !== 0) celdas.push(null);
    const semanas = [];
    for (let i = 0; i < celdas.length; i += 7) semanas.push(celdas.slice(i, i + 7));
    return semanas;
};
