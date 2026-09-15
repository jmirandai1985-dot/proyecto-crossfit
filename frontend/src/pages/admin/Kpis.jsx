import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    BarChart, Bar, AreaChart, Area, LineChart, Line,
    XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import {
    TrendingUp, Users, UserPlus, Activity, DollarSign, Percent,
    CalendarDays, TriangleAlert, Banknote, ShoppingCart, Gauge, Target, Eye,
    Sparkles,
} from 'lucide-react';
import Layout from '../../components/Layout';
import api from '../../services/api';
import { TabBar } from '../../components/kpis/TabBar';
import { KpiCard } from '../../components/kpis/KpiCard';
import { ChartCard } from '../../components/kpis/ChartCard';
import { DataTable } from '../../components/kpis/DataTable';
import { RiskBadge } from '../../components/kpis/RiskBadge';
import { ArquetipoBadge } from '../../components/kpis/ArquetipoBadge';
import { ARQUETIPOS_UI, estiloArquetipo, arquetipoDe } from '../../components/kpis/arquetipoEstilo';
import { RecomendacionModal } from '../../components/kpis/RecomendacionModal';
import { estiloReco } from '../../components/kpis/recoEstilo';

const TABS = [
    { id: 'diario', label: 'Diario' },
    { id: 'mensual', label: 'Mensual' },
    { id: 'bi', label: 'Inteligencia de Negocio' },
];

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
    'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

// ─── Gestión prescriptiva del riesgo de abandono (pestaña BI) ─────────────
// Estados aceptados por PUT /api/v1/kpis/churn/{usuario_id}/estado.
const ESTADOS_GESTION = ['PENDIENTE', 'CONTACTADO', 'RECUPERADO'];

// Etiquetas legibles para el `tipo` del último correo automático
// (`ultimo_contacto_automatico.tipo`, tal como se guarda en notificaciones_enviadas).
const ETIQUETA_CONTACTO = {
    inactividad: 'Inactividad',
    renovacion_plan: 'Renovación de plan',
    vencimiento: 'Plan por vencer',
    vencimiento_inminente: 'Plan por vencer',
    ultimo_credito: 'Último crédito',
    sin_creditos: 'Sin créditos',
    reactivacion: 'Reactivación',
    cumplimiento: 'Cumplimiento',
    acompanamiento: 'Acompañamiento',
    bienvenida: 'Bienvenida',
    activacion: 'Activación',
    bienvenida_activacion: 'Bienvenida y activación',
    confirmacion_renovacion: 'Confirmación de renovación',
    confirmacion_plan: 'Confirmación de plan',
    confirmacion_pedido: 'Confirmación de pedido',
};

const etiquetaContacto = (tipo) => {
    const t = String(tipo || '');
    if (!t) return 'Contacto';
    if (ETIQUETA_CONTACTO[t]) return ETIQUETA_CONTACTO[t];
    if (t.startsWith('hito_racha')) return 'Hito de racha';
    // Fallback: snake_case → "Texto legible"
    return t.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
};

// "hoy" / "hace 1 día" / "hace 3 días"
const fmtHace = (dias) => {
    const n = Number(dias);
    if (!Number.isFinite(n) || n <= 0) return 'hoy';
    return `hace ${n} día${n === 1 ? '' : 's'}`;
};

// Texto del último contacto automático ("Inactividad · hace 3 días") o null.
// Lo comparten la columna "Último contacto" y el modal de detalle (contactoTxt).
const fmtUltimoContacto = (v) => (
    v ? `${etiquetaContacto(v.tipo)} · ${fmtHace(v.hace_dias)}` : null
);

