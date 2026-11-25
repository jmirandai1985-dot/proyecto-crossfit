/**
 * Paneles de las tarjetas de NEGOCIO del Dashboard admin.
 *
 * Cada tarjeta abre su panel DEBAJO de la fila de KPIs (no navega a Reportes ni
 * a otra pantalla). Los datos llegan ya calculados por el backend:
 *
 *  - Ingreso del mes  → `GET /admin/ingreso-mes` (pagos aprobados por día).
 *  - Membresías mes   → `GET /admin/membresias-mes` (ranking de planes pagados).
 *  - MRR              → `GET /admin/mrr` (membresías vigentes con créditos, por plan).
 *  - Ocupación        → `GET /admin/ocupacion-mes` (una fila por clase, misma
 *                       fórmula que la tarjeta: asistencias reales / cupo).
 *
 * Estilo: el mismo `section` con borde y "Cerrar" que los paneles de "Clases de
 * hoy" y "Pagos del día" del Dashboard. Los componentes son de presentación:
 * no piden datos ni deciden reglas de negocio.
 */
import React from 'react';
import { useOcupacionMes } from '../../hooks/queries';
import { mensajeError } from '../../services/queryClient';
import { fmtFechaChile, fmtFechaCortaChile } from '../../utils/fecha';

const TZ_CHILE = 'America/Santiago';

/** "$40.000" (o "—" si no hay número: nunca "$NaN"). */
export const clp = (valor) => {
    const n = Number(valor);
    if (!Number.isFinite(n)) return '—';
    return `$${n.toLocaleString('es-CL')}`;
};

/** "01 oct" del día chileno de una fecha 'YYYY-MM-DD'. */
const diaCorto = (fecha) => {
    const fmt = new Intl.DateTimeFormat('es-CL', {
        timeZone: TZ_CHILE, weekday: 'short', day: '2-digit', month: 'short',
    }).format(new Date(`${String(fecha).slice(0, 10)}T12:00:00Z`));
    return fmt.replace(/\./g, '').replace(',', '');
};

/** Envoltorio común: título, subtítulo y botón Cerrar (mismo look del panel). */
export function PanelDetalle({ id, titulo, subtitulo, onCerrar, children }) {
    return (
        <section aria-labelledby={id}
            className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h2 id={id} className="text-lg font-bold text-zinc-100">{titulo}</h2>
                    <p className="text-xs text-zinc-500">{subtitulo}</p>
                </div>
                <button type="button" onClick={onCerrar}
                    className="shrink-0 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-semibold transition-colors"
                    aria-label={`Cerrar ${titulo}`}>
                    Cerrar
                </button>
            </div>
            {children}
        </section>
    );
}

const EstadoCarga = ({ cargando, error, children }) => {
    if (cargando) return <p className="text-sm text-zinc-500">Cargando…</p>;
    if (error) {
        return (
            <p className="text-sm font-semibold text-amber-400" role="alert" title={error}>
                ⚠️ No se pudo cargar: {error}
            </p>
        );
    }
    return children;
};

const KpiResumen = ({ label, valor, detalle }) => (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2">
        <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
        <p className="text-lg font-bold text-zinc-100">{valor}</p>
        {detalle && <p className="text-[11px] text-zinc-500">{detalle}</p>}
    </div>
);

/** Enlace secundario "Ver todo" del pie de un panel (mantiene la pantalla completa). */
const VerTodo = ({ onClick, texto = 'Ver todo' }) => (
    <button type="button" onClick={onClick}
        className="w-full rounded-lg border border-zinc-700 bg-zinc-800/60 px-3 py-2 text-xs font-semibold text-zinc-200 hover:bg-zinc-700 transition-colors">
        {texto} →
    </button>
);

