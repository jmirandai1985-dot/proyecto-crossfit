import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    BarChart, Bar, AreaChart, Area, LineChart, Line,
    XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
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
import AvisoCarga from '../../components/AvisoCarga';

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

// Índice estacional: 1,00x = un mes igual al promedio del período; 1,42x = 42%
// arriba del promedio. `null` = ese mes no tiene dato (se muestra "s/d", nunca 0).
const fmtIndice = (v) => (v === null || v === undefined)
    ? 's/d'
    : `${Number(v).toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×`;

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
    // Pestaña MENSUAL: meses con fila en `monthly_kpis` (índice del backend), el mes
    // elegido en el selector y el mes EN CURSO (calendario chileno) que informa el
    // backend para poder decir "todavía no cerró" sin adivinarlo en el navegador.
    const [periodos, setPeriodos] = useState([]);
    const [mesSel, setMesSel] = useState(null);
    const [mesActual, setMesActual] = useState(null);
    // Secciones que fallaron al cargar (banner AvisoCarga + Reintentar).
    const [erroresCarga, setErroresCarga] = useState([]);
    const [churn, setChurn] = useState(null);
    const [forecast, setForecast] = useState([]);
    const [mrrBi, setMrrBi] = useState(null);
    // Bloque financiero: ticket promedio + vida (GET /kpis/financiero) y ARPU
    // REUSADO de GET /reportes/ (misma fuente que muestra Reportes.jsx).
    const [financiero, setFinanciero] = useState(null);
    const [arpu, setArpu] = useState(null);
    // Bloques horarios (pico vs valle): oferta y asistencia por turno.
    const [bloques, setBloques] = useState(null);
    // Estacionalidad: índice por mes del año (ene..dic) de ingresos y alumnos.
    const [estacionalidad, setEstacionalidad] = useState(null);
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

    // ─── MENSUAL: meses CON fila en monthly_kpis (índice) ────────────────
    // Antes se pedían a ciegas los últimos 6 meses: los que no tienen fila (el mes
    // en curso, o los meses que el job aún no pobló) respondían 404 y se descartaban.
    // Con el índice se pide SOLO lo que existe, se muestra por defecto el ÚLTIMO MES
    // CERRADO con datos y se puede elegir otro mes en el selector.
    const cargarMensual = useCallback(async (seleccion = null) => {
        setLoading(true); setError(null); setSinDatos(false); setErroresCarga([]);
        try {
            const rPer = await api.get('/api/v1/kpis/mensual/periodos');
            const lista = rPer.data?.periodos || [];
            setPeriodos(lista);
            setMesActual(rPer.data?.actual || null);

            if (lista.length === 0) {
                setMesSel(null); setSerieMensual([]); setSinDatos(true);
                setLoading(false);
                return;
            }

            // Mes a mostrar: el que eligió el usuario (si sigue existiendo) o el
            // `default` del backend = último mes CERRADO con datos.
            const defaultEs = rPer.data?.default || null;
            const pedido = (seleccion && lista.some((p) => p.year === seleccion.year && p.month === seleccion.month))
                ? seleccion
                : defaultEs;
            setMesSel(pedido);

            // Serie del gráfico: los últimos 6 meses CON datos hasta el elegido.
            const idx = pedido
                ? lista.findIndex((p) => p.year === pedido.year && p.month === pedido.month)
                : -1;
            const fin = idx >= 0 ? idx + 1 : lista.length;
            const recorte = lista.slice(Math.max(0, fin - 6), fin);
            const res = await Promise.allSettled(
                recorte.map((p) => api.get('/api/v1/kpis/mensual', { params: { year: p.year, month: p.month } }))
            );
            const serie = res
                .map((r, i) => (r.status === 'fulfilled' ? { ...r.value.data, ...recorte[i] } : null))
                .filter(Boolean);
            setSerieMensual(serie);

            // Si algún mes de la serie falla, se avisa y se ofrece Reintentar en vez
            // de mostrar el gráfico incompleto como si fuera todo lo que hay.
            const fallidos = res.filter((r) => r.status === 'rejected').length;
            setErroresCarga(fallidos > 0
                ? [`${fallidos} de los ${recorte.length} meses del gráfico`] : []);
            setSinDatos(serie.length === 0);
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        }
        setLoading(false);
    }, []);

    // ─── BI: churn + forecast (+ MRR DE HOY vía /reportes/) ──────────────
    const cargarBi = useCallback(async () => {
        setLoading(true); setError(null); setSinDatos(false); setErroresCarga([]);
        // Secciones que fallaron: se avisan con AvisoCarga + Reintentar en vez de
        // dejar el bloque vacío como si no hubiera dato (catch mudo).
        const fallos = [];
        try {
            const [churnRes, forecastRes] = await Promise.all([
                api.get('/api/v1/kpis/churn'),
                api.get('/api/v1/kpis/forecast', { params: { meses: 3 } }),
            ]);
            setChurn(churnRes.data);
            setForecast(forecastRes.data?.proyecciones || []);

            // MRR: el de HOY —`metricas_service.mrr(db, tenant, hoy)`—, el que ya
            // devuelve GET /reportes/ y que muestran el dashboard y Reportes.
            // NO sale de `monthly_kpis`: hasta af77de2 la tarjeta leía la fila del
            // último mes del data mart mensual, así que cuando esa fila no existía
            // (o el índice de períodos fallaba) la tarjeta quedaba en "— CLP"
            // aunque el MRR vivo sí se conocía (regresión reportada en PROD).
            // El ARPU se REUSA de la MISMA respuesta (ingresos netos del mes /
            // alumnos activos: la definición que muestra Reportes.jsx).
            const rRep = tenant_id
                ? await api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`).catch(() => null)
                : null;
            if (!rRep) {
                fallos.push('el MRR y el ARPU de HOY (GET /reportes/)');
            }
            setMrrBi(rRep?.data?.mrr ?? null);
            setArpu(rRep?.data?.arpu ?? null);

            // Bloque financiero (opcional, criterio de siempre): el ticket y la vida
            // salen del endpoint propio.
            const rFin = await api.get('/api/v1/kpis/financiero').catch(() => null);
            setFinanciero(rFin?.data || null);

            // Bloques horarios (pico vs valle): opcional, mismo criterio.
            const rBlo = await api.get('/api/v1/kpis/bloques-horarios')
                .catch(() => null);
            setBloques(rBlo?.data || null);

            // Estacionalidad (índice por mes del año): NO es opcional en silencio.
            // Es la tarjeta que responde "¿cuáles son mis meses fuertes?": si la
            // lectura falla, se avisa con AvisoCarga + Reintentar en vez de dejar la
            // tarjeta vacía sin explicación.
            const rEst = await api.get('/api/v1/kpis/estacionalidad')
                .catch(() => null);
            if (!rEst) {
                fallos.push('la estacionalidad (GET /kpis/estacionalidad)');
            }
            setEstacionalidad(rEst?.data || null);

            // Cohortes de retención: opcional, mismo criterio.
            const rCoh = await api.get('/api/v1/kpis/cohortes')
                .catch(() => null);
            setCohortes(rCoh?.data || null);

            setErroresCarga(fallos);
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        }
        setLoading(false);
    }, [tenant_id]);

    useEffect(() => {
        if (activeTab === 'diario') cargarDiario();
        else if (activeTab === 'mensual') cargarMensual();
        else cargarBi();
    }, [activeTab, cargarDiario, cargarMensual, cargarBi]);

    const dia = serieDiaria.length ? serieDiaria[serieDiaria.length - 1] : null;
    // El mes que se muestra es el ELEGIDO en el selector (no simplemente el último de
    // la serie: el gráfico se recorta hasta el mes elegido, así que coinciden, pero
    // si un mes fallara la serie no mandaría sobre la selección del usuario).
    const mes = (mesSel && serieMensual.find((p) => p.year === mesSel.year && p.month === mesSel.month))
        || (serieMensual.length ? serieMensual[serieMensual.length - 1] : null);
    // "parcial" = el mes elegido es el mes EN CURSO (lo dice el backend, calendario
    // chileno): sus números son de un mes a medias.
    const mesParcial = !!(mes && mes.parcial);
    const mesCerradoConDatos = periodos.filter((p) => !p.parcial).slice(-1)[0] || null;
    // Botón (no texto suelto) para volver al último mes cerrado: es el estado por
    // defecto de la pestaña, y desde otro mes se llega en un click.
    const volverAlCerrado = mesCerradoConDatos && mesSel
        && (mesCerradoConDatos.year !== mesSel.year || mesCerradoConDatos.month !== mesSel.month)
        ? mesCerradoConDatos : null;

    // Selector de mes: SOLO los meses que existen en `monthly_kpis` (el backend los
    // manda del más viejo al más nuevo; acá se muestran del más nuevo al más viejo).
    // El mes EN CURSO aparece únicamente si ya tiene fila, rotulado "parcial"; si no,
    // no es una opción y se explica por qué (`notaMesEnCurso`).
    const selectorMes = (
        <div className="flex flex-wrap items-center gap-3">
            <label htmlFor="mes-mensual" className="text-sm text-gray-400">Mes:</label>
            <select
                id="mes-mensual"
                data-testid="selector-mes-mensual"
                value={mesSel ? `${mesSel.year}-${String(mesSel.month).padStart(2, '0')}` : ''}
                onChange={(e) => {
                    const [y, m] = e.target.value.split('-').map(Number);
                    cargarMensual({ year: y, month: m });
                }}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-orange-500"
            >
                {[...periodos].reverse().map((p) => (
                    <option
                        key={`${p.year}-${p.month}`}
                        value={`${p.year}-${String(p.month).padStart(2, '0')}`}
                    >
                        {MESES[p.month - 1]} {p.year}{p.parcial ? ' · parcial' : ''}
                    </option>
                ))}
            </select>
            {mesParcial && (
                <span
                    data-testid="badge-mes-parcial"
                    title="El mes todavía no cerró: los números son de un mes a medias."
                    className="rounded-full bg-amber-900/40 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-amber-300"
                >
                    parcial
                </span>
            )}
            {volverAlCerrado && (
                <button
                    type="button"
                    data-testid="ir-ultimo-mes-cerrado"
                    onClick={() => cargarMensual(volverAlCerrado)}
                    className="text-xs text-orange-400 underline transition-colors hover:text-orange-300"
                >
                    Ir al último mes cerrado ({MESES[volverAlCerrado.month - 1]} {volverAlCerrado.year})
                </button>
            )}
        </div>
    );

    // Por qué el mes en curso no está en el selector (no tiene fila todavía).
    const notaMesEnCurso = mesActual && !mesActual.tiene_fila ? (
        <p data-testid="nota-mes-en-curso" className="text-[11px] text-zinc-500">
            {MESES[mesActual.month - 1]} {mesActual.year} está en curso: sus KPIs se
            publican al cierre del mes (por eso el selector arranca en el último mes cerrado).
        </p>
    ) : null;

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

    // Función (no valor) a propósito: `forecastDetalle` se declara más abajo,
    // así el cuerpo se evalúa recién al renderizar y no en la declaración
    // (evita el ReferenceError de zona muerta temporal).
    const tablaPronostico = () => (
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

    // ─── Estacionalidad: derivados del índice por mes (ene..dic) ────────────
    // El mes en curso NO entra al cálculo (lo excluye el backend: es un mes a
    // medias) y un índice `null` significa "ese mes del año no tiene dato": no se
    // dibuja ni se cuenta como 0.
    const filasEstacionalidad = estacionalidad?.filas || [];
    const conIndice = filasEstacionalidad.filter((f) => f.indice_ingresos !== null);
    const mesFuerte = conIndice.length
        ? conIndice.reduce((a, b) => (b.indice_ingresos > a.indice_ingresos ? b : a))
        : null;
    const mesDebil = conIndice.length
        ? conIndice.reduce((a, b) => (b.indice_ingresos < a.indice_ingresos ? b : a))
        : null;
    // La serie de alumnos se dibuja SÓLO si el backend la declara disponible: hoy
    // `monthly_kpis.alumnos_activos_inicio` está en 0 en todos los meses cerrados y
    // una línea plana en 0 PARECERÍA un dato (el backend manda el motivo).
    const alumnosDisponible = !!estacionalidad?.alumnos_activos?.disponible;
    // Menos de 12 meses cerrados = todavía no se puede hablar de estacionalidad.
    const avisoInsuficiente = !!estacionalidad && !estacionalidad.suficiente;
    const notaEstacionalidad = estacionalidad?.nota_historia || '';

    const chartEstacionalidad = (
        <LineChart data={filasEstacionalidad}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
            <XAxis dataKey="label" stroke="#a1a1aa" fontSize={11} />
            <YAxis stroke="#a1a1aa" fontSize={11} tickFormatter={(v) => `${v}×`} />
            <Tooltip {...TOOLTIP_STYLE} formatter={(v) => fmtIndice(v)} />
            {/* 1,00× = promedio del período: la referencia deja ver de un golpe qué
                meses están arriba (fuertes) y cuáles abajo (flojos). */}
            <ReferenceLine y={1} stroke="#71717a" strokeDasharray="4 4" />
            <Line type="monotone" dataKey="indice_ingresos" name="Ingresos"
                stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} />
            {alumnosDisponible && (
                <Line type="monotone" dataKey="indice_alumnos" name="Alumnos activos"
                    stroke="#38bdf8" strokeWidth={2} dot={{ r: 3 }} />
            )}
        </LineChart>
    );

    const tablaEstacionalidad = (
        <DataTable
            columns={[
                { key: 'label', label: 'Mes' },
                {
                    key: 'ingresos', label: 'Ingresos del mes (CLP)',
                    render: (v) => (v === null ? 'sin datos' : fmtCLP(v)),
                },
                { key: 'indice_ingresos', label: 'Índice ingresos', render: (v) => fmtIndice(v) },
                {
                    key: 'alumnos_activos', label: 'Alumnos activos',
                    render: (v) => (v === null ? 'sin datos' : v),
                },
                { key: 'indice_alumnos', label: 'Índice alumnos', render: (v) => fmtIndice(v) },
            ]}
            data={filasEstacionalidad}
        />
    );

    const explicacionEstacionalidad = (
        <>
            El <span className="text-zinc-100">índice estacional</span> compara cada mes del año
            contra el promedio del período: <span className="text-zinc-100">1,00×</span> es un mes
            igual al promedio, más de 1,00× un mes fuerte y menos de 1,00× un mes flojo. Se calcula
            {' '}<em>valor del mes ÷ promedio de los meses</em> con los meses ya cerrados (los
            ingresos netos del mes, en CLP, y los alumnos activos al inicio del mes). El mes en
            curso queda afuera porque todavía no cerró: sus números son parciales.
            {mesFuerte && mesDebil && (
                <> En este perfil el mes más fuerte es
                    {' '}<span className="text-zinc-100">{mesFuerte.label}</span>
                    {' '}({fmtIndice(mesFuerte.indice_ingresos)}) y el más flojo
                    {' '}<span className="text-zinc-100">{mesDebil.label}</span>
                    {' '}({fmtIndice(mesDebil.indice_ingresos)}).</>
            )}
            {' '}Cómo se usa: para planificar campañas y dotación. El mes flojo es el que hay que
            llenar (ahí va la campaña de captación y las promos) y el fuerte es el que hay que
            aguantar (cupos, horarios extra y profes). Comparar el mismo mes entre años avisa si el
            perfil se está moviendo.
            {estacionalidad?.suficiente && notaEstacionalidad ? ` ${notaEstacionalidad}` : ''}
            {!alumnosDisponible && estacionalidad?.alumnos_activos?.motivo
                ? ` Alumnos activos: ${estacionalidad.alumnos_activos.motivo}` : ''}
        </>
    );

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
                        <p className="text-gray-300 font-medium">
                            {activeTab === 'mensual'
                                ? 'Todavía no hay KPIs mensuales cerrados.'
                                : 'Sin datos para el período.'}
                        </p>
                        <p className="text-sm text-gray-500 mt-2">
                            {activeTab === 'mensual'
                                ? 'Los KPIs mensuales se publican al cierre de cada mes. Si ya hay meses con datos cargados, se completan con el backfill: POST /api/v1/kpis/populate/monthly?backfill=12'
                                : 'Los datos se están generando: intenta de nuevo en unos minutos.'}
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
                    <div className="space-y-6" data-testid="tab-mensual">
                        <AvisoCarga
                            secciones={erroresCarga}
                            variante="oscura"
                            onReintentar={() => cargarMensual(mesSel)}
                        />
                        <div className="space-y-2">
                            {selectorMes}
                            {notaMesEnCurso}
                            <p className="text-xs text-gray-500">
                                Mostrando <span className="text-gray-300">{MESES[mes.month - 1]} {mes.year}</span>
                                {mesParcial ? ' (mes en curso: números parciales)' : ' (mes cerrado)'}
                                {mesCerradoConDatos && !volverAlCerrado
                                    ? ' · es el último mes cerrado con datos' : ''}
                            </p>
                        </div>

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
                                <ChartCard title={`Últimos ${serieMensual.length} meses con datos · Ingresos recurrentes e ingresos totales (CLP)`}>
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
                    <div className="space-y-6" data-testid="tab-bi">
                        {/* Si GET /reportes/ falla, el MRR de HOY no tiene de dónde
                            salir: se avisa con Reintentar en vez de dejar la tarjeta
                            en "— CLP" como si el número no existiera. */}
                        <AvisoCarga
                            secciones={erroresCarga}
                            variante="oscura"
                            onReintentar={cargarBi}
                        />
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

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            {/* El MRR de esta tarjeta es el de HOY (precio de lista de los
                                planes vigentes): no espera a que cierre el mes ni depende
                                del data mart mensual. El caption lo dice para que nadie lo
                                lea como "el del último mes cerrado". */}
                            <div>
                                <KpiCard label="Ingresos Recurrentes Mensuales" value={mrrBi === null ? null : Number(mrrBi)} unit="CLP" icon={Banknote} color="border-emerald-500" />
                                <p className="mt-1 text-[11px] text-zinc-500">
                                    Vigente hoy · precio de lista de los planes activos
                                </p>
                            </div>
                            <KpiCard
                                label="Proyección mes 1"
                                value={forecast.length ? Number(forecast[0].ingresos_predicho) : null}
                                unit="CLP"
                                icon={TrendingUp}
                                color="border-orange-500"
                            />
                            {/* Estacionalidad (índice por mes del año): tercer bloque de la
                                fila. Se clickea (o se abre con Enter/Espacio) y abre el
                                DetalleModal, el MISMO patrón de los otros gráficos del BI. */}
                            <div
                                role="button"
                                tabIndex={0}
                                onClick={() => setDetalle('estacionalidad')}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        setDetalle('estacionalidad');
                                    }
                                }}
                                title="Ver el detalle ampliado"
                                data-testid="card-estacionalidad"
                                className="bg-zinc-900 rounded-lg shadow p-6 border-l-4 border-sky-500 cursor-zoom-in"
                            >
                                <div className="flex justify-between items-start">
                                    <div>
                                        <p className="text-sm text-gray-400 uppercase tracking-wide">
                                            Estacionalidad
                                        </p>
                                        <p className="text-3xl font-bold text-white mt-2"
                                            data-testid="estacionalidad-mes-fuerte">
                                            {mesFuerte ? mesFuerte.label : '—'}
                                            {mesFuerte && (
                                                <span className="text-lg ml-2 text-gray-500"
                                                    title="1,00× = mes promedio">
                                                    {fmtIndice(mesFuerte.indice_ingresos)}
                                                </span>
                                            )}
                                        </p>
                                    </div>
                                    <CalendarDays className="w-8 h-8 text-gray-600" />
                                </div>
                                <p className="mt-1 text-[11px] text-zinc-500">
                                    {avisoInsuficiente
                                        ? `${estacionalidad.meses_con_datos} de ${estacionalidad.minimo_meses} meses con datos`
                                        : (mesFuerte && mesDebil
                                            ? `Mes más fuerte vs ${mesDebil.label} (${fmtIndice(mesDebil.indice_ingresos)})`
                                            : 'Todavía sin meses cerrados con datos')}
                                    {' · '}1,00× = mes promedio
                                </p>
                                <div className="mt-3 h-16">
                                    {filasEstacionalidad.length > 0 && (
                                        <ResponsiveContainer width="100%" height="100%">
                                            {chartEstacionalidad}
                                        </ResponsiveContainer>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Aviso de honestidad: con menos de 12 meses cerrados no se publica
                            como "estacionalidad" (un año es el mínimo para un perfil). */}
                        {avisoInsuficiente && (
                            <div
                                data-testid="aviso-estacionalidad"
                                role="status"
                                className="rounded-xl border border-amber-600 bg-amber-900/30 px-4 py-3 text-sm text-amber-200"
                            >
                                ⚠️ Aún no hay suficiente historia para calcular la estacionalidad:
                                se necesitan {estacionalidad.minimo_meses} meses y hay{' '}
                                {estacionalidad.meses_con_datos}. El gráfico se completa
                                automáticamente a medida que cierran los meses.
                            </div>
                        )}

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
                                {' '}El ARPU es el de Reportes (ingresos netos del mes ÷ alumnos
                                activos), para que no haya dos versiones del mismo número. Vida
                                promedio: {financiero?.vida?.formula ?? '—'}.
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
                        {tablaPronostico()}

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
                            Proyección de ingresos del box mes a mes, calculada por el modelo de
                            pronóstico sobre los ingresos históricos netos (ingresos − egresos)
                            agrupados por mes. Cada punto es el ingreso proyectado de ese mes; la tabla
                            de abajo muestra además la variación % contra el mes anterior y los alumnos
                            proyectados cuando el modelo los estima. Si un mes no tiene mes anterior
                            comparable, la variación aparece como guion en vez de un 0% inventado.
                        </>
                    )}
                >
                    <ChartCard title="Pronóstico de ingresos (CLP)" height="h-96">
                        {chartForecast}
                    </ChartCard>
                    <div className="mt-4">{tablaPronostico()}</div>
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
                            Mide cuántas clases se dictan en cada franja horaria (la oferta) y el cupo
                            promedio ofrecido. La barra naranja (asistencias por clase) es el promedio
                            de asistentes confirmados por clase del bloque, que es el dato que permite
                            comparar pico vs valle. Sirve para decidir dónde falta oferta y dónde sobra
                            cupo. Hoy la asistencia por clase puede verse en 0 porque las asistencias
                            todavía no quedan vinculadas a su clase: el dato siempre confiable de este
                            gráfico es la oferta (clases y cupo).
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
                            Cohorte = el mes en que el alumno se dio de alta. "Activo a los N días"
                            significa que tiene al menos una asistencia desde su alta hasta N días
                            después: es la señal de retención disponible hoy, porque las asistencias
                            todavía no quedan asociadas a su clase. Solo se promedian los alumnos que ya
                            cumplieron ese plazo; si la cohorte es más nueva, la celda muestra n/d en vez
                            de un 0% inventado.
                        </>
                    )}
                >
                    {tablaCohortes}
                </DetalleModal>
            )}

            {/* ── Detalle ampliado: estacionalidad (índice por mes del año) ──
                Mismo DetalleModal que el resto del BI: gráfico ampliado, tabla por mes y
                la explicación en lenguaje simple (meses fuertes/flojos y cómo se usa para
                planificar campañas). */}
            {detalle === 'estacionalidad' && (
                <DetalleModal
                    titulo="Estacionalidad del box (índice por mes del año)"
                    subtitulo={estacionalidad
                        ? `Cada mes ÷ promedio del período (1,00× = mes promedio) · ${estacionalidad.meses_con_datos} meses con datos`
                        : 'Todavía sin datos'}
                    onCerrar={() => setDetalle(null)}
                    explicacion={explicacionEstacionalidad}
                >
                    {avisoInsuficiente && (
                        <div
                            data-testid="aviso-estacionalidad-modal"
                            className="mb-4 rounded-lg border border-amber-600 bg-amber-900/30 px-4 py-3 text-sm text-amber-200"
                        >
                            ⚠️ Aún no hay suficiente historia para calcular la estacionalidad:
                            se necesitan {estacionalidad.minimo_meses} meses y hay{' '}
                            {estacionalidad.meses_con_datos}. El gráfico se completa
                            automáticamente a medida que cierran los meses.
                        </div>
                    )}

                    {filasEstacionalidad.length > 0 ? (
                        <>
                            <ChartCard
                                title="Índice por mes del año (1,00× = mes promedio)"
                                height="h-96"
                            >
                                {chartEstacionalidad}
                            </ChartCard>
                            <div className="mt-4 space-y-2">
                                {tablaEstacionalidad}
                                <p className="text-[11px] leading-relaxed text-zinc-500">
                                    Cada mes se compara con el promedio del período:
                                    {' '}{estacionalidad.ingresos.observaciones} meses cerrados de
                                    ingresos
                                    {alumnosDisponible
                                        ? ` y ${estacionalidad.alumnos_activos.observaciones} de alumnos activos.`
                                        : '. Alumnos activos: todavía sin serie histórica.'}
                                </p>
                            </div>
                        </>
                    ) : (
                        <div className="rounded-lg border border-zinc-700 bg-zinc-800/40 p-4 text-sm leading-relaxed text-zinc-300">
                            Todavía no hay meses cerrados con datos. Los KPIs mensuales se publican al
                            cierre de cada mes; el gráfico se completa solo a medida que cierran los
                            meses.
                        </div>
                    )}
                </DetalleModal>
            )}
        </Layout>
    );
};

export default AdminKpis;