// Filtros de la tabla de churn: se aplican en el propio panel con los datos que
// ya vienen en cada fila (sin endpoint nuevo). Los activan las tarjetas de KPI y
// el botón "Ver alumnos" de las alertas operativas.
const FILTROS_CHURN = {
    critico: {
        etiqueta: 'Abandono crítico',
        test: (f) => f.riesgo_nivel === 'CRITICO',
    },
    alto: {
        etiqueta: 'Riesgo alto',
        test: (f) => f.riesgo_nivel === 'ALTO',
    },
    total: {
        etiqueta: 'En riesgo (todos)',
        test: () => true,
    },
    plan_urgente: {
        // Misma condición que la Regla B del backend: riesgo ALTO/CRÍTICO con
        // plan vigente que vence en ≤7 días.
        etiqueta: 'Riesgo alto/crítico con plan que vence en ≤7 días',
        test: (f) => {
            if (!['ALTO', 'CRITICO'].includes(f.riesgo_nivel)) return false;
            if (!f.fecha_proxima_renovacion) return false;
            const limite = new Date();
            limite.setDate(limite.getDate() + 7);
            return String(f.fecha_proxima_renovacion).slice(0, 10) <= toISO(limite);
        },
    },
};

// Los 6 arquetipos son TAMBIÉN claves de filtro del MISMO estado `filtroChurn`:
// elegir un arquetipo reemplaza al filtro de riesgo y viceversa (no se acumulan).
// Los alimentan el dropdown de filtros y las tarjetas del resumen por arquetipos.
const FILTROS_ARQUETIPO = ARQUETIPOS_UI.reduce((acc, codigo) => {
    acc[codigo] = {
        etiqueta: `Arquetipo: ${estiloArquetipo(codigo).label}`,
        test: (f) => arquetipoDe(f) === codigo,
    };
    return acc;
}, {});

// Catálogo completo (riesgo + arquetipo): resuelve etiqueta y test por clave.
const FILTROS_CHURN_TODOS = { ...FILTROS_CHURN, ...FILTROS_ARQUETIPO };
const filtroChurnDef = (clave) => FILTROS_CHURN_TODOS[clave];

// Los estilos/etiquetas por código de recomendación viven en
// components/kpis/recoEstilo.js (los comparte el modal de detalle).

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

