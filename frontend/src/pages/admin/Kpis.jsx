import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    BarChart, Bar, AreaChart, Area, LineChart, Line,
    XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import {
    TrendingUp, Users, UserPlus, Activity, DollarSign, Percent,
    CalendarDays, TriangleAlert, Banknote, ShoppingCart, Gauge, Target,
    Sparkles,
} from 'lucide-react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { TabBar } from '../../components/kpis/TabBar';
import { KpiCard } from '../../components/kpis/KpiCard';
import { ChartCard } from '../../components/kpis/ChartCard';
import { DataTable } from '../../components/kpis/DataTable';
import { DetalleModal } from '../../components/kpis/DetalleModal';

const TABS = [
    { id: 'diario', label: 'Diario' },
    { id: 'mensual', label: 'Mensual' },
    { id: 'bi', label: 'Inteligencia de Negocio' },
];

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
    'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];


// ─── Helpers de fecha (hora local del navegador) ──────────────────────────
const toISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const fmtFechaCorta = (iso) => {
    const [, m, d] = String(iso).split('-');
    return `${Number(d)} ${MESES[Number(m) - 1]}`;
};

const fmtMesCorto = (iso) => {
    const [y, m] = String(iso).split('-');
    return `${MESES[Number(m) - 1]} ${String(y).slice(2)}`;
};

const fmtCLP = (n) => `$${Number(n || 0).toLocaleString('es-CL')}`;

// Celda de retención de una cohorte: "activos/evaluables (P%)" o "n/d" si el
// horizonte todavía no maduró (el backend manda `retencion_pct: null`).
const fmtCohorte = (h) => {
    if (!h || h.retencion_pct === null || h.retencion_pct === undefined) return 'n/d';
    return `${h.activos}/${h.evaluables} (${h.retencion_pct}%)`;
};

const TOOLTIP_STYLE = {
    contentStyle: { backgroundColor: '#18181b', border: '1px solid #3f3f46', borderRadius: '0.5rem' },
    labelStyle: { color: '#e4e4e7' },
};

/**
 * Página KPIs (admin) — 3 pestañas por query param `?tab=diario|mensual|bi`.
 * Consume los data marts vía /api/v1/kpis/* (poblados por los workflows n8n).
 */
