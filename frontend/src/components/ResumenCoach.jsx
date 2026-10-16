import React from 'react';
import {
    estadoFila, etiquetaEstado, horaCorta, ocupacion, reservasDe, textoProgreso,
} from '../utils/franjasAsistencia';
import { etiquetaTipo } from '../utils/avisosMarketing';

/**
 * Resumen del panel del coach (pestaña Resumen) — rediseño "energético" del mockup
 * `mockup/mockup-dashboard-energetico.html`.
 *
 * QUÉ CAMBIÓ Y POR QUÉ: la versión anterior abría con un grid 2x2 de KPIs (Clases hoy ·
 * Alumnos activos · WOD del día · En riesgo) y una lista larga de "Mis clases de hoy", todas
 * iguales. El panel se usa MINUTO A MINUTO para marcar asistencia, así que la pantalla ahora
 * se ordena alrededor de UNA pregunta —"¿cómo va la clase que tengo ahora?"—:
 *
 *   1. "Asistencia de hoy" + fecha + cuántas clases hay programadas;
 *   2. la tarjeta grande de la clase EN CURSO (o la próxima): donut marcados/cupo, nombre,
 *      los 3 números (con reserva / ya marcaron / faltan) y el botón "Marcar asistencia",
 *      todo apilado y centrado;
 *   3. la tarjeta del WOD del día (estado + "+ Publicar WOD": abre el modal de siempre);
 *   4. "+ Agregar alumno sin reserva" (el walk-in que ya existía);
 *   5. "Avisos para alumnos" + "+ Nuevo aviso" (el aviso rápido del día; Promociones,
 *      Colaboraciones y Eventos los publica el admin desde Marketing);
 *   6. el resto de las clases de hoy, en una fila horizontal con un mini-donut por clase;
 *   7. la ocupación por horario (una barra por clase) al final.
 *
 * LO QUE NO CAMBIA: los números y los estados salen de `utils/franjasAsistencia` —los mismos
 * helpers de la pestaña Asistencia— así que dos pantallas del mismo día no pueden decir cosas
 * distintas. Esta pantalla NO llama a la API: todo llega por props del Dashboard.
 *
 * SKIN: los colores del mockup viajan como valores arbitrarios de Tailwind (`bg-[#18181B]`,
 * `border-[#D7FF4A]`) porque `src/index.css` reescribe varias paletas con `!important`.
 *
 * Props: `clasesHoy` (con estado/marcada/reservas) · `proximaClase` (la en curso o la que
 * sigue) · `reservasProxima` (reservas de ESA clase) · `cargandoReservas` · `wodHoy` ·
 * `avisos` (los vigentes hoy) · `fechaCorta` · `sinAsignaciones` · `onPublicarWod` ·
 * `onAgregarSinReserva(clase)` · `onAbrirAsistencia` · `onAbrirClase(clase)` ·
 * `onAbrirDetalleWod(clase, wod)` · `onNuevoAviso`.
 */

/**
 * Donut SVG (marcados vs cupo). `mini` = la versión de las tarjetas chicas (el texto del
 * centro pasa a "3/16" y no lleva la leyenda "DE N CUPOS"): los dos tamaños salen del MISMO
 * componente para que el arco y el número no se desincronicen.
 */
const Donut = ({ marcados = 0, cupo = 0, tamano = 190, grosor = 20, mini = false }) => {
    const radio = (tamano - grosor) / 2 - 2;
    const circunferencia = 2 * Math.PI * radio;
    const pct = cupo > 0 ? Math.min(Math.max(marcados, 0) / cupo, 1) : 0;
    const centro = tamano / 2;
    return (
        <svg width={tamano} height={tamano} viewBox={`0 0 ${tamano} ${tamano}`}
            role="img" aria-label={`${marcados} de ${cupo} cupos`}>
            <circle cx={centro} cy={centro} r={radio} fill="none"
                stroke="#242428" strokeWidth={grosor} />
            <circle cx={centro} cy={centro} r={radio} fill="none"
                stroke="#D7FF4A" strokeWidth={grosor}
                strokeDasharray={circunferencia}
                strokeDashoffset={circunferencia * (1 - pct)}
                strokeLinecap="round"
                transform={`rotate(-90 ${centro} ${centro})`} />
            <text x={centro} y={mini ? centro + tamano * 0.08 : centro - tamano * 0.03}
                textAnchor="middle" fontSize={tamano * (mini ? 0.24 : 0.22)}
                fontWeight="900" fill="#fff">
                {mini ? `${marcados}/${cupo}` : marcados}
            </text>
            {!mini && (
                <text x={centro} y={centro + tamano * 0.12} textAnchor="middle"
                    fontSize={tamano * 0.072} fontWeight="700" fill="#8C8C92">
                    DE {cupo} CUPOS
                </text>
            )}
        </svg>
    );
};