// "14 sep 23:27" (hora local del navegador) para la fecha del modelo de
// segmentación (`modelo_fecha` de GET /api/v1/segmentacion).
const fmtFechaHora = (iso) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${d.getDate()} ${MESES[d.getMonth()]} ${hh}:${mm}`;
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
    const activeTab = searchParams.get('tab') || 'diario';

    const [loading, setLoading] = useState(true);
    const [sinDatos, setSinDatos] = useState(false);
    const [error, setError] = useState(null);

    const [serieDiaria, setSerieDiaria] = useState([]);
    const [serieMensual, setSerieMensual] = useState([]);
    const [churn, setChurn] = useState(null);
    const [forecast, setForecast] = useState([]);
    const [mrrBi, setMrrBi] = useState(null);

    // ─── BI: gestión por fila (dropdown) + toast ─────────────────────────
    const [gestionando, setGestionando] = useState(null); // usuario_id en curso
    const [toast, setToast] = useState(null);             // { mensaje, tipo }
    const toastTimer = useRef(null);
    // Fila cuyo detalle de recomendación se muestra en el modal (null = cerrado).
    const [detalleReco, setDetalleReco] = useState(null);
    // Clave del filtro activo sobre la tabla de churn (null = sin filtro).
    const [filtroChurn, setFiltroChurn] = useState(null);
    // Resumen de segmentación (GET /api/v1/segmentacion): conteos por arquetipo.
    const [segmentacion, setSegmentacion] = useState(null);

    // Toast breve auto-ocultable. El proyecto NO usa librería de toasts
    // (el resto de páginas recurre a `alert()`), así que acá va uno propio
    // y no bloqueante. Si algún día se agrega react-hot-toast, se reemplaza
    // sólo esta función y el bloque de render del toast.
    const mostrarToast = (mensaje, tipo = 'ok') => {
        setToast({ mensaje, tipo });
        clearTimeout(toastTimer.current);
        toastTimer.current = setTimeout(() => setToast(null), 3500);
    };

    useEffect(() => () => clearTimeout(toastTimer.current), []);

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

            // Segmentación por arquetipos: endpoint APARTE y opcional. Si falla o
            // todavía no se reentrenó, el bloque de resumen no se muestra (el resto
            // de la pestaña BI sigue funcionando igual).
            const rSeg = await api.get('/api/v1/segmentacion').catch(() => null);
            setSegmentacion(rSeg?.data || null);
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

    /**
     * PUT /api/v1/kpis/churn/{usuario_id}/estado — cambia la gestión de UNA fila.
     *
     * El <select> es controlado y su `value` sale del estado `churn`: si la
     * llamada falla NO tocamos el estado, React re-renderiza con el valor viejo
     * y el select vuelve solo al estado anterior (no hace falta revertir a mano).
     * El token del admin lo agrega el interceptor de `services/api`.
     */
    const cambiarGestion = async (row, nuevoEstado) => {
        const anterior = row.estado_gestion || 'PENDIENTE';
        if (nuevoEstado === anterior) return;

        setGestionando(row.usuario_id);
        try {
            const { data } = await api.put(
                `/api/v1/kpis/churn/${row.usuario_id}/estado`,
                { estado_gestion: nuevoEstado },
            );
            // El PUT devuelve la MISMA forma de fila que el GET (+ estado_anterior):
            // se actualiza sólo esa fila, sin recargar toda la tabla.
            const { estado_anterior, ...fila } = data;
            setChurn((prev) => (prev ? {
                ...prev,
                predicciones: (prev.predicciones || []).map(
                    (p) => (p.usuario_id === row.usuario_id ? { ...p, ...fila } : p),
                ),
            } : prev));
            mostrarToast(
                `${fila.alumno_nombre || `Alumno #${row.usuario_id}`}: `
                + `${estado_anterior || anterior} → ${fila.estado_gestion}`,
            );
        } catch (err) {
            mostrarToast(
                err.response?.data?.detail || 'No se pudo guardar la gestión. Reintentá.',
                'error',
            );
        } finally {
            setGestionando(null);
        }
    };

    const dia = serieDiaria.length ? serieDiaria[serieDiaria.length - 1] : null;
    const mes = serieMensual.length ? serieMensual[serieMensual.length - 1] : null;

    // Lista de churn con el filtro activo aplicado (client-side).
    const prediccionesChurn = churn?.predicciones || [];
    const prediccionesFiltradas = filtroChurn
        ? prediccionesChurn.filter(filtroChurnDef(filtroChurn).test)
        : prediccionesChurn;

    // Valor del dropdown de arquetipo: deriva del filtro COMPARTIDO ('' = todos),
    // así también refleja lo que se elige desde las tarjetas de arquetipo.
    const filtroArquetipo = ARQUETIPOS_UI.includes(filtroChurn) ? filtroChurn : '';

    // Las 6 tarjetas del resumen, en el orden de ARQUETIPOS_UI (el backend manda
    // su propio orden y puede no traer los que quedaron en 0 -> default 0).
    const arquetiposSegmentacion = ARQUETIPOS_UI.map((codigo) => {
        const item = (segmentacion?.arquetipos || [])
            .find((a) => a.arquetipo === codigo);
        return { codigo, ...(item || { n: 0, pct: 0, descripcion: '' }) };
    });

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
                            <KpiCard label="Riesgo de Abandono" value={Number(mes.churn_rate)} unit="%" icon={TriangleAlert} color="border-red-500" />
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
                                                {/* La alerta de "riesgo con plan" trae el acceso
                                                    directo a los alumnos que la originan. */}
                                                {churn.insight.reglas?.[i] === 'riesgo_con_plan' && (
                                                    <button
                                                        type="button"
                                                        onClick={() => setFiltroChurn((prev) => (
                                                            prev === 'plan_urgente' ? null : 'plan_urgente'))}
                                                        aria-label={filtroChurn === 'plan_urgente'
                                                            ? 'Quitar filtro de la alerta'
                                                            : 'Ver alumnos de la alerta'}
                                                        className="ml-2 rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-orange-300 hover:bg-zinc-700/60 hover:text-orange-200"
                                                    >
                                                        {filtroChurn === 'plan_urgente' ? 'Quitar filtro' : 'Ver alumnos'}
                                                    </button>
                                                )}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            {/* Tarjetas clickeables: filtran la tabla de abajo por nivel de
                                riesgo. Click de nuevo (o "Ver todos") quita el filtro. */}
                            {[
                                { clave: 'critico', label: 'Abandono Crítico', valor: churn?.criticos ?? 0, icon: TriangleAlert, color: 'border-red-500' },
                                { clave: 'alto', label: 'Riesgo alto', valor: churn?.altos ?? 0, icon: TriangleAlert, color: 'border-orange-500' },
                                { clave: 'total', label: 'En riesgo (total)', valor: churn?.total ?? 0, icon: Users, color: 'border-yellow-500' },
                            ].map(({ clave, label, valor, icon, color }) => (
                                <button
                                    key={clave}
                                    type="button"
                                    onClick={() => setFiltroChurn((prev) => (prev === clave ? null : clave))}
                                    aria-pressed={filtroChurn === clave}
                                    aria-label={`Filtrar la tabla por: ${filtroChurnDef(clave).etiqueta}`}
                                    title={filtroChurn === clave
                                        ? 'Quitar este filtro'
                                        : 'Filtrar la tabla por este grupo'}
                                    className={`w-full text-left rounded-lg transition ${filtroChurn === clave
                                        ? 'ring-2 ring-orange-500'
                                        : 'hover:ring-1 hover:ring-zinc-600'}`}
                                >
                                    <KpiCard label={label} value={valor} icon={icon} color={color} />
                                </button>
                            ))}
                        </div>

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
                        </div>

                        {/* Desglose mes a mes del pronóstico. "Alumnos proyectados" sólo
                            se muestra si el campo viene en la respuesta (hoy viene). */}
                        <div>
                            <h3 className="text-lg font-semibold text-white mb-3">Detalle del pronóstico (mes a mes)</h3>
                            <DataTable
                                columns={[
                                    { key: 'mes_prediccion', label: 'Mes', render: (v) => fmtMesCorto(v) },
                                    { key: 'ingresos_predicho', label: 'Ingresos proyectados (CLP)', render: (v) => fmtCLP(v) },
                                    {
                                        key: 'variacion', label: 'Variación vs mes anterior',
                                        render: (v) => (v === null
                                            ? '—'
                                            : `${v > 0 ? '+' : ''}${v.toLocaleString('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`),
                                    },
                                    ...(forecast.some((f) => f.alumnos_predicho != null)
                                        ? [{
                                            key: 'alumnos_predicho', label: 'Alumnos proyectados',
                                            render: (v) => (v ?? '—'),
                                        }]
                                        : []),
                                ]}
                                data={forecastDetalle}
                            />
                        </div>

                        {/* ── Resumen por arquetipos (GET /api/v1/segmentacion) ──
                            Tarjetas clickeables: filtran la MISMA tabla, con el mismo
                            estado de filtro compartido que las tarjetas de riesgo. */}
                        {segmentacion?.total > 0 && (
                            <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5">
                                <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                                    <div className="flex items-center gap-2">
                                        <Sparkles className="w-5 h-5 text-sky-400" />
                                        <h2 className="font-semibold text-white">Segmentación de alumnos</h2>
                                    </div>
                                    <p className="text-xs text-zinc-500">
                                        {segmentacion.total} alumnos segmentados
                                        {segmentacion.modelo_fecha
                                            ? ` · modelo del ${fmtFechaHora(segmentacion.modelo_fecha)}`
                                            : ''}
                                    </p>
                                </div>
                                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                                    {arquetiposSegmentacion.map(({ codigo, n, pct, descripcion }) => {
                                        const estilo = estiloArquetipo(codigo);
                                        const activo = filtroChurn === codigo;
                                        return (
                                            <button
                                                key={codigo}
                                                type="button"
                                                onClick={() => setFiltroChurn((prev) => (prev === codigo ? null : codigo))}
                                                aria-pressed={activo}
                                                aria-label={`Filtrar la tabla por arquetipo: ${estilo.label}`}
                                                title={descripcion
                                                    ? `${descripcion} Click para filtrar la tabla.`
                                                    : 'Click para filtrar la tabla.'}
                                                className={`rounded-lg border-l-4 ${estilo.borde} bg-zinc-800/60 p-3 text-left transition ${activo
                                                    ? 'ring-2 ring-orange-500'
                                                    : 'hover:ring-1 hover:ring-zinc-600'}`}
                                            >
                                                <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                                                    {estilo.label}
                                                </p>
                                                <p className="mt-1 text-2xl font-bold text-white">{n}</p>
                                                <p className="text-[11px] text-zinc-500">{pct}% del total</p>
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                        {!segmentacion?.total && (
                            <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-4 text-xs text-zinc-500">
                                Sin segmentación calculada todavía (se genera con
                                <span className="text-zinc-400"> POST /api/v1/segmentacion/reentrenar</span>).
                            </div>
                        )}

                        <div className="flex flex-wrap items-end justify-between gap-3 pt-2">
                            <h2 className="text-lg font-semibold text-white">
                                Predicción de Riesgo de Abandono ({churn?.total ?? 0})
                            </h2>
                            {/* Filtro por arquetipo: comparte el estado `filtroChurn` con
                                las tarjetas de riesgo y con las de arquetipo. */}
                            <label className="flex items-center gap-2 text-xs text-zinc-400">
                                Arquetipo
                                <select
                                    value={filtroArquetipo}
                                    onChange={(e) => setFiltroChurn(e.target.value || null)}
                                    aria-label="Filtrar la tabla por arquetipo de segmentación"
                                    className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-orange-500"
                                >
                                    <option value="">Todos</option>
                                    {ARQUETIPOS_UI.map((codigo) => (
                                        <option key={codigo} value={codigo}>
                                            {estiloArquetipo(codigo).label}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        </div>

                        {/* Indicador del filtro activo + forma de quitarlo */}
                        {filtroChurn && (
                            <div className="flex flex-wrap items-center gap-2 -mt-3 text-xs">
                                <span className="rounded bg-zinc-800 px-2 py-0.5 text-orange-300">
                                    Filtro: {filtroChurnDef(filtroChurn).etiqueta}
                                </span>
                                <span className="text-zinc-500">
                                    {prediccionesFiltradas.length} de {prediccionesChurn.length} alumnos
                                </span>
                                <button
                                    type="button"
                                    onClick={() => setFiltroChurn(null)}
                                    className="text-zinc-300 underline hover:text-orange-300"
                                >
                                    Ver todos
                                </button>
                            </div>
                        )}

                        {/* Tabla de churn: 7 columnas. "Último contacto" y "Próx. renovación" se
                            movieron al modal de detalle (RecomendacionModal) para que entre sin
                            scroll horizontal. OJO: dentro del array de columnas NO se pueden
                            poner comentarios con llaves (se parsean como objeto vacio y
                            aparece una columna fantasma): los comentarios van acá afuera. */}
                        <DataTable
                            columns={[
                                {
                                    key: 'alumno_nombre', label: 'Alumno',
                                    render: (v, row) => (
                                        <div className="leading-tight">
                                            <div className="text-white">{v || `Alumno #${row.usuario_id}`}</div>
                                            <div className="text-[10px] text-zinc-500">
                                                #{row.usuario_id}{row.alumno_correo ? ` · ${row.alumno_correo}` : ''}
                                            </div>
                                        </div>
                                    ),
                                },
                                { key: 'probabilidad_churn', label: 'Probabilidad de Abandono', render: (v) => `${Number(v).toFixed(1)}%` },
                                { key: 'riesgo_nivel', label: 'Riesgo', render: (v) => <RiskBadge nivel={v} /> },
                                { key: 'arquetipo', label: 'Arquetipo', render: (v) => <ArquetipoBadge arquetipo={v} /> },
                                { key: 'motivo', label: 'Motivo' },
                                {
                                    key: 'recomendacion', label: 'Recomendación',
                                    render: (v, row) => {
                                        if (!v) return <span className="text-zinc-500">—</span>;
                                        const e = estiloReco(row.recomendacion_codigo);
                                        return (
                                            <div className={`max-w-xs border-l-2 pl-2 ${e.borde}`} title={v}>
                                                <div className="flex items-start justify-between gap-2">
                                                    <div className={`text-[10px] font-semibold uppercase tracking-wide ${e.texto}`}>
                                                        {e.etiqueta}
                                                    </div>
                                                    <button
                                                        type="button"
                                                        onClick={() => setDetalleReco(row)}
                                                        title="Ver recomendación completa"
                                                        aria-label={`Ver recomendación completa de ${row.alumno_nombre || `alumno #${row.usuario_id}`}`}
                                                        className="shrink-0 rounded p-0.5 text-zinc-400 hover:bg-zinc-700/60 hover:text-orange-400"
                                                    >
                                                        <Eye className="h-3.5 w-3.5" />
                                                    </button>
                                                </div>
                                                <div className="text-xs leading-snug text-zinc-300 line-clamp-2">{v}</div>
                                            </div>
                                        );
                                    },
                                },
                                {
                                    key: 'estado_gestion', label: 'Gestión',
                                    render: (v, row) => (
                                        <div className="flex items-center gap-2">
                                            <select
                                                value={v || 'PENDIENTE'}
                                                disabled={gestionando === row.usuario_id}
                                                onChange={(e) => cambiarGestion(row, e.target.value)}
                                                aria-label={`Estado de gestión de ${row.alumno_nombre || `alumno #${row.usuario_id}`}`}
                                                className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs text-white disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:border-orange-500"
                                            >
                                                {ESTADOS_GESTION.map((op) => (
                                                    <option key={op} value={op}>{op}</option>
                                                ))}
                                            </select>
                                            {gestionando === row.usuario_id && (
                                                <span className="text-[10px] text-zinc-400 animate-pulse">guardando…</span>
                                            )}
                                        </div>
                                    ),
                                },
                            ]}
                            data={prediccionesFiltradas}
                        />
                    </div>
                )}
            </div>

            {/* Modal con el detalle completo de la recomendación (icono 👁 de la fila) */}
            {detalleReco && (
                <RecomendacionModal
                    fila={detalleReco}
                    onClose={() => setDetalleReco(null)}
                    contactoTxt={fmtUltimoContacto(detalleReco.ultimo_contacto_automatico)}
                    renovacionTxt={detalleReco.fecha_proxima_renovacion
                        ? fmtFechaCorta(detalleReco.fecha_proxima_renovacion) : null}
                />
            )}

            {/* Toast breve de confirmación / error (no bloqueante) */}
            {toast && (
                <div
                    role="status"
                    aria-live="polite"
                    className={`fixed bottom-4 right-4 z-50 max-w-sm rounded-lg border px-4 py-3 text-sm font-medium shadow-lg ${
                        toast.tipo === 'error'
                            ? 'bg-red-950 border-red-600 text-red-200'
                            : 'bg-emerald-950 border-emerald-600 text-emerald-200'
                    }`}
                >
                    {toast.mensaje}
                </div>
            )}
        </Layout>
    );
};

export default AdminKpis;