// ── Ingreso del mes ─────────────────────────────────────────────────────────
export function PanelIngresoMes({ resumen, cargando, error, onCerrar }) {
    const dias = Array.isArray(resumen?.dias) ? resumen.dias : [];
    return (
        <PanelDetalle
            id="dashboard-ingreso-mes"
            titulo="Ingreso del mes · cobros aprobados"
            subtitulo="Todos los planes y las ventas de Bazar, por día (America/Santiago). Fuente: pagos aprobados."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <KpiResumen label="Total del mes" valor={clp(resumen?.total_clp)}
                        detalle={`${resumen?.cantidad ?? 0} cobros aprobados`} />
                    <KpiResumen label="Membresías" valor={clp(resumen?.total_membresia_clp)} />
                    <KpiResumen label="Bazar" valor={clp(resumen?.total_bazar_clp)} />
                </div>
                {dias.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        No hay días para mostrar en este mes.
                    </p>
                ) : (
                    <div className="max-h-80 overflow-auto rounded-lg border border-zinc-800">
                        <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-zinc-900">
                                <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                                    <th className="px-3 py-2">Día</th>
                                    <th className="px-3 py-2 text-right">Cobros</th>
                                    <th className="px-3 py-2 text-right">Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                {dias.map((dia) => (
                                    <tr key={dia.fecha}
                                        className="border-t border-zinc-800/70">
                                        <td className="px-3 py-2 text-zinc-300">
                                            {diaCorto(dia.fecha)}
                                        </td>
                                        <td className="px-3 py-2 text-right text-zinc-400">
                                            {dia.cantidad}
                                        </td>
                                        <td className={`px-3 py-2 text-right font-semibold ${dia.total_clp > 0 ? 'text-zinc-100' : 'text-zinc-600'}`}>
                                            {clp(dia.total_clp)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
                {Number(resumen?.cantidad || 0) === 0 && (
                    <p className="text-sm text-zinc-500">
                        Sin cobros aprobados este mes: no hay pagos aprobados en la
                        tabla pagos (las ventas del Bazar también se cuentan desde ahí).
                    </p>
                )}
            </EstadoCarga>
        </PanelDetalle>
    );
}


// ── Membresías del mes (ranking de planes pagados) ──────────────────────────
export function PanelMembresiasMes({ ranking, cargando, error, onCerrar }) {
    const planes = Array.isArray(ranking?.planes) ? ranking.planes : [];
    return (
        <PanelDetalle
            id="dashboard-membresias-mes"
            titulo="Membresías del mes · planes vendidos"
            subtitulo="Ranking de planes de membresía con precio mayor a $0 vendidos este mes. Los planes de prueba (gratis o de precio simbólico) no son membresías."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <KpiResumen label="Planes pagados vendidos"
                    valor={ranking?.total_altas ?? 0}
                    detalle="Excluye el plan de prueba gratis" />
                {planes.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        Sin membresías pagadas este mes. Los planes de prueba (gratis o
                        de precio simbólico) no cuentan como membresía y no entran al ranking.
                    </p>
                ) : (
                    <div className="rounded-lg border border-zinc-800 overflow-hidden">
                        <table className="w-full text-sm">
                            <thead className="bg-zinc-900">
                                <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                                    <th className="px-3 py-2">Plan</th>
                                    <th className="px-3 py-2 text-right">Altas</th>
                                    <th className="px-3 py-2 text-right">% del mes</th>
                                    <th className="px-3 py-2 text-right">Cobrado</th>
                                </tr>
                            </thead>
                            <tbody>
                                {planes.map((plan) => (
                                    <tr key={plan.plan_id}
                                        className="border-t border-zinc-800/70">
                                        <td className="px-3 py-2 text-zinc-200">{plan.plan_nombre}</td>
                                        <td className="px-3 py-2 text-right text-zinc-300">{plan.altas}</td>
                                        <td className="px-3 py-2 text-right text-zinc-400">{plan.porcentaje}%</td>
                                        <td className="px-3 py-2 text-right font-semibold text-zinc-100">
                                            {clp(plan.total_clp)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </EstadoCarga>
        </PanelDetalle>
    );
}


// ── MRR actual (corte de hoy) ──────────────────────────────────────────────
export function PanelMrr({ mrr, cargando, error, onCerrar }) {
    const planes = Array.isArray(mrr?.planes) ? mrr.planes : [];
    // Compatibilidad: si el backend aún no manda `actual`, se usa el nivel raíz.
    const actual = mrr?.actual || {
        total_clp: mrr?.total_clp,
        alumnos: mrr?.alumnos,
        fecha_corte: mrr?.fecha,
    };

    return (
        <PanelDetalle
            id="dashboard-mrr"
            titulo="MRR · corte de hoy"
            subtitulo="Membresías de pago con fecha vigente hoy y créditos disponibles. Un plan por alumno, sin planes de prueba y sin prorrateo."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <KpiResumen label="MRR actual (hasta hoy)"
                        valor={clp(actual?.total_clp)}
                        detalle={`Corte: ${actual?.fecha_corte ? fmtFechaChile(actual.fecha_corte) : '—'} · ${actual?.alumnos ?? 0} alumnos`} />
                    <KpiResumen label="Fecha de corte"
                        valor={actual?.fecha_corte ? fmtFechaChile(actual.fecha_corte) : '—'}
                        detalle={`${actual?.alumnos ?? 0} alumnos con plan vigente`} />
                </div>
                {planes.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        No hay membresías de pago vigentes con créditos disponibles hoy.
                        Los planes de prueba (gratis o de precio simbólico) no cuentan
                        para el MRR.
                    </p>
                ) : (
                    <div className="space-y-2">
                        <p className="text-[11px] uppercase tracking-wide text-zinc-500">
                            Detalle por plan · corte de hoy
                        </p>
                        <div className="rounded-lg border border-zinc-800 overflow-hidden">
                            <table className="w-full text-sm">
                                <thead className="bg-zinc-900">
                                    <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                                        <th className="px-3 py-2">Plan</th>
                                        <th className="px-3 py-2 text-right">Alumnos</th>
                                        <th className="px-3 py-2 text-right">Precio plan</th>
                                        <th className="px-3 py-2 text-right">Total</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {planes.map((plan) => (
                                        <tr key={plan.plan_id}
                                            className="border-t border-zinc-800/70">
                                            <td className="px-3 py-2 text-zinc-200">{plan.plan_nombre}</td>
                                            <td className="px-3 py-2 text-right text-zinc-300">{plan.alumnos}</td>
                                            <td className="px-3 py-2 text-right text-zinc-400">{clp(plan.precio_clp)}</td>
                                            <td className="px-3 py-2 text-right font-semibold text-zinc-100">
                                                {clp(plan.total_clp)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </EstadoCarga>
        </PanelDetalle>
    );
}


// ── Ocupación del mes por clase ────────────────────────────────────────────
/**
 * `data` = respuesta de `GET /admin/ocupacion-mes`: total + una fila por clase
 * realizada CON cupo. El backend usa la MISMA fórmula de la tarjeta
 * (`metricas_service.ocupacion_promedio`): asistencias reales (sin cuentas
 * `es_prueba`) / cupo. Las clases sin tope se informan aparte.
 */
export function PanelOcupacionMes({ data, cargando, error, onCerrar }) {
    const clases = Array.isArray(data?.clases) ? data.clases : [];
    const totalPct = data?.total_pct ?? null;
    const asistentes = data?.asistentes ?? 0;
    const cupo = data?.cupo ?? 0;
    const sinTope = data?.clases_sin_cupo ?? 0;

    return (
        <PanelDetalle
            id="dashboard-ocupacion-mes"
            titulo="Ocupación del mes · por clase"
            subtitulo="Asistencias reales (marcadas, sin cuentas de prueba) sobre el cupo de cada clase realizada. Es la MISMA fórmula de la tarjeta. Las clases sin tope no tienen porcentaje."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <KpiResumen label="Ocupación del mes"
                        valor={totalPct === null ? 'n/d' : `${totalPct}%`}
                        detalle={`${asistentes} asistencias / ${cupo} cupos`} />
                    <KpiResumen label="Clases con cupo" valor={clases.length}
                        detalle="Realizadas este mes" />
                    <KpiResumen label="Clases sin tope" valor={sinTope}
                        detalle="Musculación / Open Box" />
                </div>
                {clases.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        Todavía no hay clases realizadas con cupo este mes: sin
                        denominador no se publica un porcentaje.
                    </p>
                ) : (
                    <div className="max-h-80 overflow-auto rounded-lg border border-zinc-800">
                        <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-zinc-900">
                                <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                                    <th className="px-3 py-2">Clase</th>
                                    <th className="px-3 py-2 text-right">Asistencia</th>
                                    <th className="px-3 py-2 text-right">Cupo</th>
                                    <th className="px-3 py-2 text-right">Ocupación</th>
                                </tr>
                            </thead>
                            <tbody>
                                {clases.map((clase) => (
                                    <tr key={clase.id} className="border-t border-zinc-800/70">
                                        <td className="px-3 py-2 text-zinc-200">
                                            <span className="text-zinc-400">
                                                {fmtFechaCortaChile(clase.fecha)} · {clase.hora_inicio}
                                            </span>
                                            <br />
                                            {clase.disciplina}
                                            {clase.coach ? ` · ${clase.coach}` : ''}
                                        </td>
                                        <td className="px-3 py-2 text-right text-zinc-300">
                                            {clase.asistentes}
                                        </td>
                                        <td className="px-3 py-2 text-right text-zinc-400">
                                            {clase.cupo}
                                        </td>
                                        <td className={`px-3 py-2 text-right font-semibold ${clase.pct >= 80 ? 'text-emerald-300' : clase.pct >= 50 ? 'text-amber-300' : 'text-zinc-300'}`}>
                                            {clase.pct == null ? 'n/d' : `${clase.pct}%`}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
                {sinTope > 0 && (
                    <p className="text-[11px] text-zinc-500">
                        {sinTope} clases realizadas sin cupo (Musculación / Open Box):
                        se cuentan aparte y no entran en el porcentaje.
                    </p>
                )}
            </EstadoCarga>
        </PanelDetalle>
    );
}


/**
 * Panel de Ocupación CON su propia consulta. Se monta SÓLO al abrir el panel:
 * así el Dashboard no arrastra el mes completo de asistencia en cada carga.
 * Lo comparten la vista de escritorio y la móvil.
 */
export function PanelOcupacionConDatos({ anio, mes, onCerrar }) {
    const ocupacionQ = useOcupacionMes(anio, mes);
    const error = ocupacionQ.error
        ? mensajeError(ocupacionQ.error, 'No se pudo cargar la ocupación del mes')
        : '';
    return (
        <PanelOcupacionMes
            data={ocupacionQ.data}
            cargando={ocupacionQ.isPending}
            error={error}
            onCerrar={onCerrar}
        />
    );
}



// ── Asistencia de hoy (lista resumida) ──────────────────────────────────────
const horaDe = (clase) => String(clase?.hora_inicio || '').slice(0, 5);
const asistentesDe = (clase) => Number(clase?.asistentes_confirmados) || 0;
const reservasDeClase = (clase) => Number(clase?.reservas_count) || 0;
const sinCupoClase = (clase) => clase?.cupo_maximo === null
    || clase?.cupo_maximo === undefined;

export function PanelAsistenciaHoy({ clases, cargando, error, onCerrar, onVerTodo }) {
    const todas = Array.isArray(clases) ? clases : [];
    // Las últimas 10 por hora (lo más reciente primero); el total de la
    // tarjeta se calcula sobre TODAS las clases, no sobre el recorte.
    const lista = [...todas]
        .sort((a, b) => horaDe(b).localeCompare(horaDe(a)))
        .slice(0, 10);
    const total = todas.reduce((suma, clase) => suma + asistentesDe(clase), 0);

    return (
        <PanelDetalle
            id="dashboard-asistencia-hoy"
            titulo="Asistencia de hoy"
            subtitulo="Asistencias registradas en las clases del día (asistentes confirmados). Misma suma que la tarjeta."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <KpiResumen label="Asistencias de hoy" valor={total}
                    detalle={`${todas.length} clases hoy`} />
                {lista.length === 0 ? (
                    <p className="text-sm text-zinc-500">No hay clases registradas hoy.</p>
                ) : (
                    <div className="max-h-72 overflow-auto rounded-lg border border-zinc-800">
                        <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-zinc-900">
                                <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                                    <th className="px-3 py-2">Hora</th>
                                    <th className="px-3 py-2">Clase</th>
                                    <th className="px-3 py-2 text-right">Asist.</th>
                                    <th className="px-3 py-2 text-right">Reservas / cupo</th>
                                </tr>
                            </thead>
                            <tbody>
                                {lista.map((clase) => (
                                    <tr key={clase.id} className="border-t border-zinc-800/70">
                                        <td className="px-3 py-2 text-zinc-400 tabular-nums">
                                            {horaDe(clase) || '--:--'}
                                        </td>
                                        <td className="px-3 py-2 text-zinc-200">
                                            {clase.disciplina_nombre || 'Clase'}
                                        </td>
                                        <td className="px-3 py-2 text-right font-semibold text-zinc-100">
                                            {asistentesDe(clase)}
                                        </td>
                                        <td className="px-3 py-2 text-right text-zinc-400">
                                            {sinCupoClase(clase)
                                                ? `${reservasDeClase(clase)} · sin cupo`
                                                : `${reservasDeClase(clase)} / ${clase.cupo_maximo}`}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
                <VerTodo onClick={onVerTodo} texto="Ver la asistencia completa" />
            </EstadoCarga>
        </PanelDetalle>
    );
}



// ── Alumnos activos (lista resumida) ────────────────────────────────────────
export function PanelAlumnosActivos({ resumen, cargando, error, onCerrar, onVerTodo }) {
    const alumnos = Array.isArray(resumen?.alumnos) ? resumen.alumnos : [];
    return (
        <PanelDetalle
            id="dashboard-alumnos-activos"
            titulo="Alumnos activos"
            subtitulo="Alumnos con una suscripción vigente hoy (día de Chile). El total es la base de la tarjeta y del riesgo."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <KpiResumen label="Alumnos activos" valor={resumen?.total ?? 0}
                    detalle="Suscripción vigente hoy" />
                {alumnos.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        No hay alumnos con una suscripción vigente hoy.
                    </p>
                ) : (
                    <ul className="max-h-72 space-y-1 overflow-auto">
                        {alumnos.map((alumno) => (
                            <li key={alumno.id}
                                className="flex items-center justify-between gap-2 rounded border border-zinc-800 px-3 py-2 text-sm">
                                <div className="min-w-0">
                                    <p className="truncate text-zinc-200">{alumno.nombre}</p>
                                    <p className="truncate text-[11px] text-zinc-500">
                                        {alumno.plan_nombre || 'Sin plan'}
                                        {alumno.correo ? ` · ${alumno.correo}` : ''}
                                    </p>
                                </div>
                                <span className="shrink-0 text-[11px] text-zinc-400">
                                    {alumno.fecha_expiracion
                                        ? `vence ${fmtFechaCortaChile(alumno.fecha_expiracion)}`
                                        : 'sin vencimiento'}
                                </span>
                            </li>
                        ))}
                    </ul>
                )}
                <VerTodo onClick={onVerTodo} texto="Ver el padrón activo" />
            </EstadoCarga>
        </PanelDetalle>
    );
}



// ── Ventas Bazar (lista resumida) ───────────────────────────────────────────
export function PanelVentasBazar({ pagos, cargando, error, onCerrar, onVerTodo }) {
    const todos = Array.isArray(pagos) ? pagos.filter((p) => p?.origen === 'bazar') : [];
    const lista = [...todos]
        .sort((a, b) => String(b.fecha || '').localeCompare(String(a.fecha || '')))
        .slice(0, 10);
    const total = todos.reduce((suma, pago) => suma + Number(pago.monto_clp || 0), 0);

    return (
        <PanelDetalle
            id="dashboard-ventas-bazar"
            titulo="Ventas Bazar"
            subtitulo="Cobros aprobados del Bazar en el mes (tabla pagos). La lista muestra los últimos 10."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <KpiResumen label="Ventas del mes" valor={clp(total)}
                    detalle={`${todos.length} pedidos cobrados`} />
                {lista.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        Sin ventas del Bazar cobradas por Mercado Pago este mes.
                    </p>
                ) : (
                    <div className="max-h-72 overflow-auto rounded-lg border border-zinc-800">
                        <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-zinc-900">
                                <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                                    <th className="px-3 py-2">Fecha</th>
                                    <th className="px-3 py-2">Alumno</th>
                                    <th className="px-3 py-2">Producto</th>
                                    <th className="px-3 py-2 text-right">Monto</th>
                                </tr>
                            </thead>
                            <tbody>
                                {lista.map((pago) => (
                                    <tr key={pago.pago_id} className="border-t border-zinc-800/70">
                                        <td className="px-3 py-2 text-zinc-400">
                                            {fmtFechaCortaChile(pago.fecha)}
                                            {pago.hora ? ` · ${pago.hora}` : ''}
                                        </td>
                                        <td className="px-3 py-2 text-zinc-200">
                                            {pago.nombre || 'Alumno'}
                                        </td>
                                        <td className="px-3 py-2 text-zinc-300">
                                            {pago.producto || pago.origen_detalle || 'Producto'}
                                        </td>
                                        <td className="px-3 py-2 text-right font-semibold text-zinc-100">
                                            {clp(pago.monto_clp)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
                <VerTodo onClick={onVerTodo} texto="Ver todos los pedidos" />
            </EstadoCarga>
        </PanelDetalle>
    );
}

