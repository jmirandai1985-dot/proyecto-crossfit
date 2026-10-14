import React from 'react';

/**
 * Resumen del panel del coach (mockup `#pantalla-resumen`).
 *
 * MOBILE-FIRST: el mockup aprobado es el diseño final para TODOS los anchos, así que esto
 * no se reordena en escritorio: el contenido se limita a `max-w-2xl` y queda centrado — la
 * MISMA tarjeta del teléfono, sin inventar un layout de PC (si algún día se quiere uno, se
 * decide antes, no acá).
 *
 * LA REGLA DE NEGOCIO QUE ORDENA LA PANTALLA (y su copy): el alumno RESERVA y marca su
 * propia asistencia; el coach revisa y corrige a quien falte. El crédito se descuenta al
 * RESERVAR (`POST /reservas`), no cuando el coach marca: por eso la tarjeta de Asistencia
 * habla de "con reserva / ya marcaron / faltan" —nunca de cobros— y el único botón de
 * corrección es "Agregar alumno sin reserva", que dice ahí mismo si descuenta el crédito.
 *
 * Props (todo lo que necesita ya lo tiene el Dashboard: acá no se piden datos):
 *   clasesHoy         clases de hoy del coach (con `estado`, `marcada` y `reservas_count`
 *                     cuando el backend de Asistencia los trae),
 *   alumnosActivos    alumnos del coach · alumnosConRms los que tienen alguna marca,
 *   wodHoy            WOD de hoy (null = sin publicar),
 *   enRiesgo/umbralRiesgo  alumnos sin entrenar y el umbral en días,
 *   proximaClase      la clase EN CURSO o la próxima de hoy (null si ya no queda),
 *   reservasProxima   reservas de esa clase: `asistio` → los 3 números del mockup,
 *   onPublicarWod · onAgregarSinReserva(clase) · onAbrirAsistencia · onAbrirClase(clase)
 *   · onIrA(tab) · onAbrirDetalleWod(clase, wod).
 */
