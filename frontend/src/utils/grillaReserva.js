// ─── Grilla de reserva del alumno ────────────────────────────────────────────
// Fuente ÚNICA de (a) los próximos 7 días anclados al calendario chileno y
// (b) los dos agrupados que pinta la grilla de reserva. La consumen el Inicio
// (Dashboard ≥768px) y la pestaña "Agendar Reserva", para que las dos
// pantallas muestren exactamente los mismos días, clases y franjas.
//
// Antes vivía dentro de `pages/alumno/Dashboard.jsx`; al extraer la grilla a
// `components/GrillaReservaClases.jsx` se movió acá para no duplicar la regla
// de zona horaria ni el agrupado.
import { fechaSolaAInstante, hoyChileStr } from './fecha';

const NOMBRES_DIA = ['DOMINGO', 'LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES', 'SÁBADO'];

// Próximos 7 días (HOY + 6) sobre la fecha chilena, anclada a mediodía UTC
// para que sumar días no se corra por la zona horaria del navegador.
export const getProximosDias = (hoy = hoyChileStr()) => {
    const dias = [];
    const base = fechaSolaAInstante(hoy);
    for (let i = 0; i < 7; i++) {
        const fecha = new Date(base.getTime() + i * 24 * 60 * 60 * 1000);
        const fechaStr = fecha.toISOString().slice(0, 10);
        dias.push({
            fecha: fechaStr,
            nombreDia: NOMBRES_DIA[fecha.getUTCDay()],
            diaNum: fecha.getUTCDate(),
            mes: fecha.getUTCMonth() + 1,
        });
    }
    return dias;
};

// Clases agrupadas por día de clase (`fecha` o `fecha_clase`). El Inicio las
// usa además para el Inicio móvil, así que conserva TODAS las clases del día.
export const agruparClasesPorDia = (clases) => {
    const agrupadas = {};
    (clases || []).forEach((clase) => {
        const fechaClase = clase.fecha || clase.fecha_clase;
        if (!fechaClase) return;
        if (!agrupadas[fechaClase]) agrupadas[fechaClase] = [];
        agrupadas[fechaClase].push(clase);
    });
    return agrupadas;
};

// Helper: una fila por (disciplina, hora_inicio, hora_fin) — la grilla muestra
// el representante de cada grupo, no una fila por clase dictada.
const agruparClasesRepetidas = (clases) => {
    const grupos = {};
    (clases || []).forEach((c) => {
        const key = `${c.disciplina_nombre || ''}|${c.hora_inicio || ''}|${c.hora_fin || ''}`;
        if (!grupos[key]) grupos[key] = c;
    });
    return Object.values(grupos);
};

// Helper: separa las clases del día en Mañana (<14:00) / Tarde (>=14:00),
// aplicado DESPUÉS de agrupar las filas repetidas.
export const separarClasesPorFranja = (clases) => {
    const manana = [];
    const tarde = [];
    agruparClasesRepetidas(clases).forEach((c) => {
        const fallback = c.hora_inicio || '00:00';
        const hora = parseInt(fallback.split(':')[0], 10);
        if (hora < 14) {
            manana.push(c);
        } else {
            tarde.push(c);
        }
    });
    return { manana, tarde };
};
