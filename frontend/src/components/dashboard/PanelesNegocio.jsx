/**
 * Paneles de las tarjetas de NEGOCIO del Dashboard admin.
 *
 * Cada tarjeta abre su panel DEBAJO de la fila de KPIs (no navega a Reportes ni
 * a otra pantalla). Los datos llegan ya calculados por el backend:
 *
 *  - Ingreso del mes  → `GET /admin/ingreso-mes` (pagos aprobados por día).
 *  - Membresías mes   → `GET /admin/membresias-mes` (ranking de planes pagados).
 *  - MRR              → `GET /admin/mrr` (membresías activas por plan).
 *  - Ocupación        → `GET /asistencia/historial` (una fila por clase).
 *
 * Estilo: el mismo `section` con borde y "Cerrar" que los paneles de "Clases de
 * hoy" y "Pagos del día" del Dashboard. Los componentes son de presentación:
 * no piden datos ni deciden reglas de negocio.
 */
import React from 'react';
import { useHistorialAsistencia } from '../../hooks/queries';
import { mensajeError } from '../../services/queryClient';
import { fmtFechaCortaChile } from '../../utils/fecha';

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
            className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
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
            subtitulo="Ranking de planes con precio mayor a $0 vendidos este mes. El plan de prueba gratis no es una venta."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <KpiResumen label="Planes pagados vendidos"
                    valor={ranking?.total_altas ?? 0}
                    detalle="Excluye el plan de prueba gratis" />
                {planes.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        Sin membresías pagadas este mes. En este box el plan de prueba
                        es gratuito, así que sus alumnos no entran en el ranking.
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


// ── MRR del día ────────────────────────────────────────────────────────────
export function PanelMrr({ mrr, cargando, error, onCerrar }) {
    const planes = Array.isArray(mrr?.planes) ? mrr.planes : [];
    return (
        <PanelDetalle
            id="dashboard-mrr"
            titulo="MRR · membresías activas hoy"
            subtitulo="Planes pagados con membresía activa, vigente y con créditos. Un plan por alumno (el que vence más tarde). Precio de LISTA del plan (no se prorratean los planes de larga duración)."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <KpiResumen label="MRR" valor={clp(mrr?.total_clp)}
                        detalle={`${mrr?.alumnos ?? 0} alumnos con plan pagado`} />
                    <KpiResumen label="Fecha de corte" valor={mrr?.fecha || '—'}
                        detalle="Día de Chile" />
                </div>
                {planes.length === 0 ? (
                    <p className="text-sm text-zinc-500">
                        No hay membresías activas pagadas hoy. El plan de prueba gratis
                        (precio $0) no cuenta para el MRR.
                    </p>
                ) : (
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
                )}
            </EstadoCarga>
        </PanelDetalle>
    );
}


// ── Ocupación del mes por clase ────────────────────────────────────────────
/**
 * `historial` = respuesta de `GET /asistencia/historial` (clases del mes con
 * `marcados_count` y `cupo_maximo`). Ocupación de cada clase realizada CON tope:
 * asistentes reales (`marcados_count`) / cupo. Las clases sin tope (Musculación /
 * Open Box) no tienen denominador y se informan aparte.
 */
export function PanelOcupacionMes({ historial, cargando, error, onCerrar }) {
    const clases = Array.isArray(historial?.clases) ? historial.clases : [];
    const conCupo = clases.filter((c) => c.estado === 'realizada'
        && c.cupo_maximo !== null && c.cupo_maximo !== undefined);
    const sinTope = clases.filter((c) => c.estado === 'realizada'
        && (c.cupo_maximo === null || c.cupo_maximo === undefined));
    const asistentes = conCupo.reduce((a, c) => a + (c.marcados_count || 0), 0);
    const cupos = conCupo.reduce((a, c) => a + (c.cupo_maximo || 0), 0);
    const totalPct = cupos > 0 ? Math.round((asistentes / cupos) * 1000) / 10 : null;

    return (
        <PanelDetalle
            id="dashboard-ocupacion-mes"
            titulo="Ocupación del mes · por clase"
            subtitulo="Asistencia real (marcada) sobre el cupo de cada clase realizada. Las clases sin tope no tienen porcentaje."
            onCerrar={onCerrar}>
            <EstadoCarga cargando={cargando} error={error}>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <KpiResumen label="Ocupación del mes"
                        valor={totalPct === null ? 'n/d' : `${totalPct}%`}
                        detalle={`${asistentes} asistencias / ${cupos} cupos`} />
                    <KpiResumen label="Clases con cupo" valor={conCupo.length}
                        detalle="Realizadas este mes" />
                    <KpiResumen label="Clases sin tope" valor={sinTope.length}
                        detalle="Musculación / Open Box" />
                </div>
                {conCupo.length === 0 ? (
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
                                {conCupo.map((clase) => {
                                    const pct = Math.round(
                                        ((clase.marcados_count || 0) / clase.cupo_maximo) * 1000) / 10;
                                    return (
                                        <tr key={clase.id} className="border-t border-zinc-800/70">
                                            <td className="px-3 py-2 text-zinc-200">
                                                <span className="text-zinc-400">
                                                    {fmtFechaCortaChile(clase.fecha)} · {String(clase.hora_inicio).slice(0, 5)}
                                                </span>
                                                <br />
                                                {clase.disciplina_nombre}
                                                {clase.coach ? ` · ${clase.coach}` : ''}
                                            </td>
                                            <td className="px-3 py-2 text-right text-zinc-300">
                                                {clase.marcados_count || 0}
                                            </td>
                                            <td className="px-3 py-2 text-right text-zinc-400">
                                                {clase.cupo_maximo}
                                            </td>
                                            <td className={`px-3 py-2 text-right font-semibold ${pct >= 80 ? 'text-emerald-300' : pct >= 50 ? 'text-amber-300' : 'text-zinc-300'}`}>
                                                {pct}%
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
                {sinTope.length > 0 && (
                    <p className="text-[11px] text-zinc-500">
                        {sinTope.length} clases realizadas sin cupo (Musculación / Open Box):
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
    const historialQ = useHistorialAsistencia(anio, mes);
    const error = historialQ.error
        ? mensajeError(historialQ.error, 'No se pudo cargar la ocupación del mes')
        : '';
    return (
        <PanelOcupacionMes
            historial={historialQ.data}
            cargando={historialQ.isPending}
            error={error}
            onCerrar={onCerrar}
        />
    );
}