const ResumenCoach = ({
    clasesHoy = [], alumnosActivos = 0, alumnosConRms = 0, wodHoy = null,
    enRiesgo = 0, umbralRiesgo = 7, proximaClase = null, reservasProxima = [],
    cargandoReservas = false, onPublicarWod, onAgregarSinReserva, onAbrirAsistencia,
    onAbrirClase, onIrA, onAbrirDetalleWod,
}) => {
    const hora = (h) => (h ? String(h).slice(0, 5) : '');
    const asistentesHoy = clasesHoy.reduce(
        (total, c) => total + (c.asistentes_confirmados ?? 0), 0);

    // Los 3 números del mockup: los que reservaron, los que YA marcaron y los que faltan.
    const conReserva = proximaClase?.reservas_count ?? reservasProxima.length;
    const yaMarcaron = reservasProxima.filter((r) => r.asistio).length;
    const faltan = Math.max(conReserva - yaMarcaron, 0);

    const KPI = 'rounded-xl border border-zinc-800 bg-zinc-900 p-3 text-left transition-colors';
    const KPI_TOCABLE = `${KPI} hover:border-zinc-700 active:bg-zinc-800`;

    const estadoDe = (clase) => {
        if (clase?.marcada) {
            return { texto: 'Hecha', color: 'text-emerald-300 bg-emerald-900/30', barra: 'bg-emerald-500' };
        }
        if (clase?.estado === 'en_curso') {
            return { texto: 'En curso', color: 'text-red-200 bg-red-900/40', barra: 'bg-red-500' };
        }
        return { texto: 'Pendiente', color: 'text-amber-200 bg-amber-900/30', barra: 'bg-amber-500' };
    };

    return (
        <div className="mx-auto max-w-2xl space-y-3" data-testid="coach-resumen">
            <div className="grid grid-cols-2 gap-2.5">
                <button type="button" onClick={() => onIrA && onIrA('clases')}
                    data-testid="kpi-clases-hoy" className={KPI_TOCABLE}>
                    <p className="text-[10px] uppercase tracking-wide text-zinc-500">Clases hoy</p>
                    <p className="mt-1 text-2xl font-bold text-zinc-100">{clasesHoy.length}</p>
                    <p className="text-[10.5px] text-zinc-400">{asistentesHoy} asistentes</p>
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
                        <p className={`mt-1 text-[15px] font-bold ${wodHoy ? 'text-zinc-100' : 'text-amber-300'}`}>
                            {wodHoy ? (wodHoy.titulo || 'Publicado') : 'Sin publicar'}
                        </p>
                    </button>
                    <button type="button" onClick={onPublicarWod} data-testid="abrir-publicar-wod"
                        className="mx-3 mb-3 rounded-md border-[1.5px] border-amber-600 bg-amber-500 px-2 py-2 text-[10.5px] font-bold text-amber-950 hover:bg-amber-400">
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

            {/* ── Asistencia · próxima clase (la tarjeta ancha del mockup) ── */}
            <div className="rounded-xl border border-amber-900/60 bg-gradient-to-br from-zinc-900 to-zinc-950"
                data-testid="tarjeta-asistencia">
                {proximaClase ? (
                    <>
                        <button type="button" onClick={onAbrirAsistencia}
                            className="block w-full px-3 pb-2 pt-3 text-left">
                            <p className="text-[10px] uppercase tracking-wide text-zinc-500">
                                Asistencia · próxima clase, {hora(proximaClase.hora_inicio)}{' '}
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
                                {cargandoReservas
                                    ? 'Cargando la asistencia…'
                                    : 'Toca para ver quiénes faltan. El alumno marca al llegar; tú sólo corriges.'}
                            </p>
                        </button>
                        <button type="button"
                            onClick={() => onAgregarSinReserva && onAgregarSinReserva(proximaClase)}
                            data-testid="resumen-agregar-sin-reserva"
                            className="mx-3 mb-3 flex w-[calc(100%-1.5rem)] items-center justify-center gap-1.5 rounded-lg border-2 border-dashed border-amber-900/70 px-3 py-2.5 text-[11px] font-semibold text-amber-100 hover:border-amber-600">
                            + Agregar alumno sin reserva
                        </button>
                    </>
                ) : (
                    <p className="px-3 py-4 text-[12px] text-zinc-400">
                        No quedan clases por delante hoy.
                    </p>
                )}
            </div>

            {/* ── Mis clases de hoy (mismas filas del mockup) ── */}
            <div>
                <p className="mb-2 px-0.5 text-[11px] uppercase tracking-wide text-zinc-500">
                    Mis clases de hoy
                </p>
                {clasesHoy.length === 0 ? (
                    <p className="rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-4 text-center text-[12px] text-zinc-400">
                        No tienes clases programadas para hoy.
                    </p>
                ) : (
                    <div className="space-y-2">
                        {clasesHoy.map((clase) => {
                            const est = estadoDe(clase);
                            return (
                                <button key={clase.id} type="button"
                                    onClick={() => onAbrirClase && onAbrirClase(clase)}
                                    data-testid={`clase-hoy-${clase.id}`}
                                    className="flex w-full items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2.5 text-left hover:border-zinc-700">
                                    <span className={`h-8 w-1 flex-none rounded ${est.barra}`} />
                                    <span className="flex-1">
                                        <span className="block text-[13px] font-semibold text-zinc-100">
                                            {hora(clase.hora_inicio)} · {clase.disciplina_nombre}
                                        </span>
                                        <span className="block text-[10.5px] text-zinc-400">
                                            {clase.reservas_count ?? clase.asistentes_confirmados ?? 0} con reserva
                                            {' '}(cupo {clase.cupo_maximo ?? '—'})
                                        </span>
                                    </span>
                                    <span className={`flex-none rounded px-2 py-1 text-[9.5px] font-bold ${est.color}`}>
                                        {est.texto}
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

