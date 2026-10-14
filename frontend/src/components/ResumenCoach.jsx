import React from 'react';
import {
    etiquetaEstado, estadoFila, horaCorta, reservasDe, textoProgreso,
} from '../utils/franjasAsistencia';

/**
 * Resumen del panel del coach (mockup `#pantalla-resumen`).
 *
 * MOBILE-FIRST: el mockup aprobado es el diseño final para TODOS los anchos, así que esto
 * no se reordena en escritorio: el contenido se limita a `max-w-2xl` y queda centrado — la
 * MISMA tarjeta del teléfono, sin inventar un layout de PC (si algún día se quiere uno, se
 * decide antes, no acá).
 *
 * LO QUE SE VE ES EL MOCKUP, CAMPO POR CAMPO (`#pantalla-resumen`), en este orden:
 *   1. el grid 2x2: Clases hoy · Alumnos activos · WOD del día (con el botón inline
 *      "+ Publicar WOD") · En riesgo;
 *   2. la tarjeta ANCHA de Asistencia (ocupa las 2 columnas): los 3 números —con reserva /
 *      ya marcaron / faltan—, clickeable, con "+ Agregar alumno sin reserva" adentro;
 *   3. "Mis clases de hoy": una fila por clase, con su barra de color y su badge de estado.
 *
 * LA REGLA DE NEGOCIO QUE ORDENA LA PANTALLA (y su copy): el alumno RESERVA y marca su
 * propia asistencia; el coach revisa y corrige a quien falte. El crédito se descuenta al
 * RESERVAR (`POST /reservas`), no cuando el coach marca: por eso la tarjeta de Asistencia
 * habla de "con reserva / ya marcaron / faltan" —nunca de cobros— y el único botón de
 * corrección es "Agregar alumno sin reserva", que dice ahí mismo si descuenta el crédito.
 *
 * LOS ESTADOS NO SE RE-IMPLEMENTAN ACÁ: salen de `utils/franjasAsistencia` (`estadoFila`,
 * `etiquetaEstado` y `textoProgreso`), los mismos que usa la pestaña Asistencia —"12/12
 * presentes", "9/14 marcados", "Hecha" / "En curso" / "Pendiente"—, para que las dos
 * pantallas que muestran el mismo día no puedan decir cosas distintas.
 *
 * OJO CON LA SKIN (`src/index.css`): reescribe `bg-emerald-500` a NARANJA con `!important`,
 * así que la barra verde de "Hecha" va con `bg-green-500` (que la skin no toca y es el verde
 * del mockup) y los badges usan tonos 300/950, que tampoco aparecen en la skin.
 *
 * Props (todo lo que necesita ya lo tiene el Dashboard: acá no se piden datos):
 *   clasesHoy         clases de hoy del coach (con `estado`, `marcada` y `reservas_count`
 *                     cuando el backend de Asistencia los trae),
 *   alumnosActivos    alumnos del coach · alumnosConRms los que tienen alguna marca,
 *   wodHoy            WOD de hoy (sin publicar o en borrador = "Sin publicar"),
 *   enRiesgo/umbralRiesgo  alumnos sin entrenar y el umbral en días,
 *   proximaClase      la clase EN CURSO o la próxima de hoy (null si ya no queda),
 *   reservasProxima   reservas de esa clase: `asistio` → los 3 números del mockup,
 *   sinAsignaciones   el coach todavía NO tiene disciplinas ni clases asignadas: los 0 son
 *                     reales por falta de asignación, así que la pantalla lo dice en vez
 *                     de mostrar un 0 mudo (el caso que llegó de PROD),
 *   onPublicarWod · onAgregarSinReserva(clase) · onAbrirAsistencia · onAbrirClase(clase)
 *   · onIrA(tab) · onAbrirDetalleWod(clase, wod).
 */
// Barra de la fila y badge del estado, con los colores del mockup: verde la hecha, roja la
// que está en curso y ámbar la que todavía no parte.
const BARRA = {
    hecha: 'bg-green-500',
    'en-curso': 'bg-red-500',
    pendiente: 'bg-amber-500',
};
const BADGE = {
    hecha: 'text-emerald-300 bg-emerald-950/60',
    'en-curso': 'text-red-200 bg-red-950/60',
    pendiente: 'text-amber-200 bg-amber-950/60',
};