const AdminKpis = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const { tenant_id } = useAuth();
    const activeTab = searchParams.get('tab') || 'diario';

    const [loading, setLoading] = useState(true);
    const [sinDatos, setSinDatos] = useState(false);
    const [error, setError] = useState(null);

    const [serieDiaria, setSerieDiaria] = useState([]);
    const [serieMensual, setSerieMensual] = useState([]);
    const [churn, setChurn] = useState(null);
    const [forecast, setForecast] = useState([]);
    const [mrrBi, setMrrBi] = useState(null);
    // Bloque financiero: ticket promedio + vida (GET /kpis/financiero) y ARPU
    // REUSADO de GET /reportes/ (misma fuente que muestra Reportes.jsx).
    const [financiero, setFinanciero] = useState(null);
    const [arpu, setArpu] = useState(null);
    // Bloques horarios (pico vs valle): oferta y asistencia por turno.
    const [bloques, setBloques] = useState(null);
    // Cohortes de retención por mes de alta.
    const [cohortes, setCohortes] = useState(null);
    // Bloque abierto en el modal de detalle ampliado (null = ninguno).
    const [detalle, setDetalle] = useState(null);

    // ─── BI: SOLO LECTURA ────────────────────────────────────────────────
    // La gestión individual de alumnos vive en /admin/fidelizacion: acá las
    // tarjetas y las alertas NAVEGAN a esa pantalla con un query param.

    // ─── DIARIO: últimos 7 días ──────────────────────────────────────────
    // El job n8n puebla el DÍA ANTERIOR (02:30), por eso la serie termina ayer.
    const cargarDiario = useCallback(async () => {
        setLoading(true); setError(null); setSinDatos(false);
        const fin = new Date();
        fin.setDate(fin.getDate() - 1);
        const fechas = [];
        for (let i = 6; i >= 0; i--) {
            const d = new Date(fin);
            d.setDate(d.getDate() - i);
            fechas.push(toISO(d));
        }
        try {
            const res = await Promise.allSettled(
                fechas.map((fecha) => api.get('/api/v1/kpis/diario', { params: { fecha } }))
            );
            const serie = res
                .map((r, i) => (r.status === 'fulfilled' ? { ...r.value.data, fecha: fechas[i] } : null))
                .filter(Boolean);
            setSerieDiaria(serie);
            setSinDatos(serie.length === 0);
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        }
        setLoading(false);
    }, []);

    // ─── MENSUAL: últimos 6 meses ────────────────────────────────────────
    const cargarMensual = useCallback(async () => {
        setLoading(true); setError(null); setSinDatos(false);
        const hoy = new Date();
        const periodos = [];
        for (let i = 5; i >= 0; i--) {
            const d = new Date(hoy.getFullYear(), hoy.getMonth() - i, 1);
            periodos.push({ year: d.getFullYear(), month: d.getMonth() + 1 });
        }
        try {
            const res = await Promise.allSettled(
                periodos.map((p) => api.get('/api/v1/kpis/mensual', { params: p }))
            );
            const serie = res
                .map((r, i) => (r.status === 'fulfilled' ? { ...r.value.data, ...periodos[i] } : null))
                .filter(Boolean);
            setSerieMensual(serie);
            setSinDatos(serie.length === 0);
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        }
        setLoading(false);
    }, []);

    // ─── BI: churn + forecast (+ MRR del mes) ────────────────────────────
    const cargarBi = useCallback(async () => {
        setLoading(true); setError(null); setSinDatos(false);
        const hoy = new Date();
        try {
            const [churnRes, forecastRes] = await Promise.all([
                api.get('/api/v1/kpis/churn'),
                api.get('/api/v1/kpis/forecast', { params: { meses: 3 } }),
            ]);
            setChurn(churnRes.data);
            setForecast(forecastRes.data?.proyecciones || []);

            // MRR: mes actual y, si no hay fila aún, el mes anterior.
            const mesActual = { year: hoy.getFullYear(), month: hoy.getMonth() + 1 };
            const rMes = await api.get('/api/v1/kpis/mensual', { params: mesActual }).catch(() => null);
            let mrr = rMes?.data?.mrr ?? null;
            if (mrr === null) {
                const prev = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
                const rPrev = await api
                    .get('/api/v1/kpis/mensual', { params: { year: prev.getFullYear(), month: prev.getMonth() + 1 } })
                    .catch(() => null);
                mrr = rPrev?.data?.mrr ?? null;
            }
            setMrrBi(mrr);

            // Bloque financiero (opcional, mismo criterio): el ticket y la vida
            // salen del endpoint nuevo; el ARPU se REUSA de /reportes/ (la misma
            // definición de Reportes.jsx: ingresos netos del mes / alumnos activos).
            const rFin = await api.get('/api/v1/kpis/financiero').catch(() => null);
            setFinanciero(rFin?.data || null);
            const rRep = tenant_id
                ? await api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`).catch(() => null)
                : null;
            setArpu(rRep?.data?.arpu ?? null);

            // Bloques horarios (pico vs valle): opcional, mismo criterio.
            const rBlo = await api.get('/api/v1/kpis/bloques-horarios')
                .catch(() => null);
            setBloques(rBlo?.data || null);

            // Cohortes de retención: opcional, mismo criterio.
            const rCoh = await api.get('/api/v1/kpis/cohortes')
                .catch(() => null);
            setCohortes(rCoh?.data || null);
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        if (activeTab === 'diario') cargarDiario();
        else if (activeTab === 'mensual') cargarMensual();
        else cargarBi();
    }, [activeTab, cargarDiario, cargarMensual, cargarBi]);

    const dia = serieDiaria.length ? serieDiaria[serieDiaria.length - 1] : null;
    const mes = serieMensual.length ? serieMensual[serieMensual.length - 1] : null;

    // LTV estimado = ARPU mensual × vida promedio del alumno en meses.
    // (La fórmula y sus límites los documenta el backend en `financiero`.)
    const ltvEstimado = (arpu != null && financiero?.vida?.vida_promedio_meses)
        ? Math.round(arpu * financiero.vida.vida_promedio_meses)
        : null;

    // Pico vs valle: ordenado por cantidad de clases (dato real de la oferta).
    const bloquesOrdenados = [...(bloques?.bloques || [])]
        .sort((a, b) => b.clases - a.clases);
    const bloquePico = bloquesOrdenados[0] || null;

    // Gráfico de bloques horarios y tabla de cohortes: mismo criterio que el
    // pronóstico (una sola definición, usada por la página y por el modal).
    const chartBloques = (
        <BarChart data={bloques?.bloques || []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
            <XAxis dataKey="bloque" stroke="#a1a1aa" fontSize={11} />
            <YAxis stroke="#a1a1aa" fontSize={12} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Bar dataKey="clases" name="Clases" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
            <Bar dataKey="asistencias_por_clase" name="Asistencias por clase" fill="#f97316" radius={[4, 4, 0, 0]} />
        </BarChart>
    );

    const tablaCohortes = cohortes?.cohortes?.length > 0 ? (
        <>
            <DataTable
                columns={[
                    { key: 'cohorte', label: 'Cohorte (alta)' },
                    { key: 'n_alumnos', label: 'Alumnos' },
                    { key: 'h30', label: 'Activos a 30 d\u00edas', render: (h) => fmtCohorte(h) },
                    { key: 'h60', label: 'Activos a 60 d\u00edas', render: (h) => fmtCohorte(h) },
                    { key: 'h90', label: 'Activos a 90 d\u00edas', render: (h) => fmtCohorte(h) },
                ]}
                data={cohortes.cohortes}
            />
            <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
                {cohortes.definicion}
                {' '}Global: a 30 d\u00edas {fmtCohorte(cohortes.global?.h30)},
                {' '}a 60 d\u00edas {fmtCohorte(cohortes.global?.h60)},
                {' '}a 90 d\u00edas {fmtCohorte(cohortes.global?.h90)}.
            </p>
        </>
    ) : null;

    // Gráfico y tabla del pronóstico: se definen una vez y los usan TANTO la
    // tarjeta de la página como el modal de detalle (evita duplicar el JSX).
    const chartForecast = (
        <LineChart data={forecast}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
            <XAxis dataKey="mes_prediccion" tickFormatter={fmtMesCorto} stroke="#a1a1aa" fontSize={12} />
            <YAxis stroke="#a1a1aa" fontSize={12} />
            <Tooltip {...TOOLTIP_STYLE} formatter={(v) => fmtCLP(v)} />
            <Line type="monotone" dataKey="ingresos_predicho" name="Ingresos proyectados" stroke="#f97316" strokeWidth={2} dot={{ r: 4 }} />
        </LineChart>
    );

    const tablaPronostico = (
        <div>
            <h3 className="text-lg font-semibold text-white mb-3">Detalle del pronóstico (mes a mes)</h3>
            <DataTable
                columns={[
                    { key: 'mes_prediccion', label: 'Mes', render: (v) => fmtMesCorto(v) },
                    { key: 'ingresos_predicho', label: 'Ingresos proyectados (CLP)', render: (v) => fmtCLP(v) },
                    {
                        key: 'variacion', label: 'Variación vs mes anterior',
                        render: (v) => (v === null
                            ? '\u2014'
                            : `${v > 0 ? '+' : ''}${v.toLocaleString('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`),
                    },
                    ...(forecast.some((f) => f.alumnos_predicho != null)
                        ? [{
                            key: 'alumnos_predicho', label: 'Alumnos proyectados',
                            render: (v) => (v ?? '\u2014'),
                        }]
                        : []),
                ]}
                data={forecastDetalle}
            />
        </div>
    );
    const bloqueValle = bloquesOrdenados.length > 1
        ? bloquesOrdenados[bloquesOrdenados.length - 1]
        : null;

    // Desglose mes a mes del pronóstico. La variación % vs mes anterior se
    // calcula acá (el backend expone `tasa_crecimiento`, que es otra métrica).
    const forecastDetalle = forecast.map((f, i) => {
        const previo = i > 0 ? Number(forecast[i - 1].ingresos_predicho) : null;
        const actual = Number(f.ingresos_predicho);
        return {
            ...f,
            variacion: previo ? ((actual - previo) / previo) * 100 : null,
        };
    });

    return (
        <Layout>
            <div className="max-w-7xl mx-auto">
                {/* ── Encabezado ── */}
                <div className="mb-6 flex items-center gap-3">
                    <TrendingUp className="w-8 h-8 text-orange-500" />
                    <div>
                        <h1 className="text-3xl font-bold text-white">KPIs</h1>
                        <p className="text-sm text-gray-400">
                            Indicadores actualizados automáticamente
                        </p>
                    </div>
                </div>

                <TabBar tabs={TABS} />

                {/* ── Estados ── */}
                {loading && (
                    <div className="flex items-center justify-center py-20">
                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
                    </div>
                )}

                {!loading && error && (
                    <div className="bg-red-900/30 border border-red-700 text-red-200 rounded-lg p-4">
                        Error al cargar los KPIs: {error}
                    </div>
                )}

                {!loading && !error && sinDatos && (
                    <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-8 text-center">
                        <p className="text-gray-300 font-medium">Sin datos para el período.</p>
                        <p className="text-sm text-gray-500 mt-2">
                            Los datos se están generando, intentá de nuevo en unos minutos
                        </p>
                    </div>
                )}

                {/* ══ TAB DIARIO ══ */}
                {!loading && !error && !sinDatos && activeTab === 'diario' && dia && (
                    <div className="space-y-6">
                        <p className="text-xs text-gray-500">
                            Último día con datos: <span className="text-gray-300">{fmtFechaCorta(dia.fecha)}</span>
                        </p>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            <KpiCard label="Alumnos activos" value={dia.alumnos_activos} icon={Users} color="border-blue-500" />
                            <KpiCard label="Alumnos nuevos" value={dia.alumnos_nuevos} icon={UserPlus} color="border-green-500" />
                            <KpiCard label="Asistentes del día" value={dia.asistentes_totales} icon={Activity} color="border-purple-500" />
                            <KpiCard label="Ingresos del día" value={Number(dia.ingresos_total)} unit="CLP" icon={DollarSign} color="border-emerald-500" />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            <KpiCard label="Clases ejecutadas" value={dia.clases_ejecutadas} icon={CalendarDays} color="border-cyan-500" />
                            <KpiCard label="Ocupación promedio" value={Number(dia.ocupacion_promedio)} unit="%" icon={Percent} color="border-amber-500" />
                            <KpiCard label="Reservas confirmadas" value={dia.reservas_confirmadas} icon={Gauge} color="border-sky-500" />
                            <KpiCard label="Cancelaciones" value={dia.cancellaciones} icon={TriangleAlert} color="border-red-500" />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <KpiCard label="Ingresos por membresía" value={Number(dia.ingresos_membresia)} unit="CLP" icon={Banknote} color="border-emerald-500" />
                            <KpiCard label="Ingresos por bazar" value={Number(dia.ingresos_bazar)} unit="CLP" icon={ShoppingCart} color="border-teal-500" />
                        </div>

                        <ChartCard title="Últimos 7 días · asistentes vs reservas confirmadas">
                            <BarChart data={serieDiaria}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                                <XAxis dataKey="fecha" tickFormatter={fmtFechaCorta} stroke="#a1a1aa" fontSize={12} />
                                <YAxis stroke="#a1a1aa" fontSize={12} />
                                <Tooltip {...TOOLTIP_STYLE} />
                                <Bar dataKey="asistentes_totales" name="Asistentes" fill="#a855f7" radius={[4, 4, 0, 0]} />
                                <Bar dataKey="reservas_confirmadas" name="Reservas confirmadas" fill="#06b6d4" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ChartCard>

                        <ChartCard title="Ingresos por día (CLP)">
                            <AreaChart data={serieDiaria}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                                <XAxis dataKey="fecha" tickFormatter={fmtFechaCorta} stroke="#a1a1aa" fontSize={12} />
                                <YAxis stroke="#a1a1aa" fontSize={12} />
                                <Tooltip {...TOOLTIP_STYLE} formatter={(v) => fmtCLP(v)} />
                                <Area type="monotone" dataKey="ingresos_total" name="Ingresos" stroke="#10b981" fill="#10b981" fillOpacity={0.25} />
                            </AreaChart>
                        </ChartCard>
                    </div>
                )}

                {/* ══ TAB MENSUAL ══ */}
                {!loading && !error && !sinDatos && activeTab === 'mensual' && mes && (
                    <div className="space-y-6">
                        <p className="text-xs text-gray-500">
                            Último mes con datos: <span className="text-gray-300">{MESES[mes.month - 1]} {mes.year}</span>
                        </p>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            <KpiCard label="Conversión prueba→plan" value={Number(mes.conversion_rate)} unit="%" icon={TrendingUp} color="border-green-500" />
                            <KpiCard label="Riesgo de Abandono"
                                        value={mes.churn_rate === null ? null : Number(mes.churn_rate)}
                                        unit="%" icon={TriangleAlert} color="border-red-500" />
                            <KpiCard label="Ingresos Recurrentes Mensuales (MRR)" value={Number(mes.mrr)} unit="CLP" icon={Banknote} color="border-emerald-500" />
                            <KpiCard label="Ingresos del mes" value={Number(mes.ingresos_total)} unit="CLP" icon={DollarSign} color="border-blue-500" />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            <KpiCard label="Asistencia promedio" value={Number(mes.asistencia_promedio)} unit="%" icon={Activity} color="border-purple-500" />
                            <KpiCard label="Frecuencia semanal" value={Number(mes.frecuencia_semanal)} unit="clases/sem" icon={Gauge} color="border-cyan-500" />
                            <KpiCard label="Ocupación promedio" value={Number(mes.ocupacion_promedio)} unit="%" icon={Target} color="border-amber-500" />
                            <KpiCard label="Alumnos activos (inicio)" value={mes.alumnos_activos_inicio} icon={Users} color="border-sky-500" />
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                            <div className="lg:col-span-2">
                                <ChartCard title="Últimos 6 meses · Ingresos recurrentes e ingresos totales (CLP)">
                                    <AreaChart data={serieMensual}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                                        <XAxis dataKey="month" tickFormatter={(mm) => MESES[Number(mm) - 1]} stroke="#a1a1aa" fontSize={12} />
                                        <YAxis stroke="#a1a1aa" fontSize={12} />
                                        <Tooltip {...TOOLTIP_STYLE} formatter={(v) => fmtCLP(v)} />
                                        <Area type="monotone" dataKey="mrr" name="Ingresos recurrentes" stroke="#f97316" fill="#f97316" fillOpacity={0.25} />
                                        <Area type="monotone" dataKey="ingresos_total" name="Ingresos" stroke="#10b981" fill="#10b981" fillOpacity={0.2} />
                                    </AreaChart>
                                </ChartCard>
                            </div>

                            {/* Embudo prueba → plan (card simple, no es gráfico recharts) */}
                            <div className="bg-zinc-900 rounded-lg shadow p-6">
                                <h3 className="text-lg font-semibold text-white mb-4">Proceso de Conversión de Nuevos Clientes</h3>
                                <div className="space-y-4">
                                    {[
                                        { label: 'Alumnos en prueba', valor: mes.alumnos_prueba, color: 'bg-zinc-500' },
                                        { label: 'Ejecutaron clase de prueba', valor: mes.alumnos_clase_prueba_ejecutada, color: 'bg-cyan-500' },
                                        { label: 'Compraron plan', valor: mes.alumnos_plan_comprado, color: 'bg-emerald-500' },
                                    ].map((f) => {
                                        const base = Math.max(1, Number(mes.alumnos_prueba));
                                        const pct = Math.min(100, (Number(f.valor) / base) * 100);
                                        return (
                                            <div key={f.label}>
                                                <div className="flex items-center justify-between text-sm mb-1">
                                                    <span className="text-gray-400">{f.label}</span>
                                                    <span className="text-white font-semibold">{f.valor}</span>
                                                </div>
                                                <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
                                                    <div className={`h-full ${f.color}`} style={{ width: `${pct}%` }} />
                                                </div>
                                            </div>
                                        );
                                    })}
                                    <div className="pt-3 border-t border-zinc-800 flex items-center justify-between">
                                        <span className="text-sm text-gray-400">Conversión</span>
                                        <span className="text-xl font-bold text-white">{Number(mes.conversion_rate)}%</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ══ TAB BI (Inteligencia de Negocio) ══ */}
                {!loading && !error && !sinDatos && activeTab === 'bi' && (
                    <div className="space-y-6">
                        {/* ── Alertas operativas (resumen ejecutivo del backend) ── */}
                        {churn?.insight?.mensajes?.length > 0 && (
                            <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5">
                                <div className="flex items-center gap-2 mb-3">
                                    <Sparkles className="w-5 h-5 text-orange-500" />
                                    <h2 className="font-semibold text-white">Alertas Operativas</h2>
                                </div>
                                <ul className="space-y-2">
                                    {churn.insight.mensajes.map((m, i) => (
                                        <li key={i} className="flex gap-2 text-sm text-zinc-200">
                                            <span className="text-orange-500 shrink-0">•</span>
                                            <span>
                                                {m}
                                                {/* La alerta de "riesgo con plan" da acceso directo a
                                                    los alumnos que la originan: NAVEGA a Fidelización
                                                    (la gestión individual vive en esa pantalla). */}
                                                {churn.insight.reglas?.[i] === 'riesgo_con_plan' && (
                                                    <button
                                                        type="button"
                                                        onClick={() => navigate('/admin/fidelizacion?filtro=plan_urgente')}
                                                        aria-label="Ver en Fidelizacion los alumnos de esta alerta"
                                                        className="ml-2 rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-orange-300 hover:bg-zinc-700/60 hover:text-orange-200"
                                                    >
                                                        Ver alumnos
                                                    </button>
                                                )}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            <KpiCard label="Ingresos Recurrentes Mensuales" value={mrrBi === null ? null : Number(mrrBi)} unit="CLP" icon={Banknote} color="border-emerald-500" />
                            <KpiCard
                                label="Proyección mes 1"
                                value={forecast.length ? Number(forecast[0].ingresos_predicho) : null}
                                unit="CLP"
                                icon={TrendingUp}
                                color="border-orange-500"
                            />
                        </div>

                        {/* ── Bloque financiero: ticket promedio por plan + LTV ──
                            El ticket y la vida salen de GET /kpis/financiero; el ARPU se
                            REUSA de GET /reportes/ (misma definición que Reportes.jsx). */}
                        <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5">
                            <div className="mb-4 flex items-center gap-2">
                                <Banknote className="w-5 h-5 text-emerald-500" />
                                <h2 className="font-semibold text-white">Financiero</h2>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div>
                                    <KpiCard
                                        label="Ticket promedio"
                                        value={financiero?.ticket_promedio?.global ?? null}
                                        unit="CLP"
                                        icon={Banknote}
                                        color="border-emerald-500"
                                    />
                                    <p className="mt-1 text-[11px] text-zinc-500">
                                        Membresías ({financiero?.ticket_promedio?.n_transacciones ?? 0} transacciones)
                                    </p>
                                </div>
                                <div>
                                    <KpiCard
                                        label="LTV estimado"
                                        value={ltvEstimado}
                                        unit="CLP"
                                        icon={TrendingUp}
                                        color="border-sky-500"
                                    />
                                    <p className="mt-1 text-[11px] text-zinc-500">
                                        ARPU {arpu != null ? fmtCLP(arpu) : '—'} × {financiero?.vida?.vida_promedio_meses ?? '—'} meses
                                    </p>
                                </div>
                                <div>
                                    <KpiCard
                                        label="Vida promedio del alumno"
                                        value={financiero?.vida?.vida_promedio_meses ?? null}
                                        unit="meses"
                                        icon={Users}
                                        color="border-purple-500"
                                    />
                                    <p className="mt-1 text-[11px] text-zinc-500">
                                        {financiero?.vida?.vida_promedio_dias ?? 0} días · {financiero?.vida?.n_con_baja ?? 0} de {financiero?.vida?.n_alumnos ?? 0} con baja
                                    </p>
                                </div>
                            </div>

                            {financiero?.ticket_promedio?.por_plan?.length > 0 && (
                                <div className="mt-5">
                                    <h3 className="mb-2 text-sm font-semibold text-zinc-300">
                                        Ticket promedio por plan (top 8 por ingreso)
                                    </h3>
                                    <DataTable
                                        columns={[
                                            { key: 'plan', label: 'Plan' },
                                            { key: 'precio_lista', label: 'Precio de lista', render: (v) => fmtCLP(v) },
                                            { key: 'ticket_promedio', label: 'Ticket promedio', render: (v) => fmtCLP(v) },
                                            { key: 'suscripciones', label: 'Suscripciones' },
                                            { key: 'n_transacciones', label: 'Transacciones' },
                                            { key: 'ingreso_total', label: 'Ingreso total', render: (v) => fmtCLP(v) },
                                        ]}
                                        data={financiero.ticket_promedio.por_plan.slice(0, 8)}
                                    />
                                </div>
                            )}

                            <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
                                <span className="text-zinc-400">LTV = ARPU mensual × vida promedio (meses).</span>
                                {' '}El ARPU se toma de GET /api/v1/reportes/ (ingresos netos del mes / alumnos
                                activos: la misma definición que muestra Reportes), así no hay dos versiones del
                                mismo número. Vida promedio: {financiero?.vida?.formula ?? '—'}.
                                {financiero?.vida?.limitaciones ? ` (${financiero.vida.limitaciones})` : ''}
                                {' '}No se calcula CAC: {financiero?.nota_cac ?? 'no hay dato de costo de adquisición.'}
                            </p>
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            <ChartCard title="Pronóstico de ingresos (CLP)"
                                onAmpliar={() => setDetalle('forecast')}>
                                {chartForecast}
                            </ChartCard>

                            {/* Pico vs valle: oferta real por turno (clases y cupo) y, cuando
                                el join asistencias->clase tenga datos, la asistencia promedio
                                por clase. ChartCard admite UN solo gráfico -> las notas van
                                como caption hermano. */}
                            <div>
                                <ChartCard title="Concurrencia por bloque horario (pico vs valle)"
                                    onAmpliar={() => setDetalle('bloques')}>
                                    {chartBloques}
                                </ChartCard>
                                <div className="mt-2 space-y-1 text-[11px] leading-relaxed text-zinc-500">
                                    {bloquePico && (
                                        <p>
                                            Pico: <span className="text-zinc-300">{bloquePico.bloque}</span>
                                            {' '}({bloquePico.clases} clases · cupo prom. {bloquePico.cupo_promedio})
                                            {' · '}Valle: <span className="text-zinc-300">{bloqueValle?.bloque}</span>
                                            {bloqueValle ? ` (${bloqueValle.clases} clases)` : ''}
                                        </p>
                                    )}
                                    {bloques?.cobertura && (
                                        <p>
                                            Asistencias asociadas a su clase: {bloques.cobertura.con_clase} de {bloques.cobertura.asistencias_total} ({bloques.cobertura.pct}%).
                                            {' '}{bloques.cobertura.nota}
                                        </p>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Desglose mes a mes del pronóstico. "Alumnos proyectados" sólo
                            se muestra si el campo viene en la respuesta (hoy viene). */}
                        {tablaPronostico}

                        {/* ── Cohortes de retención por mes de alta ──
                            "n/d" = la cohorte todavía no cumple ese horizonte (no se
                            inventa un 0%): lo resuelve el backend con `evaluables`. */}
                        {cohortes?.cohortes?.length > 0 && (
                            <>
                            <div className="mb-3 flex items-start justify-between gap-3">
                                <h3 className="text-lg font-semibold text-white">
                                    Cohortes de retención por mes de alta
                                </h3>
                                <button
                                    type="button"
                                    onClick={() => setDetalle('cohortes')}
                                    aria-label="Ampliar: Cohortes de retención"
                                    className="shrink-0 rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-zinc-300 transition hover:bg-zinc-700/60 hover:text-white"
                                >
                                    Ampliar
                                </button>
                            </div>
                            {tablaCohortes}
                            </>
                        )}


                    </div>
                )}
            </div>

            {/* ── Detalle ampliado: pronóstico (gráfico + tabla de desglose) ── */}
            {detalle === 'forecast' && (
                <DetalleModal
                    titulo="Pronóstico de ingresos (CLP)"
                    subtitulo="Proyección mes a mes y su desglose, en grande"
                    onCerrar={() => setDetalle(null)}
                    explicacion={(
                        <>
                            Proyección de ingresos del box mes a mes, calculada por el modelo de pronóstico
                            (GET /kpis/forecast) sobre los ingresos históricos (transacciones_financieras,
                            netos: ingresos − egresos) agrupados por mes. Cada punto es el ingreso proyectado
                            de ese mes; la tabla de abajo muestra además la variación % contra el mes anterior
                            y los alumnos proyectados cuando el modelo los estima. Si un mes no tiene mes
                            anterior comparable, la variación aparece como guion en vez de un 0% inventado.
                        </>
                    )}
                >
                    <ChartCard title="Pronóstico de ingresos (CLP)" height="h-96">
                        {chartForecast}
                    </ChartCard>
                    <div className="mt-4">{tablaPronostico}</div>
                </DetalleModal>
            )}

            {/* ── Detalle ampliado: pico vs valle por bloque horario ── */}
            {detalle === 'bloques' && (
                <DetalleModal
                    titulo="Concurrencia por bloque horario (pico vs valle)"
                    subtitulo="Oferta real por turno y, cuando hay datos, asistencia por clase"
                    onCerrar={() => setDetalle(null)}
                    explicacion={(
                        <>
                            Mide la OFERTA de clases por franja horaria: cuántas clases se dictan en cada
                            bloque y el cupo promedio ofrecido. La barra naranja (asistencias por clase) es
                            el promedio de asistentes confirmados por clase del bloque, que es el dato que
                            permite comparar pico vs valle. Sirve para decidir dónde falta oferta y dónde
                            sobra cupo. Hoy la asistencia por clase puede verse en 0 porque las asistencias
                            todavía no están vinculadas a su clase (asistencias.clase_id es NULL en toda la
                            base): el dato siempre confiable de este gráfico es la oferta (clases y cupo).
                        </>
                    )}
                >
                    <ChartCard title="Concurrencia por bloque horario (pico vs valle)" height="h-96">
                        {chartBloques}
                    </ChartCard>
                    <div className="mt-4 space-y-1 text-xs leading-relaxed text-zinc-400">
                        {bloquePico && (
                            <p>
                                Pico: <span className="text-zinc-200">{bloquePico.bloque}</span>
                                {' '}({bloquePico.clases} clases · cupo prom. {bloquePico.cupo_promedio})
                                {' · '}Valle: <span className="text-zinc-200">{bloqueValle?.bloque}</span>
                                {bloqueValle ? ` (${bloqueValle.clases} clases)` : ''}
                            </p>
                        )}
                        {bloques?.cobertura && (
                            <p>
                                Asistencias asociadas a su clase: {bloques.cobertura.con_clase} de{' '}
                                {bloques.cobertura.asistencias_total} ({bloques.cobertura.pct}%).{' '}
                                {bloques.cobertura.nota}
                            </p>
                        )}
                    </div>
                </DetalleModal>
            )}

            {/* ── Detalle ampliado: cohortes de retención ── */}
            {detalle === 'cohortes' && (
                <DetalleModal
                    titulo="Cohortes de retención por mes de alta"
                    subtitulo="Retención a 30, 60 y 90 días por cohorte (mes de alta del alumno)"
                    onCerrar={() => setDetalle(null)}
                    explicacion={(
                        <>
                            Cohorte = mes de alta del alumno (usuarios.created_at). "Activo a los N días"
                            significa que el alumno tiene al menos una asistencia en la ventana
                            [alta, alta + N días]: es la señal de retención disponible hoy, porque las
                            asistencias todavía no están asociadas a su clase. Solo se promedian los
                            alumnos EVALUABLES, es decir los que ya cumplieron ese horizonte; si la cohorte
                            es más joven, la celda muestra n/d en vez de un 0% inventado.
                        </>
                    )}
                >
                    {tablaCohortes}
                </DetalleModal>
            )}
        </Layout>
    );
};

export default AdminKpis;





