import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    BarChart, Bar, AreaChart, Area, LineChart, Line,
    XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import {
    TrendingUp, Users, UserPlus, Activity, DollarSign, Percent,
    CalendarDays, TriangleAlert, Award, Banknote, ShoppingCart, Gauge, Target,
} from 'lucide-react';
import Layout from '../../components/Layout';
import api from '../../services/api';
import { TabBar } from '../../components/kpis/TabBar';
import { KpiCard } from '../../components/kpis/KpiCard';
import { ChartCard } from '../../components/kpis/ChartCard';
import { DataTable } from '../../components/kpis/DataTable';
import { RiskBadge } from '../../components/kpis/RiskBadge';

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
    const activeTab = searchParams.get('tab') || 'diario';

    const [loading, setLoading] = useState(true);
    const [sinDatos, setSinDatos] = useState(false);
    const [error, setError] = useState(null);

    const [serieDiaria, setSerieDiaria] = useState([]);
    const [serieMensual, setSerieMensual] = useState([]);
    const [churn, setChurn] = useState(null);
    const [forecast, setForecast] = useState([]);
    const [segmentos, setSegmentos] = useState(null);
    const [mrrBi, setMrrBi] = useState(null);

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

    // ─── BI: churn + forecast + segmentos (+ MRR del mes) ────────────────
    const cargarBi = useCallback(async () => {
        setLoading(true); setError(null); setSinDatos(false);
        const hoy = new Date();
        try {
            const [churnRes, forecastRes, segRes] = await Promise.all([
                api.get('/api/v1/kpis/churn'),
                api.get('/api/v1/kpis/forecast', { params: { meses: 3 } }),
                api.get('/api/v1/kpis/segments'),
            ]);
            setChurn(churnRes.data);
            setForecast(forecastRes.data?.proyecciones || []);
            setSegmentos(segRes.data);

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

    return (
        <Layout>
            <div className="max-w-7xl mx-auto">
                {/* ── Encabezado ── */}
                <div className="mb-6 flex items-center gap-3">
                    <TrendingUp className="w-8 h-8 text-orange-500" />
                    <div>
                        <h1 className="text-3xl font-bold text-white">KPIs</h1>
                        <p className="text-sm text-gray-400">
                            Indicadores desde los data marts (poblados por los workflows de n8n)
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
                            Los data marts se llenan con los workflows de n8n
                            (Populate Daily KPIs, Populate Monthly KPIs y Populate Predictions).
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
                            <KpiCard label="Churn rate" value={Number(mes.churn_rate)} unit="%" icon={TriangleAlert} color="border-red-500" />
                            <KpiCard label="MRR" value={Number(mes.mrr)} unit="CLP" icon={Banknote} color="border-emerald-500" />
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
                                <ChartCard title="Últimos 6 meses · MRR e ingresos (CLP)">
                                    <AreaChart data={serieMensual}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                                        <XAxis dataKey="month" tickFormatter={(mm) => MESES[Number(mm) - 1]} stroke="#a1a1aa" fontSize={12} />
                                        <YAxis stroke="#a1a1aa" fontSize={12} />
                                        <Tooltip {...TOOLTIP_STYLE} formatter={(v) => fmtCLP(v)} />
                                        <Area type="monotone" dataKey="mrr" name="MRR" stroke="#f97316" fill="#f97316" fillOpacity={0.25} />
                                        <Area type="monotone" dataKey="ingresos_total" name="Ingresos" stroke="#10b981" fill="#10b981" fillOpacity={0.2} />
                                    </AreaChart>
                                </ChartCard>
                            </div>

                            {/* Embudo prueba → plan (card simple, no es gráfico recharts) */}
                            <div className="bg-zinc-900 rounded-lg shadow p-6">
                                <h3 className="text-lg font-semibold text-white mb-4">Embudo prueba → plan</h3>
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
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            <KpiCard label="Churn crítico" value={churn?.criticos ?? 0} icon={TriangleAlert} color="border-red-500" />
                            <KpiCard label="Riesgo alto" value={churn?.altos ?? 0} icon={TriangleAlert} color="border-orange-500" />
                            <KpiCard label="En riesgo (total)" value={churn?.total ?? 0} icon={Users} color="border-yellow-500" />
                            <KpiCard
                                label="Listos para upgrade"
                                value={(segmentos?.segmentos || []).filter((s) => s.ready_for_upgrade).length}
                                icon={Award}
                                color="border-emerald-500"
                            />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            <KpiCard label="MRR" value={mrrBi === null ? null : Number(mrrBi)} unit="CLP" icon={Banknote} color="border-emerald-500" />
                            <KpiCard label="Alumnos segmentados" value={segmentos?.segmentos?.length ?? 0} icon={Users} color="border-sky-500" />
                            <KpiCard label="Nivel avanzado" value={segmentos?.totales?.avanzado ?? 0} icon={Award} color="border-purple-500" />
                            <KpiCard
                                label="Proyección mes 1"
                                value={forecast.length ? Number(forecast[0].ingresos_predicho) : null}
                                unit="CLP"
                                icon={TrendingUp}
                                color="border-orange-500"
                            />
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            <ChartCard title="Pronóstico de ingresos (CLP)">
                                <LineChart data={forecast}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                                    <XAxis dataKey="mes_prediccion" tickFormatter={fmtMesCorto} stroke="#a1a1aa" fontSize={12} />
                                    <YAxis stroke="#a1a1aa" fontSize={12} />
                                    <Tooltip {...TOOLTIP_STYLE} formatter={(v) => fmtCLP(v)} />
                                    <Line type="monotone" dataKey="ingresos_predicho" name="Ingresos proyectados" stroke="#f97316" strokeWidth={2} dot={{ r: 4 }} />
                                </LineChart>
                            </ChartCard>

                            <ChartCard title="Segmentación de atletas por nivel">
                                <BarChart
                                    data={[
                                        { nivel: 'Básico', cantidad: segmentos?.totales?.basico ?? 0 },
                                        { nivel: 'Intermedio', cantidad: segmentos?.totales?.intermedio ?? 0 },
                                        { nivel: 'Avanzado', cantidad: segmentos?.totales?.avanzado ?? 0 },
                                    ]}
                                >
                                    <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                                    <XAxis dataKey="nivel" stroke="#a1a1aa" fontSize={12} />
                                    <YAxis stroke="#a1a1aa" fontSize={12} allowDecimals={false} />
                                    <Tooltip {...TOOLTIP_STYLE} />
                                    <Bar dataKey="cantidad" name="Atletas" fill="#a855f7" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            </ChartCard>
                        </div>

                        <h2 className="text-lg font-semibold text-white pt-2">
                            Predicción de churn ({churn?.total ?? 0})
                        </h2>
                        <DataTable
                            columns={[
                                { key: 'usuario_id', label: 'Alumno (ID)' },
                                { key: 'probabilidad_churn', label: 'Probabilidad', render: (v) => `${Number(v).toFixed(1)}%` },
                                { key: 'riesgo_nivel', label: 'Riesgo', render: (v) => <RiskBadge nivel={v} /> },
                                { key: 'motivo', label: 'Motivo' },
                                { key: 'estado_gestion', label: 'Gestión' },
                                { key: 'fecha_proxima_renovacion', label: 'Próx. renovación', render: (v) => v || '—' },
                            ]}
                            data={churn?.predicciones || []}
                        />

                        <h2 className="text-lg font-semibold text-white pt-2">
                            Segmentación de atletas ({(segmentos?.segmentos || []).length})
                        </h2>
                        <DataTable
                            columns={[
                                { key: 'usuario_id', label: 'Alumno (ID)' },
                                { key: 'nivel', label: 'Nivel' },
                                { key: 'fuerza_score', label: 'Fuerza', render: (v) => Number(v).toFixed(1) },
                                { key: 'gymnastica_score', label: 'Gimnasia', render: (v) => Number(v).toFixed(1) },
                                { key: 'asistencia_score', label: 'Asistencia', render: (v) => Number(v).toFixed(1) },
                                { key: 'retention_score', label: 'Retención', render: (v) => Number(v).toFixed(1) },
                                { key: 'ready_for_upgrade', label: 'Upgrade', render: (v) => (v ? '✅' : '—') },
                            ]}
                            data={segmentos?.segmentos || []}
                        />
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default AdminKpis;