const ResumenCoach = ({
    clasesHoy = [], alumnosActivos = 0, alumnosConRms = 0, wodHoy = null,
    enRiesgo = 0, umbralRiesgo = 7, proximaClase = null, reservasProxima = [],
    cargandoReservas = false, sinAsignaciones = false, onPublicarWod, onAgregarSinReserva,
    onAbrirAsistencia, onAbrirClase, onIrA, onAbrirDetalleWod,
}) => {
    const asistentesHoy = clasesHoy.reduce(
        (total, c) => total + (c.asistentes_confirmados ?? 0), 0);

    // Los 3 números del mockup: los que reservaron, los que YA marcaron y los que faltan.
    const conReserva = proximaClase?.reservas_count ?? reservasProxima.length;
    const yaMarcaron = reservasProxima.filter((r) => r.asistio).length;
    const faltan = Math.max(conReserva - yaMarcaron, 0);

    // El KPI del WOD: publicado muestra su título; sin WOD —o en borrador— dice
    // "Sin publicar", que es lo que al coach le queda por hacer ese día.
    const wodPublicado = Boolean(wodHoy && wodHoy.estado === 'publicado');

    // Radios del mockup: .kpi/.item 9px, .badge 6px, el botón del walk-in 7px.
    const KPI = 'rounded-[9px] border border-zinc-800 bg-zinc-900 p-3 text-left transition-colors';
    const KPI_TOCABLE = `${KPI} hover:border-zinc-700 active:bg-zinc-800`;

    return (
        <div className="mx-auto max-w-2xl space-y-3" data-testid="coach-resumen">
            {/* ── 1. Grid 2x2 del mockup ── */}
            <div className="grid grid-cols-2 gap-2.5">
                <button type="button" onClick={() => onIrA && onIrA('clases')}
                    data-testid="kpi-clases-hoy" className={KPI_TOCABLE}>
                    <p className="text-[10px] uppercase tracking-wide text-zinc-500">Clases hoy</p>
                    <p className="mt-1 text-2xl font-bold text-zinc-100">{clasesHoy.length}</p>
                    {/* Si el coach no tiene NADA asignado, el 0 no se explica solo: acá
                        arriba es donde primero se mira cuando "todo está en 0". */}
                    <p className="text-[10.5px] text-zinc-400">{sinAsignaciones
                        ? 'Sin clases asignadas'
                        : `${asistentesHoy} asistentes`}</p>
                </button>

                <button type="button" onClick={() => onIrA && onIrA('alumnos')}
                    data-testid="kpi-alumnos" className={KPI_TOCABLE}>
                    <p className="text-[10px] uppercase tracking-wide text-zinc-500">Alumnos activos</p>
                    <p className="mt-1 text-2xl font-bold text-emerald-300">{alumnosActivos}</p>
                    <p className="text-[10.5px] text-zinc-400">{alumnosConRms} con RMs</p>
                </button>

                <div className={`${KPI} flex flex-col p-0`}>
                    <button type="button"
                        onClick={() => (wodHoy
                            ? onAbrirDetalleWod && onAbrirDetalleWod(proximaClase, wodHoy)
                            : onIrA && onIrA('clases'))}
                        className="flex-1 px-3 pb-2 pt-3 text-left">
                        <p className="text-[10px] uppercase tracking-wide text-zinc-500">WOD del día</p>
                        <p className={`mt-1 text-[15px] font-bold ${wodPublicado ? 'text-zinc-100' : 'text-amber-300'}`}>
                            {wodPublicado ? (wodHoy.titulo || 'Publicado') : 'Sin publicar'}
                        </p>
                    </button>
                    <button type="button" onClick={onPublicarWod} data-testid="abrir-publicar-wod"
                        className="mx-3 mb-3 rounded-md border-[1.5px] border-[#a68318] bg-[#e8a93b] px-2 py-2 text-[10.5px] font-bold text-[#1a1608] hover:bg-[#f0b64f]">
                        + Publicar WOD
                    </button>
                </div>

                <button type="button" onClick={() => onIrA && onIrA('riesgo')}
                    data-testid="kpi-riesgo" className={KPI_TOCABLE}>
                    <p className="text-[10px] uppercase tracking-wide text-zinc-500">En riesgo</p>
                    <p className={`mt-1 text-2xl font-bold ${enRiesgo > 0 ? 'text-red-300' : 'text-zinc-100'}`}>
                        {enRiesgo}
                    </p>
                    <p className="text-[10.5px] text-zinc-400">Sin asistir {umbralRiesgo}+ días</p>
                </button>
            </div>
            {/* ── 2. La tarjeta ANCHA de Asistencia (ocupa las 2 columnas) ──
                Los hex son los del mockup (degradado cálido + borde #4a3a1a): van como valores
                arbitrarios a propósito, para que la skin no los reescriba. */}
            <div className="rounded-[9px] border border-[#4a3a1a] bg-[linear-gradient(145deg,#231f14,#15130d)]"
                data-testid="tarjeta-asistencia">
                {proximaClase ? (
                    <>
                        <button type="button" onClick={onAbrirAsistencia}
                            className="block w-full px-3 pb-2 pt-3 text-left">
                            <p className="text-[10px] uppercase tracking-wide text-zinc-500">
                                Asistencia · próxima clase, {horaCorta(proximaClase.hora_inicio)}{' '}
                                {proximaClase.disciplina_nombre}
                            </p>
                            <div className="mt-1 flex items-baseline gap-4">
                                <span>
                                    <span className="text-2xl font-bold text-zinc-100">{conReserva}</span>
                                    <span className="ml-1 text-[10px] text-zinc-500">con reserva</span>
                                </span>
                                <span>
                                    <span className="text-2xl font-bold text-emerald-300">{yaMarcaron}</span>
                                    <span className="ml-1 text-[10px] text-zinc-500">ya marcaron</span>
                                </span>
                                <span>
                                    <span className="text-2xl font-bold text-amber-200">{faltan}</span>
                                    <span className="ml-1 text-[10px] text-zinc-500">faltan</span>
                                </span>
                            </div>
                            <p className="mt-1 text-[10.5px] text-zinc-400">
                                {cargandoReservas ? 'Cargando la asistencia…' : 'Toca para ver quiénes faltan'}
                            </p>
                        </button>
                        <button type="button"
                            onClick={() => onAgregarSinReserva && onAgregarSinReserva(proximaClase)}
                            data-testid="resumen-agregar-sin-reserva"
                            className="mx-3 mb-3 flex w-[calc(100%-1.5rem)] items-center justify-center gap-1.5 rounded-[7px] border-[1.5px] border-dashed border-[#4a3a1a] px-3 py-2.5 text-[11px] font-semibold text-[#d9c9a3] hover:border-[#8a6a2a] hover:text-[#eadfc8]">
                            + Agregar alumno sin reserva
                        </button>
                    </>
                ) : (
                    <p className="px-3 py-4 text-[12px] text-zinc-400">
                        No quedan clases por delante hoy.
                    </p>
                )}
            </div>
            {/* ── 3. Mis clases de hoy (las mismas filas del mockup) ── */}
            <div>
                <p className="mb-2 px-0.5 text-[11px] uppercase tracking-wide text-zinc-500">
                    Mis clases de hoy
                </p>
                {clasesHoy.length === 0 ? (
                    <p className="rounded-[9px] border border-zinc-800 bg-zinc-900 px-3 py-4 text-center text-[12px] text-zinc-400"
                        data-testid="resumen-sin-clases">
                        {sinAsignaciones
                            ? 'Todavía no tienes clases asignadas: pídele al admin que te asigne tus disciplinas u horarios.'
                            : 'No tienes clases programadas para hoy. Si esperabas tener, revisa con el admin que tus disciplinas y horarios estén cargados.'}
                    </p>
                ) : (
                    <div className="space-y-2">
                        {clasesHoy.map((clase) => {
                            const estado = estadoFila(clase);
                            // El progreso lo escribe el MISMO helper de la pestaña Asistencia
                            // ("12/12 presentes" / "9/14 marcados"): el tope son las reservas de
                            // esa clase (los que se esperan), no el cupo nominal.
                            const esperados = reservasDe(clase);
                            return (
                                <button key={clase.id} type="button"
                                    onClick={() => onAbrirClase && onAbrirClase(clase)}
                                    data-testid={`clase-hoy-${clase.id}`}
                                    className="flex w-full items-center gap-3 rounded-[9px] border border-zinc-800 bg-zinc-900 px-3 py-2.5 text-left hover:border-zinc-700">
                                    <span className={`h-8 w-1 flex-none rounded ${BARRA[estado]}`} />
                                    <span className="flex-1">
                                        <span className="block text-[13px] font-semibold text-zinc-100">
                                            {horaCorta(clase.hora_inicio)} · {clase.disciplina_nombre || 'Clase'}
                                        </span>
                                        <span className="block text-[10.5px] text-zinc-400">
                                            {textoProgreso(clase, esperados > 0 ? esperados : undefined)}
                                        </span>
                                    </span>
                                    <span className={`flex-none rounded-[6px] px-2 py-1 text-[9.5px] font-bold ${BADGE[estado]}`}>
                                        {etiquetaEstado(estado)}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
};

export default ResumenCoach;