// Acento del mockup (verde-lima) y las clases que se repiten.
const BOTON_LIMA = 'rounded-[14px] bg-[#D7FF4A] px-4 py-2.5 text-[12.5px] font-black text-[#0E0E10] hover:bg-[#E8FF8A] transition-colors';
const TARJETA = 'rounded-[18px] border border-[#2A2A2E] bg-[#18181B] p-4';
const ROTULO = 'text-[10.5px] font-extrabold uppercase tracking-[0.06em] text-zinc-500';
const BADGE_ESTADO = {
    hecha: 'text-emerald-300 bg-emerald-950/60',
    'en-curso': 'text-[#0E0E10] bg-[#D7FF4A]',
    pendiente: 'text-amber-200 bg-amber-950/60',
};

const ResumenCoach = ({
    clasesHoy = [], proximaClase = null, reservasProxima = [], cargandoReservas = false,
    wodHoy = null, avisos = [], fechaCorta = '', sinAsignaciones = false,
    onPublicarWod, onAgregarSinReserva, onAbrirAsistencia, onAbrirClase, onAbrirDetalleWod,
    onNuevoAviso,
}) => {
    // Los 3 números del mockup: los que reservaron, los que YA marcaron y los que faltan.
    // Salen del detalle de ESA clase (`reservasProxima`), con el respaldo de `reservas_count`,
    // igual que la pestaña Asistencia.
    const conReserva = proximaClase?.reservas_count ?? reservasProxima.length;
    const yaMarcaron = reservasProxima.filter((r) => r.asistio).length;
    const faltan = Math.max(conReserva - yaMarcaron, 0);
    const cupo = Number(proximaClase?.cupo_maximo) || 0;

    const estadoProxima = proximaClase ? estadoFila(proximaClase) : 'pendiente';
    const enCurso = estadoProxima === 'en-curso';

    // El WOD del día: publicado muestra su título; sin WOD —o en borrador— "Sin publicar",
    // que es lo que al coach le queda por hacer ese día.
    const wodPublicado = Boolean(wodHoy && wodHoy.estado === 'publicado');

    // El resto del día (sin la clase de la tarjeta grande) para la fila horizontal.
    const restoDelDia = clasesHoy.filter((c) => c.id !== proximaClase?.id);

    return (
        <div className="mx-auto max-w-3xl space-y-5" data-testid="coach-resumen">
            {/* ── 1. Qué es esta pantalla y cuánto hay hoy ── */}
            <div>
                <h1 className="text-3xl font-black uppercase tracking-tight text-white sm:text-4xl">
                    Asistencia de hoy
                </h1>
                <p className="mt-1 text-[12.5px] font-semibold uppercase tracking-wide text-zinc-400">
                    {fechaCorta} · {clasesHoy.length} clase{clasesHoy.length === 1 ? '' : 's'}{' '}
                    programada{clasesHoy.length === 1 ? '' : 's'}
                </p>
            </div>

            {/* ── 2. La clase EN CURSO (o la próxima): el corazón de la pantalla ── */}
            {proximaClase && (
                <div className="rounded-[28px] border-2 border-[#D7FF4A] bg-[linear-gradient(135deg,#1C1C20,#121214)] px-5 py-7 text-center sm:px-10 sm:py-9"
                    data-testid="tarjeta-asistencia">
                    <div className="flex items-center justify-center gap-2.5">
                        <span className="h-2.5 w-2.5 rounded-full bg-[#D7FF4A]" aria-hidden="true" />
                        <span className="text-[12px] font-extrabold uppercase tracking-[0.06em] text-[#D7FF4A]">
                            {enCurso ? 'En curso ahora' : 'Próxima clase'}
                        </span>
                    </div>

                    <div className="mt-5 flex justify-center">
                        <Donut marcados={yaMarcaron} cupo={cupo} />
                    </div>

                    <p className="mt-4 text-2xl font-black leading-tight text-white sm:text-3xl">
                        {horaCorta(proximaClase.hora_inicio)} · {proximaClase.disciplina_nombre || 'Clase'}
                    </p>

                    <div className="mt-4 flex items-start justify-center gap-8 sm:gap-12">
                        <span>
                            <span className="block text-2xl font-black text-zinc-100">{conReserva}</span>
                            <span className="block text-[10.5px] uppercase tracking-wide text-zinc-500">con reserva</span>
                        </span>
                        <span>
                            <span className="block text-2xl font-black text-[#D7FF4A]">{yaMarcaron}</span>
                            <span className="block text-[10.5px] uppercase tracking-wide text-zinc-500">ya marcaron</span>
                        </span>
                        <span>
                            <span className="block text-2xl font-black text-amber-200">{faltan}</span>
                            <span className="block text-[10.5px] uppercase tracking-wide text-zinc-500">faltan</span>
                        </span>
                    </div>

                    <button type="button" onClick={onAbrirAsistencia}
                        data-testid="abrir-marcar-asistencia"
                        className={`${BOTON_LIMA} mt-6 w-full max-w-xs uppercase tracking-wide py-3`}>
                        Marcar asistencia
                    </button>
                    <p className="mt-2 text-[11.5px] text-zinc-500">
                        {cargandoReservas
                            ? 'Cargando la asistencia…'
                            : `Estado: ${etiquetaEstado(estadoProxima)} · ${textoProgreso(proximaClase, cupo || undefined)}`}
                    </p>

                    <button type="button"
                        onClick={() => onAgregarSinReserva && onAgregarSinReserva(proximaClase)}
                        data-testid="resumen-agregar-sin-reserva"
                        className="mx-auto mt-4 flex w-full max-w-xs items-center justify-center gap-1.5 rounded-[10px] border-[1.5px] border-dashed border-[#4a4a2a] px-3 py-2.5 text-[11.5px] font-semibold text-[#d9e0a3] hover:border-[#D7FF4A] hover:text-[#E8FF8A]">
                        + Agregar alumno sin reserva
                    </button>
                </div>
            )}



            {/* ── 3. WOD del día: estado + publicar (mismo modal del panel) ── */}
            <div className={TARJETA} data-testid="wod-del-dia">
                <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                        <p className={ROTULO}>WOD del día</p>
                        <p className={`mt-1 truncate text-[15px] font-bold ${wodPublicado ? 'text-zinc-100' : 'text-amber-300'}`}>
                            {wodPublicado ? (wodHoy.titulo || 'Publicado') : 'Sin publicar'}
                        </p>
                    </div>
                    <span className={`flex-none rounded-[8px] px-2.5 py-1 text-[10.5px] font-black uppercase tracking-wide ${wodPublicado ? 'bg-emerald-950/60 text-emerald-300' : 'bg-amber-950/60 text-amber-200'}`}>
                        {wodPublicado ? 'Publicado' : 'Sin publicar'}
                    </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" onClick={onPublicarWod} data-testid="abrir-publicar-wod"
                        className={BOTON_LIMA}>
                        + Publicar WOD
                    </button>
                    {wodHoy && (
                        <button type="button"
                            onClick={() => onAbrirDetalleWod && onAbrirDetalleWod(proximaClase, wodHoy)}
                            className="rounded-[14px] border border-[#2A2A2E] px-4 py-2.5 text-[12.5px] font-bold text-zinc-300 hover:border-zinc-600 hover:text-zinc-100">
                            Ver el WOD completo
                        </button>
                    )}
                </div>
                <p className="mt-2 text-[11px] text-zinc-500">
                    Se publica desde el mismo modal del panel (o con el Excel de la semana, en la
                    pestaña Clases).
                </p>
            </div>

            {/* ── 5. Avisos para alumnos (Bloque 10) ──
                El coach sólo puede publicar AVISOS DEL DÍA: el resto de los tipos los elige el
                admin en Marketing. Se listan los vigentes hoy —los mismos que ve el carrusel
                del Inicio del alumno— leídos del endpoint abierto a cualquier sesión. */}
            <div className={TARJETA} data-testid="resumen-avisos">
                <div className="flex items-center justify-between gap-3">
                    <p className={ROTULO}>Avisos para alumnos</p>
                    <button type="button" onClick={onNuevoAviso} data-testid="resumen-nuevo-aviso"
                        className="flex-none rounded-[12px] border border-[#4a4a2a] px-3 py-1.5 text-[11.5px] font-bold text-[#d9e0a3] hover:border-[#D7FF4A] hover:text-[#E8FF8A]">
                        + Nuevo aviso
                    </button>
                </div>

                {avisos.length === 0 ? (
                    <p className="mt-2 text-[12px] text-zinc-500" data-testid="resumen-sin-avisos">
                        No hay avisos vigentes hoy. El que publiques aparece en el Inicio de los
                        alumnos y desaparece solo a medianoche.
                    </p>
                ) : (
                    <ul className="mt-3 space-y-2" data-testid="resumen-lista-avisos">
                        {avisos.slice(0, 4).map((aviso) => (
                            <li key={aviso.id}
                                className="rounded-[12px] border border-[#2A2A2E] bg-zinc-900 px-3 py-2">
                                <div className="flex items-center gap-2">
                                    <span className="flex-none rounded bg-[#2A2A2E] px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wide text-zinc-300">
                                        {etiquetaTipo(aviso.tipo)}
                                    </span>
                                    <span className="min-w-0 flex-1 truncate text-[12.5px] font-bold text-zinc-100">
                                        {aviso.titulo || 'Aviso del box'}
                                    </span>
                                </div>
                                <p className="mt-1 text-[11.5px] text-zinc-400">{aviso.texto}</p>
                            </li>
                        ))}
                    </ul>
                )}
                <p className="mt-2 text-[10.5px] text-zinc-600">
                    Promociones, colaboraciones y eventos los publica el admin desde Marketing.
                    {avisos.length > 4 && ` Se muestran 4 de ${avisos.length}.`}
                </p>
            </div>

            {/* ── 6. El resto de las clases de hoy (fila horizontal) ── */}
            {restoDelDia.length > 0 && (
                <div>
                    <p className={`mb-2 ${ROTULO}`}>Resto de hoy</p>
                    <div className="flex gap-3 overflow-x-auto pb-2" data-testid="resumen-clases-hoy-scroll">
                        {restoDelDia.map((clase) => {
                            const estado = estadoFila(clase);
                            const esperados = reservasDe(clase);
                            return (
                                <button key={clase.id} type="button"
                                    onClick={() => onAbrirClase && onAbrirClase(clase)}
                                    data-testid={`clase-hoy-${clase.id}`}
                                    className={`flex w-[164px] flex-none flex-col items-center gap-2 rounded-[18px] border-2 bg-[#18181B] px-4 py-4 text-center transition-colors ${estado === 'en-curso' ? 'border-[#D7FF4A]' : 'border-transparent hover:border-[#2A2A2E]'}`}>
                                    <Donut mini tamano={76} grosor={10}
                                        marcados={esperados} cupo={Number(clase.cupo_maximo) || 0} />
                                    <span className="text-[15px] font-extrabold text-zinc-100">
                                        {horaCorta(clase.hora_inicio)}
                                    </span>
                                    <span className="text-[11.5px] font-semibold text-zinc-400">
                                        {clase.disciplina_nombre || 'Clase'}
                                    </span>
                                    <span className={`rounded-[8px] px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wide ${BADGE_ESTADO[estado]}`}>
                                        {etiquetaEstado(estado)}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* ── 7. Ocupación por horario: una barra por clase del día ── */}
            {clasesHoy.length > 0 && (
                <div>
                    <p className={`mb-2 ${ROTULO}`}>Ocupación por horario — hoy</p>
                    <div className="space-y-3.5 rounded-[20px] bg-[#18181B] p-5" data-testid="resumen-ocupacion">
                        {clasesHoy.map((clase) => {
                            const { pct } = ocupacion(reservasDe(clase), clase.cupo_maximo);
                            return (
                                <div key={clase.id} className="flex items-center gap-3">
                                    <span className="w-[132px] flex-none text-[12px] font-bold text-zinc-400">
                                        {horaCorta(clase.hora_inicio)} {clase.disciplina_nombre || ''}
                                    </span>
                                    <span className="h-[18px] flex-1 overflow-hidden rounded-[9px] bg-[#242428]">
                                        <span className="block h-full rounded-[9px] bg-[linear-gradient(90deg,#D7FF4A,#8CFF6E)]"
                                            style={{ width: `${pct}%` }} />
                                    </span>
                                    <span className="w-[44px] flex-none text-right text-[12px] font-bold text-zinc-400">
                                        {pct}%
                                    </span>
                                </div>
                            );
                        })}
                        <p className="pt-1 text-[11.5px] text-zinc-600">
                            Se va llenando a medida que se marca asistencia en cada clase.
                        </p>
                    </div>
                </div>
            )}

            {/* ── Sin clases: el 0 se explica (falta de asignación vs. día vacío) ── */}
            {clasesHoy.length === 0 && (
                <p className="rounded-[18px] border border-[#2A2A2E] bg-[#18181B] px-4 py-5 text-center text-[12.5px] text-zinc-400"
                    data-testid="resumen-sin-clases">
                    {sinAsignaciones
                        ? 'Todavía no tienes clases asignadas: pídele al admin que te asigne tus disciplinas u horarios.'
                        : 'No tienes clases programadas para hoy. Si esperabas tener, revisa con el admin que tus disciplinas y horarios estén cargados.'}
                </p>
            )}
        </div>
    );
};

export default ResumenCoach;

