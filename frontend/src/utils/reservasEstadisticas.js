/**
 * Estadísticas y agrupación de "Mis Reservas" (rediseño).
 *
 * POR QUÉ EXISTE: el rediseño agrega 3 tarjetas de estadísticas arriba de la lista
 * (clases del mes, % de asistencia y racha actual) y agrupa el historial por mes.
 * Todo se calcula en cliente a partir del MISMO array `reservas` que ya carga la
 * pantalla (GET /reservas), sin red.
 *
 * Racha: reutiliza el MISMO criterio que `utils/asistenciaEvolucion.js`
 * (`calcularRachaAsistencia`): semanas ISO consecutivas con >= 1 asistencia; un
 * hueco (semana sin datos) corta la racha. Para poder reutilizarla, acá se agrupan
 * las reservas con estado "asistio" por semana ISO ('YYYY-Sww').
 */
import { estadoVisible } from './estadoReserva.js';
import { calcularRachaAsistencia } from './asistenciaEvolucion.js';

const MESES = [
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
];

/** Semana ISO de una fecha 'YYYY-MM-DD' en formato 'YYYY-Sww' (misma clave que asistenciaEvolucion). */
export function semanaISO(fechaStr) {
    if (!fechaStr) return null;
    const d = new Date(`${fechaStr}T12:00:00`);
    if (Number.isNaN(d.getTime())) return null;
    const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const day = date.getUTCDay() || 7; // 1 = lunes ... 7 = domingo
    date.setUTCDate(date.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
    const week = Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
    return `${date.getUTCFullYear()}-S${String(week).padStart(2, '0')}`;
}

/**
 * Estadísticas de la cabecera: clases del mes actual (reservadas y asistidas), % de
 * asistencia del historial (asistió / total del historial) y racha actual de semanas
 * con al menos 1 asistencia.
 */
// Estados que CUENTAN para el % de asistencia: espejo de `ESTADOS_QUE_CUENTAN`
// del backend (`historial_alumno_service`). Cancelar a tiempo NO ensucia el
// número; una cancelación tardía sí cuenta como falta. `reservada` (activa) no
// entra porque todavía no ocurrió.
const ESTADOS_QUE_CUENTAN_PCT = ['asistio', 'falto', 'cancelada_tarde'];

/** % de asistencia redondeado (mismo `Math.round` que el resto de la app). */
export function porcentajeAsistencia(reservas) {
    const cuentan = (reservas || []).filter(
        (r) => ESTADOS_QUE_CUENTAN_PCT.includes(estadoVisible(r)),
    );
    if (!cuentan.length) return 0;
    const asistidas = cuentan.filter((r) => estadoVisible(r) === 'asistio').length;
    return Math.round((asistidas / cuentan.length) * 100);
}

export function calcularEstadisticasReservas(reservas, hoyStr) {
    const lista = reservas || [];
    const mesActual = String(hoyStr || '').slice(0, 7); // 'YYYY-MM'

    const clasesEsteMes = lista.filter((r) => String(r?.clase_fecha || '').slice(0, 7) === mesActual).length;
    // Solo las del mes actual a las que el alumno ASISTIÓ de verdad (mismo estado
    // visible que el historial). La tarjeta "Clases este mes" las muestra juntas:
    // "X reservadas / Y asistidas", para no confundir ambas cosas.
    const asistidasEsteMes = lista.filter(
        (r) => String(r?.clase_fecha || '').slice(0, 7) === mesActual && estadoVisible(r) === 'asistio',
    ).length;

    const pctAsistencia = porcentajeAsistencia(lista);

    // Racha: agrupar las asistencias por semana ISO y delegar el cálculo (no se duplica).
    const porSemana = new Map();
    lista.forEach((r) => {
        if (estadoVisible(r) !== 'asistio' || !r?.clase_fecha) return;
        const s = semanaISO(r.clase_fecha);
        if (!s) return;
        if (!porSemana.has(s)) porSemana.set(s, { semana: s, asistencias: 0, total: 0 });
        const w = porSemana.get(s);
        w.asistencias += 1;
        w.total += 1;
    });
    const { rachaActual } = calcularRachaAsistencia([...porSemana.values()]);

    return { clasesEsteMes, asistidasEsteMes, pctAsistencia, rachaActual };
}

/** Etiqueta de mes 'YYYY-MM' -> 'Noviembre 2026'. */
export function etiquetaMes(claveMes) {
    const [anio, mes] = String(claveMes || '').split('-');
    const idx = Number(mes) - 1;
    if (!anio || MESES[idx] == null) return claveMes || '';
    return `${MESES[idx]} ${anio}`;
}

/**
 * Agrupa el HISTORIAL por mes (descendente, el más reciente primero). Devuelve
 * [{ clave: 'YYYY-MM', label: 'Noviembre 2026', reservas: [...] }]. Las reservas sin
 * fecha legible se descartan (no hay mes que mostrar).
 */
export function agruparReservasPorMes(reservas) {
    const grupos = new Map();
    (reservas || []).forEach((r) => {
        if (!r?.clase_fecha) return;
        const d = new Date(`${r.clase_fecha}T12:00:00`);
        if (Number.isNaN(d.getTime())) return;
        const clave = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        if (!grupos.has(clave)) grupos.set(clave, []);
        grupos.get(clave).push(r);
    });
    return [...grupos.entries()]
        .sort((a, b) => b[0].localeCompare(a[0])) // 'YYYY-MM' descendente
        .map(([clave, reservasMes]) => ({ clave, label: etiquetaMes(clave), reservas: reservasMes }));
}

// ── Filtro por mes del historial ("Mis Reservas") ───────────────────────────
// `'Todos'` es el valor de la UI para "sin filtrar" (mismo rol que 'Todas' en
// `utils/estadoReserva.js`): no se persiste entre visitas, arranca siempre ahí.
export const TODOS_LOS_MESES = 'Todos';

/**
 * Filtra los grupos que devuelve `agruparReservasPorMes` por mes ('YYYY-MM').
 * `TODOS_LOS_MESES` (o vacío) devuelve los grupos tal cual. La pantalla lo aplica
 * DESPUÉS de los filtros de disciplina y estado, así los tres se combinan (AND)
 * sin recalcular la agrupación.
 */
export function filtrarGruposPorMes(grupos, claveMes) {
    if (!claveMes || claveMes === TODOS_LOS_MESES) return grupos || [];
    return (grupos || []).filter((grupo) => grupo.clave === claveMes);
}
