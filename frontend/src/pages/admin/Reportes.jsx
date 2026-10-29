import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import {
    SIN_DATOS, useCrearTransaccionFinanzas, useDescargarReporteVentas, useStatsDashboard,
    useTransaccionesFinanzas,
} from '../../hooks/queries';
import { DetalleModal } from '../../components/kpis/DetalleModal';
import { hoyChileStr } from '../../utils/fecha';
// Filtros del detalle "Membresías del mes": las MISMAS reglas puras del modal del
// Dashboard (`utils/membresiasMes`). Sin esto, el mismo listado se filtraba distinto
// en cada pantalla (o no se filtraba acá, que es lo que pasaba: 263 filas seguidas).
import {
    FILTRO_PLAN_SIN_PRUEBA, FILTRO_PLAN_TODOS, filtrarMembresias, planesDe,
} from '../../utils/membresiasMes';

// Tooltip personalizado con Tailwind
const CustomTooltip = ({ active, payload, label, formatter }) => {
    if (!active || !payload || !payload.length) return null;
    return (
        <div className="bg-gray-900 text-white px-4 py-3 rounded-lg shadow-xl border border-gray-700">
            <p className="text-sm font-medium text-gray-300 mb-1">{label}</p>
            {payload.map((entry, index) => (
                <p key={index} className="text-base font-bold" style={{ color: entry.color }}>
                    {formatter ? formatter(entry.value) : entry.value}
                </p>
            ))}
        </div>
    );
};

// Formato compacto de montos: $4.5M en vez de $4.500.000
const formatCompact = (value) => {
    if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `$${(value / 1000).toFixed(0)}K`;
    return `$${value}`;
};

const formatCLP = (value) => `$${value.toLocaleString('es-CL')}`;

// Encabezado ordenable del "Detalle de Movimientos". El click va en un <button>
// (no en el <th>) para que se pueda tocar/teclear sin perder la semántica de la
// tabla, y `aria-sort` en el <th> anuncia el orden actual al lector de pantalla.
const ThOrden = ({ campo, etiqueta, orden, onOrdenar }) => {
    const activo = orden.campo === campo;
    return (
        <th scope="col" className="px-6 py-3 text-left text-sm font-medium"
            aria-sort={activo ? (orden.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
            <button type="button" onClick={() => onOrdenar(campo)}
                className="inline-flex items-center gap-1 hover:text-blue-200 transition-colors"
                title={`Ordenar por ${etiqueta.toLowerCase()}`}>
                {etiqueta}
                <span aria-hidden="true">{activo ? (orden.dir === 'asc' ? '▲' : '▼') : '↕'}</span>
            </button>
        </th>
    );
};

// Anclas internas del reporte: las tarjetas de KPI llevan al detalle que
// respalda su número. Se usan tanto al entrar con `?seccion=` (Dashboard) como
// al hacer clic en una tarjeta de esta misma pantalla.
const SECCION_IDS = {
    bazar: 'seccion-bazar',
    ranking: 'ranking-planes',
    membresias: 'membresias-mes',
    movimientos: 'detalle-movimientos',
    disciplinas: 'resumen-disciplinas',
    coaches: 'clases-coach',
    vencidos: 'planes-vencidos',
};

const Reportes = () => {
    const { tenant_id } = useAuth();
    const navigate = useNavigate();
    // Mismo fallback `|| 1` que ya usaba esta pantalla en el reporte, el alta de un
    // movimiento y el Excel: se conserva tal cual (no se cambia la petición que sale).
    const tenantEfectivo = tenant_id || 1;

    // El reporte lo trae el hook COMPARTIDO con el Dashboard (`GET /reportes/?tenant_id=`):
    // la clave es la misma (`['reportes', tenantId]`), así que entrar acá después del panel
    // pinta al instante y no vuelve a pedir lo mismo.
    const { data: reporteData, isPending: loadingReporte } = useStatsDashboard(tenantEfectivo);
    const reportData = reporteData ?? null;
    const loading = loadingReporte;
    // El Dashboard enlaza acá con ?seccion=bazar|ranking|...: al entrar se baja
    // hasta la tarjeta/sección del detalle en vez de dejar al admin arriba.
    const [searchParams, setSearchParams] = useSearchParams();
    const seccionActiva = searchParams.get('seccion');
    const seccionId = SECCION_IDS[seccionActiva] || null;
    useEffect(() => {
        if (!seccionId || loading) return undefined;
        const t = setTimeout(() => {
            document.getElementById(seccionId)
                ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 150);
        return () => clearTimeout(t);
    }, [seccionId, loading]);

    // Misma pantalla: actualizar el query param y bajar al detalle en el acto.
    const irASeccion = (seccion) => {
        setSearchParams({ seccion });
        const id = SECCION_IDS[seccion];
        if (id) {
            setTimeout(() => document.getElementById(id)
                ?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
        }
    };
    // Gráfico histórico abierto en el modal de detalle (null = ninguno).
    const [detalleGrafico, setDetalleGrafico] = useState(null);
    const [showMovModal, setShowMovModal] = useState(false);
    const [movForm, setMovForm] = useState({ tipo: 'egreso', categoria: '', monto: '', descripcion: '', fecha: hoyChileStr(), tenant_id: tenant_id });
    // Detalle de movimientos: lista propia (hoy no la comparte otra pantalla) que se
    // invalida al registrar un movimiento. `SIN_DATOS` es el array vacío ESTABLE que
    // exporta el módulo de consultas (un `|| []` nuevo en cada render rompe los memo).
    const { data: transacciones, isPending: loadingMovs } = useTransaccionesFinanzas();
    const movimientosList = transacciones ?? SIN_DATOS;
    // ── Detalle de movimientos: filtro y orden EN MEMORIA ────────────────────
    // La lista ya viene completa del hook (mes en curso): acá sólo se recorta y se
    // ordena para leerla. No hay endpoint nuevo ni otra petición.
    const [filtroTipo, setFiltroTipo] = useState('todos');            // todos|ingreso|egreso
    const [filtroCategoria, setFiltroCategoria] = useState('todas');  // todas|<categoría>
    const [ordenMovs, setOrdenMovs] = useState({ campo: 'fecha', dir: 'desc' });
    // Las categorías salen de las filas cargadas (no de una lista fija): si mañana
    // aparece un gasto con otra categoría, se puede filtrar sin tocar la pantalla.
    const categoriasMovs = useMemo(() => (
        [...new Set(movimientosList.map((m) => m.categoria).filter(Boolean))]
            .sort((a, b) => String(a).localeCompare(String(b), 'es'))
    ), [movimientosList]);
    const movimientosVisibles = useMemo(() => {
        const filas = movimientosList.filter((m) => (
            (filtroTipo === 'todos' || m.tipo === filtroTipo)
            && (filtroCategoria === 'todas' || m.categoria === filtroCategoria)
        ));
        const signo = ordenMovs.dir === 'asc' ? 1 : -1;
        // Copia antes de ordenar: `movimientosList` puede ser el array ESTABLE de la
        // caché (`SIN_DATOS` o el de la query) y no se debe mutar.
        return [...filas].sort((a, b) => {
            if (ordenMovs.campo === 'monto') {
                return ((Number(a.monto) || 0) - (Number(b.monto) || 0)) * signo;
            }
            // `fecha` llega como 'YYYY-MM-DD' (`str()` de la columna DATE): se compara
            // como fecha y no como texto para que un ISO completo no desordene.
            const fa = Date.parse(a.fecha) || 0;
            const fb = Date.parse(b.fecha) || 0;
            return (fa - fb) * signo;
        });
    }, [movimientosList, filtroTipo, filtroCategoria, ordenMovs]);
    const hayFiltroMovs = filtroTipo !== 'todos' || filtroCategoria !== 'todas';
    const alternarOrdenMovs = (campo) => setOrdenMovs((o) => (
        o.campo === campo
            ? { campo, dir: o.dir === 'asc' ? 'desc' : 'asc' }
            : { campo, dir: campo === 'fecha' ? 'desc' : 'asc' }
    ));
    const limpiarFiltrosMovs = () => {
        setFiltroTipo('todos');
        setFiltroCategoria('todas');
    };
    const guardarMovimiento = useCrearTransaccionFinanzas();
    const savingMov = guardarMovimiento.isPending;
    const descargarVentas = useDescargarReporteVentas();

    // Datos de los últimos 6 meses para los gráficos (desde BD real)
    const membresiaData = (reportData?.historicoMembresias || []).map(item => ({
        mes: item.mes,
        membresias: item.membresias,
    }));

    const ingresosData = (reportData?.historicoIngresos || []).map(item => ({
        mes: item.mes,
        ingresos: item.ingresos,
    }));

    // Ranking de planes del mes: lo entrega `/reportes/` ya agrupado y con el
    // MISMO criterio de compra que Convertidos (plan con precio > 0), así no
    // cuenta pruebas ni regalos. No se recalcula en el cliente.
    const rankingPlanes = reportData?.planesMasVendidos || [];
    // `null` con cero altas comerciales: la tarjeta muestra "sin altas", no 0.
    const planTop = rankingPlanes[0] || null;
    const totalAltasRanking = rankingPlanes.reduce((acc, p) => acc + (p.altas || 0), 0);
    // Detalle de la tarjeta "Planes Vencidos (Mes)" (mismas filas del COUNT).
    const planesVencidos = reportData?.planesVencidosMes || [];

    // ── Membresías del mes: filtro y orden EN MEMORIA ────────────────────────
    // `/reportes/` ya manda TODAS las suscripciones del mes (`suscripcionesMes`, 263
    // en un mes normal), así que acá se recorta y se ordena para leerlas: no hay
    // endpoint nuevo ni otra petición. La lista NO se copia con `|| []` (crearía un
    // array nuevo en cada render y rompería los `useMemo`): los auxiliares aceptan
    // `undefined` mientras el reporte carga.
    const suscripcionesMes = reportData?.suscripcionesMes;
    const [busquedaMembresias, setBusquedaMembresias] = useState('');
    const [planMembresias, setPlanMembresias] = useState(FILTRO_PLAN_TODOS);
    const [ordenMembresias, setOrdenMembresias] = useState('reciente');
    const planesMembresias = useMemo(() => planesDe(suscripcionesMes), [suscripcionesMes]);
    const membresiasVisibles = useMemo(() => filtrarMembresias(suscripcionesMes, {
        busqueda: busquedaMembresias, plan: planMembresias, orden: ordenMembresias,
    }), [suscripcionesMes, busquedaMembresias, planMembresias, ordenMembresias]);
    const totalMembresiasMes = (suscripcionesMes || []).length;
    const limpiarFiltrosMembresias = () => {
        setBusquedaMembresias('');
        setPlanMembresias(FILTRO_PLAN_TODOS);
    };

    // Degradados para AreaChart
    const degradeMembresias = (
        <defs>
            <linearGradient id="colorMembresias" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#FF6B35" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#FF6B35" stopOpacity={0} />
            </linearGradient>
        </defs>
    );

    const degradeIngresos = (
        <defs>
            <linearGradient id="colorIngresos" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#1F4E78" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#1F4E78" stopOpacity={0} />
            </linearGradient>
        </defs>
    );

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4"></div>
                        <p className="text-zinc-400">Cargando reportes...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    // Gráfico histórico: misma definición para la tarjeta y el modal.
    const chartMembresias = (alto) => (
<ResponsiveContainer width="100%" height={alto}>
                            <AreaChart data={membresiaData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                                <defs>{degradeMembresias}</defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                                <XAxis dataKey="mes" tick={{ fill: '#6b7280', fontSize: 12 }} />
                                <YAxis tick={{ fill: '#6b7280', fontSize: 12 }} />
                                <Tooltip content={<CustomTooltip formatter={(v) => `${v} membresías`} />} />
                                <Area
                                    type="monotone"
                                    dataKey="membresias"
                                    stroke="#FF6B35"
                                    strokeWidth={3}
                                    fill="url(#colorMembresias)"
                                    dot={{ fill: '#FF6B35', strokeWidth: 2, r: 4 }}
                                    activeDot={{ r: 6, fill: '#FF6B35' }}
                                />
                            </AreaChart>
                        </ResponsiveContainer>
    );

    const chartIngresos = (alto) => (
<ResponsiveContainer width="100%" height={alto}>
                            <AreaChart data={ingresosData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                                <defs>{degradeIngresos}</defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                                <XAxis dataKey="mes" tick={{ fill: '#6b7280', fontSize: 12 }} />
                                <YAxis
                                    tick={{ fill: '#6b7280', fontSize: 12 }}
                                    tickFormatter={(v) => formatCompact(v)}
                                />
                                <Tooltip content={<CustomTooltip formatter={(v) => formatCLP(v)} />} />
                                <Area
                                    type="monotone"
                                    dataKey="ingresos"
                                    stroke="#1F4E78"
                                    strokeWidth={3}
                                    fill="url(#colorIngresos)"
                                    dot={{ fill: '#1F4E78', strokeWidth: 2, r: 4 }}
                                    activeDot={{ r: 6, fill: '#1F4E78' }}
                                />
                            </AreaChart>
                        </ResponsiveContainer>
    );

    return (
        <Layout>
            <div className="space-y-6">
                {/* Título */}
                <div>
                    <h1 className="text-3xl font-bold text-zinc-100">Reportes & Analytics</h1>
                    <p className="text-zinc-400 mt-1">Análisis de desempeño y estadísticas de tu box</p>
                </div>

                {/* KPIs principales */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <button type="button"
                        onClick={() => navigate('/admin/alumnos?estado=activo')}
                        title="Ver el padrón filtrado por alumnos activos"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-blue-500 transition hover:shadow-md hover:border-blue-400 cursor-pointer">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-zinc-400 text-sm font-medium">Alumnos Activos</p>
                                <p className="text-3xl font-bold text-zinc-100 mt-2">{reportData?.alumnosActivos || 0}</p>
                                {/* Mismo criterio que el endpoint: alumno con suscripcion vigente hoy. */}
                                <p className="text-xs text-zinc-400 mt-2">Con suscripción vigente — Clic para ver</p>
                            </div>
                            <span className="text-4xl">👥</span>
                        </div>
                    </button>

                    <button type="button"
                        onClick={() => irASeccion('movimientos')}
                        title="Ver el detalle de movimientos del mes"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-green-500 transition hover:shadow-md hover:border-green-400 cursor-pointer">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-zinc-400 text-sm font-medium">Ingreso Neto Mensual</p>
                                <p className="text-3xl font-bold text-zinc-100 mt-2">
                                    {formatCompact(reportData?.ingresoMensual || 0)}
                                </p>
                                <p className="text-xs text-zinc-400 mt-2">Ingresos - Egresos del mes</p>
                                {/* MoM de INGRESOS (antes estaba mal ubicado bajo Alumnos Activos). */}
                                {reportData?.crecimientoMensual === null ? (
                                    <p className="text-xs text-zinc-500 mt-2"
                                        title="Sin mes anterior comparable: el ingreso neto del mes pasado fue <= 0 (sin movimientos o mas egresos que ingresos).">
                                        s/d vs mes anterior (sin base comparable)
                                    </p>
                                ) : (
                                    <p className={`text-xs mt-2 ${reportData?.crecimientoMensual > 0 ? 'text-green-600' : reportData?.crecimientoMensual < 0 ? 'text-red-500' : 'text-zinc-400'}`}
                                        title={`Ingreso neto del mes anterior: ${formatCLP(reportData?.ingresoMesAnterior ?? 0)}`}>
                                        {reportData?.crecimientoMensual > 0 ? '↑' : reportData?.crecimientoMensual < 0 ? '↓' : '='}{' '}
                                        {Math.abs(reportData?.crecimientoMensual ?? 0)}% vs mes anterior
                                    </p>
                                )}
                                <p className="text-[11px] text-zinc-500 mt-2">Clic para ver movimientos</p>
                            </div>
                            <span className="text-4xl">💰</span>
                        </div>
                    </button>

                    <button type="button"
                        onClick={() => irASeccion('disciplinas')}
                        title="Ver ocupación y asistencia por disciplina"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-orange-500 transition hover:shadow-md hover:border-orange-400 cursor-pointer">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-zinc-400 text-sm font-medium"
                                    title="Ocupacion: clases.asistentes_confirmados / clases.cupo_maximo (lugares reservados sobre cupo ofrecido). NO mide asistencia real. Puede verse 0% porque las asistencias todavia no estan vinculadas a su clase (asistencias.clase_id es NULL en toda la base).">Ocupación promedio</p>
                                <p className="text-3xl font-bold text-zinc-100 mt-2">{reportData?.asistenciaPromedio || 0}%</p>
                                <p className="text-xs text-zinc-400 mt-2"
                                    title="Ocupacion: clases.asistentes_confirmados / clases.cupo_maximo (lugares reservados sobre cupo ofrecido). NO mide asistencia real. Puede verse 0% porque las asistencias todavia no estan vinculadas a su clase (asistencias.clase_id es NULL en toda la base).">Ocupación (reservas vs cupo), no asistencia real</p>
                                <p className="text-[11px] text-zinc-500 mt-2">
                                    {reportData?.reservasSinCupo > 0
                                        ? `+ ${reportData.reservasSinCupo} reservas en salas sin cupo (Musculación / Open Box)`
                                        : 'Clic para ver por disciplina'}
                                </p>
                            </div>
                            <span className="text-4xl">📊</span>
                        </div>
                    </button>

                    <button type="button"
                        onClick={() => irASeccion('coaches')}
                        title="Ver clases impartidas por coach"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-purple-500 transition hover:shadow-md hover:border-purple-400 cursor-pointer">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-zinc-400 text-sm font-medium">Clases Impartidas</p>
                                <p className="text-3xl font-bold text-zinc-100 mt-2">{reportData?.clasesImpartidas || 0}</p>
                                <p className="text-xs text-zinc-400 mt-2">Este mes — Clic para ver por coach</p>
                            </div>
                            <span className="text-4xl">📅</span>
                        </div>
                    </button>

                    <button type="button"
                        onClick={() => irASeccion('ranking')}
                        title="Ver el ranking de planes del mes"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-indigo-500 transition hover:shadow-md hover:border-indigo-400 cursor-pointer">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-zinc-400 text-sm font-medium">Plan más vendido (Mes)</p>
                                {planTop ? (
                                    <>
                                        <p className="text-3xl font-bold text-zinc-100 mt-2">{planTop.altas}</p>
                                        <p className="text-xs text-zinc-400 mt-2 truncate max-w-[180px]"
                                            title={planTop.plan_nombre}>
                                            {planTop.plan_nombre} · {planTop.porcentaje}% de las altas
                                        </p>
                                    </>
                                ) : (
                                    <>
                                        <p className="text-2xl font-bold text-zinc-500 mt-2">Sin altas</p>
                                        <p className="text-xs text-zinc-400 mt-2">No hay ventas de planes este mes</p>
                                    </>
                                )}
                                <p className="text-[11px] text-zinc-500 mt-2">Clic para ver el ranking</p>
                            </div>
                            <span className="text-4xl">🏆</span>
                        </div>
                    </button>
                </div>

                {/* Gráficos con Recharts */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Crecimiento de Membresías - AreaChart con degradado */}
                    <div className="bg-zinc-900 rounded-lg shadow p-6">
                        <div className="mb-4 flex items-start justify-between gap-3">
                        <h3 className="text-lg font-bold text-zinc-100">Crecimiento de Membresías</h3>
                        <button
                            type="button"
                            onClick={() => setDetalleGrafico('membresias')}
                            aria-label="Ampliar: Crecimiento de Membresias"
                            className="shrink-0 rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-zinc-300 transition hover:bg-zinc-700/60 hover:text-white"
                        >
                            Ampliar
                        </button>
                    </div>
                    <div className="cursor-zoom-in" onClick={() => setDetalleGrafico('membresias')}
                        title="Ver el detalle ampliado">
                        {chartMembresias(250)}
                    </div>
                    </div>

                    {/* Ingresos Mensuales - AreaChart con formato compacto */}
                    <div className="bg-zinc-900 rounded-lg shadow p-6">
                        <div className="mb-4 flex items-start justify-between gap-3">
                        <h3 className="text-lg font-bold text-zinc-100">Ingresos Mensuales</h3>
                        <button
                            type="button"
                            onClick={() => setDetalleGrafico('ingresos')}
                            aria-label="Ampliar: Ingresos Mensuales"
                            className="shrink-0 rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-zinc-300 transition hover:bg-zinc-700/60 hover:text-white"
                        >
                            Ampliar
                        </button>
                    </div>
                    <div className="cursor-zoom-in" onClick={() => setDetalleGrafico('ingresos')}
                        title="Ver el detalle ampliado">
                        {chartIngresos(250)}
                    </div>
                    </div>
                </div>

                {/* Nuevos Alumnos / Planes Vencidos / MRR / Plan más vendido */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    <button type="button"
                        onClick={() => navigate('/admin/alumnos-prueba')}
                        title="Ver los alumnos nuevos del mes y si convirtieron"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-emerald-500 transition hover:shadow-md hover:border-emerald-400 cursor-pointer">
                        <p className="text-zinc-400 text-sm font-medium">Nuevos Alumnos (Mes)</p>
                        <p className="text-3xl font-bold text-zinc-100 mt-2">{reportData?.nuevosAlumnosMes || 0}</p>
                        <p className="text-[11px] text-zinc-500 mt-2">Clic para ver el detalle</p>
                        <span className="text-4xl">✨</span>
                    </button>
                    <button type="button"
                        onClick={() => irASeccion('vencidos')}
                        title="Ver los planes vencidos de este mes"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-red-500 transition hover:shadow-md hover:border-red-400 cursor-pointer">
                        <p className="text-zinc-400 text-sm font-medium"
                            title="Suscripciones con estado=vencido cuya fecha_expiracion cayo en este mes. NO son cancelaciones explicitas: ese estado no existe en la base.">Planes Vencidos (Mes)</p>
                        <p className="text-3xl font-bold text-zinc-100 mt-2">{reportData?.cancelacionesMes || 0}</p>
                        <p className="text-[11px] text-zinc-500 mt-2">Clic para ver el detalle</p>
                        <span className="text-4xl">📉</span>
                    </button>
                    <button type="button"
                        onClick={() => navigate('/admin/planes')}
                        title="Ver el catálogo de planes y sus precios"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-purple-500 transition hover:shadow-md hover:border-purple-400 cursor-pointer">
                        <p className="text-zinc-400 text-sm font-medium">Ingresos Recurrentes Mensuales (MRR)</p>
                        <p className="text-3xl font-bold text-zinc-100 mt-2">{formatCompact(reportData?.mrr || 0)}</p>
                        <p className="text-xs text-zinc-400 mt-2"
                            title="ARPU = ingreso NETO del mes (ingresos - egresos) dividido por los alumnos activos. No es bruto: los egresos del mes lo reducen.">
                            ARPU (neto): {formatCompact(reportData?.arpu || 0)}/alumno
                        </p>
                        {/* Definición explícita: el LTV del BI reusa ESTE mismo número. */}
                        <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
                            <span className="text-zinc-400">ARPU = ingreso neto del mes ÷ alumnos activos</span>
                            {' '}(neto = ingresos − egresos), no bruto: los egresos del mes lo bajan.
                            {' '}Es el mismo ARPU que reusa el <span className="text-zinc-400">LTV de Inteligencia de Negocio</span>
                            {' '}(LTV = ARPU × vida promedio), así que un mes con muchos egresos también baja ese LTV.
                            {' '}El MRR, en cambio, es el precio de lista de los planes con suscripción activa vigente.
                        </p>
                        <p className="text-[11px] text-zinc-500 mt-2">Clic para ver los planes</p>
                    </button>
                    {/* Ventas del Bazar del mes (BRUTAS): campo `ventasBazar` de /reportes/.
                        No están dentro del MRR (que es sólo planes) ni del ingreso mensual (que es
                        caja neta de transacciones): por eso van en su propia tarjeta. */}
                    <button type="button" id="seccion-bazar"
                        onClick={() => navigate('/admin/pedidos')}
                        title="Ver los pedidos del Bazar"
                        className={`w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-teal-500 transition hover:shadow-md hover:border-teal-400 cursor-pointer${seccionActiva === 'bazar' ? ' ring-2 ring-teal-500/60' : ''}`}>
                        <p className="text-zinc-400 text-sm font-medium"
                            title="Pedidos del bazar ya cobrados (validados o entregados) del mes en curso, por la fecha del pedido. Un pedido con el comprobante sin revisar todavía no suma.">Ventas Bazar (Mes)</p>
                        <p className="text-3xl font-bold text-zinc-100 mt-2">{formatCLP(reportData?.ventasBazar || 0)}</p>
                        <p className="text-xs text-zinc-400 mt-2">
                            {reportData?.ventasBazarPedidos || 0} pedido{(reportData?.ventasBazarPedidos || 0) === 1 ? '' : 's'} cobrado{(reportData?.ventasBazarPedidos || 0) === 1 ? '' : 's'} (validados/entregados)
                        </p>
                        {/* `null` = el mes anterior no vendió nada: no hay base comparable,
                            así que no se muestra un 0% que parezca una caída. */}
                        {reportData?.ventasBazarVariacion == null ? (
                            <p className="text-xs text-zinc-500 mt-1">
                                Sin base del mes anterior ({formatCLP(reportData?.ventasBazarMesAnterior || 0)})
                            </p>
                        ) : (
                            <p className={`text-xs font-bold mt-1 ${reportData.ventasBazarVariacion > 0 ? 'text-green-500' : reportData.ventasBazarVariacion < 0 ? 'text-red-500' : 'text-zinc-500'}`}
                                title={`Mes anterior: ${formatCLP(reportData?.ventasBazarMesAnterior || 0)}`}>
                                {reportData.ventasBazarVariacion > 0 ? '↑' : reportData.ventasBazarVariacion < 0 ? '↓' : '='}{' '}
                                {Math.abs(reportData.ventasBazarVariacion)}% vs mes anterior
                            </p>
                        )}
                        <p className="text-[11px] text-zinc-500 mt-1">Clic para ver los pedidos</p>
                        <span className="text-4xl">🛒</span>
                    </button>
                    {/* Retención (antes "Churn"): se muestra la tasa que SIGUE vigente,
                        no la pérdida. Mismo criterio que la tarjeta del panel/dashboard. */}
                    <button type="button"
                        onClick={() => navigate('/admin/fidelizacion')}
                        title="Ver el panel de fidelización y alumnos en riesgo"
                        className="w-full rounded-lg bg-zinc-900 p-6 text-left shadow border-l-4 border-emerald-500 transition hover:shadow-md hover:border-emerald-400 cursor-pointer">
                        <p className="text-zinc-400 text-sm font-medium"
                            title="Retención de cohorte de los últimos 30 días: de los alumnos vigentes hace 30 días, cuántos siguen vigentes hoy. Si la base no alcanza el mínimo, no se calcula.">
                            Tasa de Retención (30 días)
                        </p>
                        {reportData?.tieneDatosRetencion ? (
                            <>
                                <p className="text-3xl font-bold text-zinc-100 mt-2">{reportData.retencion}%</p>
                                <p className="text-xs text-zinc-400 mt-2">
                                    De {reportData.alumnosActivosHace30 ?? 0} alumnos vigentes hace 30 días
                                </p>
                            </>
                        ) : (
                            <>
                                <p className="text-2xl font-bold text-zinc-500 mt-2">Datos insuficientes</p>
                                <p className="text-xs text-yellow-600 mt-2">
                                    ⚠️ Base de {reportData?.alumnosActivosHace30 ?? 0} de {reportData?.retencionBaseMinima ?? 5} alumnos con plan vigente hace 30 días
                                </p>
                            </>
                        )}
                        <p className="text-[11px] text-zinc-500 mt-2">Clic para ver Fidelización</p>
                        <span className="text-4xl">🛡️</span>
                    </button>
                </div>

                {/* Detalle de Planes Vencidos (Mes): respalda la tarjeta del mismo
                    nombre. Mismas filas que el COUNT `cancelacionesMes`. */}
                <div id="planes-vencidos"
                    className={`bg-zinc-900 rounded-lg shadow overflow-hidden${seccionActiva === 'vencidos' ? ' ring-2 ring-red-500/60' : ''}`}>
                    <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between gap-3">
                        <div>
                            <h2 className="text-lg font-bold text-zinc-100">📉 Planes vencidos del mes</h2>
                            <p className="text-xs text-zinc-500 mt-0.5">
                                Suscripciones con estado vencido y fecha de expiración dentro del mes
                            </p>
                        </div>
                        <span className="shrink-0 text-xs font-semibold text-zinc-400">
                            {planesVencidos.length} vencimiento{planesVencidos.length === 1 ? '' : 's'}
                        </span>
                    </div>
                    {planesVencidos.length === 0 ? (
                        <p className="px-6 py-8 text-center text-sm text-zinc-500">
                            No hay planes vencidos este mes.
                        </p>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-zinc-800 text-zinc-300">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Alumno</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Plan</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Precio</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Venció</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                    {planesVencidos.map((p, index) => (
                                        <tr key={`${p.alumno_nombre}-${p.plan_nombre}-${p.fecha_expiracion}-${index}`}
                                            className={index % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                            <td className="px-6 py-3">
                                                <p className="text-sm font-medium text-zinc-100">{p.alumno_nombre}</p>
                                                <p className="text-xs text-zinc-500">{p.correo}</p>
                                            </td>
                                            <td className="px-6 py-3 text-sm text-zinc-300">{p.plan_nombre || '—'}</td>
                                            <td className="px-6 py-3 text-sm text-zinc-300">{formatCLP(p.precio_clp || 0)}</td>
                                            <td className="px-6 py-3 text-sm text-zinc-300">{p.fecha_expiracion || '—'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>


                <div id="ranking-planes" className={`bg-zinc-900 rounded-lg shadow overflow-hidden${seccionActiva === 'ranking' ? ' ring-2 ring-indigo-500/60' : ''}`}>
                    <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between gap-3">
                        <div>
                            <h2 className="text-lg font-bold text-zinc-100">🏆 Ranking de planes del mes</h2>
                            <p className="text-xs text-zinc-500 mt-0.5">
                                Altas de planes comerciales (precio &gt; 0) este mes
                            </p>
                        </div>
                        <span className="shrink-0 text-xs font-semibold text-zinc-400">
                            {totalAltasRanking} alta{totalAltasRanking === 1 ? '' : 's'}
                        </span>
                    </div>
                    {rankingPlanes.length === 0 ? (
                        <p className="px-6 py-8 text-center text-sm text-zinc-500">
                            No hay ventas de planes este mes.
                        </p>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-zinc-800 text-zinc-300">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-sm font-medium">#</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Plan</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Altas</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">% del total</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                    {rankingPlanes.map((p, index) => (
                                        <tr key={p.plan_nombre} className={index % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                            <td className="px-6 py-3 text-sm text-zinc-500">{index + 1}</td>
                                            <td className="px-6 py-3 text-sm font-medium text-zinc-100">{p.plan_nombre}</td>
                                            <td className="px-6 py-3 text-sm text-zinc-300">{p.altas}</td>
                                            <td className="px-6 py-3">
                                                <div className="flex items-center gap-3">
                                                    <div className="h-2 w-32 max-w-full rounded bg-zinc-800 overflow-hidden">
                                                        <div className="h-full rounded bg-teal-500"
                                                            style={{ width: `${p.porcentaje}%` }} />
                                                    </div>
                                                    <span className="text-sm text-zinc-400">{p.porcentaje}%</span>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Detalle de "Membresías Mensuales" (Dashboard): cada suscripción del mes
                    con filtro por alumno, por plan ("Sin pruebas" saca las cuentas de
                    prueba, que no son ventas) y orden por fecha. Mismas reglas puras que
                    el modal del Dashboard (`utils/membresiasMes`, `npm run test:membresias`):
                    el mismo listado no puede filtrarse distinto en dos pantallas. */}
                <div id="membresias-mes"
                    className={`bg-zinc-900 rounded-lg shadow overflow-hidden${seccionActiva === 'membresias' ? ' ring-2 ring-indigo-500/60' : ''}`}>
                    <div className="px-6 py-4 border-b border-zinc-800 flex flex-wrap items-center justify-between gap-3">
                        <div>
                            <h2 className="text-lg font-bold text-zinc-100">📦 Membresías del mes</h2>
                            <p className="text-xs text-zinc-500 mt-0.5">
                                Cada suscripción iniciada este mes, con su alumno, plan y fecha
                            </p>
                        </div>
                        <span className="shrink-0 text-xs font-semibold text-zinc-400"
                            data-testid="membresias-contador">
                            {totalMembresiasMes} suscripción{totalMembresiasMes === 1 ? '' : 'es'}
                            {membresiasVisibles.length !== totalMembresiasMes
                                && ` · ${membresiasVisibles.length} con los filtros`}
                        </span>
                    </div>
                    <div className="flex flex-col gap-2 border-b border-zinc-800 px-4 py-2.5 sm:flex-row sm:items-center sm:px-6">
                        <input
                            type="search"
                            value={busquedaMembresias}
                            onChange={(e) => setBusquedaMembresias(e.target.value)}
                            placeholder="Buscar alumno…"
                            aria-label="Buscar alumno en las membresías del mes"
                            className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-teal-500 focus:outline-none"
                        />
                        <div className="flex items-center gap-2">
                            <select
                                value={planMembresias}
                                onChange={(e) => setPlanMembresias(e.target.value)}
                                aria-label="Filtrar por tipo de plan"
                                className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-teal-500 focus:outline-none sm:flex-none"
                            >
                                <option value={FILTRO_PLAN_TODOS}>Todos los planes</option>
                                <option value={FILTRO_PLAN_SIN_PRUEBA}>Sin pruebas</option>
                                {planesMembresias.map((nombre) => (
                                    <option key={nombre} value={nombre}>{nombre}</option>
                                ))}
                            </select>
                            <button
                                type="button"
                                onClick={() => setOrdenMembresias((o) => (o === 'reciente' ? 'antigua' : 'reciente'))}
                                title={ordenMembresias === 'reciente'
                                    ? 'Ordenado por fecha: más reciente primero (clic para invertir)'
                                    : 'Ordenado por fecha: más antigua primero (clic para invertir)'}
                                className="shrink-0 rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-xs font-semibold text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                            >
                                {ordenMembresias === 'reciente' ? '↓ Fecha' : '↑ Fecha'}
                            </button>
                        </div>
                    </div>
                    {totalMembresiasMes === 0 ? (
                        <p className="px-6 py-8 text-center text-sm text-zinc-500">
                            No hay membresías vendidas este mes.
                        </p>
                    ) : membresiasVisibles.length === 0 ? (
                        <div className="px-6 py-8 text-center text-sm text-zinc-500"
                            data-testid="membresias-sin-coincidencias">
                            <p>Ninguna membresía coincide con los filtros.</p>
                            <button
                                type="button"
                                onClick={limpiarFiltrosMembresias}
                                className="mt-3 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                            >
                                Limpiar filtros
                            </button>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[34rem] table-fixed">
                                <thead className="bg-zinc-800 text-zinc-300">
                                    <tr>
                                        <th className="w-[46%] px-4 py-3 text-left text-sm font-medium">Alumno</th>
                                        <th className="w-[32%] px-4 py-3 text-left text-sm font-medium">Plan</th>
                                        <th className="w-[22%] px-4 py-3 text-left text-sm font-medium">Fecha</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                    {membresiasVisibles.map((s, idx) => (
                                        // El endpoint no manda id de suscripción: la lista sale
                                        // estable del filtro, así que `idx` sirve de key.
                                        <tr key={idx} className="hover:bg-zinc-800/40">
                                            <td className="break-words px-4 py-3 text-sm font-medium text-zinc-100">{s.alumno_nombre}</td>
                                            <td className="break-words px-4 py-3 text-sm text-teal-400">{s.plan_nombre}</td>
                                            <td className="whitespace-nowrap px-4 py-3 text-sm tabular-nums text-zinc-400">{s.fecha_inicio || '-'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Resumen de Disciplinas */}
                <div id="resumen-disciplinas"
                    className={`bg-zinc-900 rounded-lg shadow overflow-hidden${seccionActiva === 'disciplinas' ? ' ring-2 ring-orange-500/60' : ''}`}>
                    <div className="px-6 py-4 border-b border-zinc-800">
                        <h2 className="text-lg font-bold text-zinc-100">Resumen de Disciplinas</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Disciplina</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Clases</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Alumnos Únicos</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Asist. Total</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Ocupación</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-800">
                                {(reportData?.ocupacionPorDisciplina || []).length > 0 ? (
                                    reportData.ocupacionPorDisciplina.map((d, index) => (
                                        <tr key={d.id} className={index % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                            <td className="px-6 py-4 text-sm font-medium text-zinc-100">{d.nombre}</td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">{d.clases || 0}</td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">{d.alumnos_unicos || 0}</td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">{d.asistentes || 0}</td>
                                            <td className="px-6 py-4 text-sm">
                                                {/* Migración 066: sin cupo no hay %; se muestra el
                                                    conteo de reservas de esa disciplina. */}
                                                {d.sin_tope || d.ocupacion_pct === null ? (
                                                    <span className="px-3 py-1 rounded-full text-xs font-medium bg-sky-100 text-sky-800"
                                                        title="Sala de acceso libre: no tiene cupo, se informa el conteo de reservas">
                                                        {d.reservas || 0} reservas (sin cupo)
                                                    </span>
                                                ) : (
                                                    <span className={`px-3 py-1 rounded-full text-xs font-medium ${d.ocupacion_pct >= 70 ? 'bg-green-100 text-green-800' : d.ocupacion_pct >= 40 ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800'}`}>
                                                        {d.ocupacion_pct}%
                                                    </span>
                                                )}
                                            </td>
                                        </tr>
                                    ))
                                ) : (
                                    <tr><td colSpan={5} className="px-6 py-6 text-center text-zinc-500">Sin datos de ocupación este mes</td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Coaches: clases dictadas + coberturas */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div id="clases-coach"
                        className={`bg-zinc-900 rounded-lg shadow overflow-hidden${seccionActiva === 'coaches' ? ' ring-2 ring-purple-500/60' : ''}`}>
                        <div className="px-6 py-4 border-b border-zinc-800">
                            <h2 className="text-lg font-bold text-zinc-100">👨‍🏫 Clases por Coach (Mes)</h2>
                        </div>
                        <div className="p-6">
                            {(reportData?.clasesPorCoach || []).length > 0 ? (
                                <div className="space-y-3">
                                    {reportData.clasesPorCoach.map((c) => (
                                        <div key={c.id} className="flex items-center justify-between">
                                            <span className="text-sm font-medium text-zinc-300">{c.nombre}</span>
                                            <span className="text-sm font-bold text-zinc-100">{c.clases} clases</span>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-zinc-500 text-sm text-center py-4">Sin datos de coaches este mes</p>
                            )}
                        </div>
                    </div>
                    <div className="bg-zinc-900 rounded-lg shadow overflow-hidden">
                        <div className="px-6 py-4 border-b border-zinc-800">
                            <h2 className="text-lg font-bold text-zinc-100">🆘 Coberturas de Emergencia</h2>
                        </div>
                        <div className="p-6">
                            <p className="text-3xl font-bold text-zinc-100">{reportData?.coberturasEmergencia || 0}</p>
                            <p className="text-sm text-zinc-400 mt-1">Usos como cobertura este mes</p>
                        </div>
                    </div>
                </div>

                {/* Detalle de Movimientos */}
                <div id="detalle-movimientos"
                    className={`bg-zinc-900 rounded-lg shadow overflow-hidden${seccionActiva === 'movimientos' ? ' ring-2 ring-green-500/60' : ''}`}>
                    <div className="px-6 py-4 border-b border-zinc-800">
                        <h2 className="text-lg font-bold text-zinc-100">📋 Detalle de Movimientos</h2>
                        <p className="text-xs text-zinc-500 mt-1">
                            Filtra por tipo o categoría y ordena tocando Fecha o Monto.
                        </p>
                    </div>
                    {/* Filtros EN MEMORIA sobre la lista del mes: no hay endpoint nuevo,
                        la lista sale del mismo hook que ya pinta la tabla. */}
                    <div className="px-6 py-3 border-b border-zinc-800 flex flex-wrap items-end gap-3">
                        <label className="text-xs font-medium text-zinc-400">
                            Tipo
                            <select value={filtroTipo} onChange={(e) => setFiltroTipo(e.target.value)}
                                className="mt-1 block w-40 rounded bg-zinc-800 border border-zinc-700 px-2 py-1.5 text-sm text-zinc-200">
                                <option value="todos">Todos</option>
                                <option value="ingreso">Ingresos</option>
                                <option value="egreso">Egresos</option>
                            </select>
                        </label>
                        <label className="text-xs font-medium text-zinc-400">
                            Categoría
                            <select value={filtroCategoria} onChange={(e) => setFiltroCategoria(e.target.value)}
                                className="mt-1 block w-48 rounded bg-zinc-800 border border-zinc-700 px-2 py-1.5 text-sm text-zinc-200">
                                <option value="todas">Todas</option>
                                {categoriasMovs.map((c) => (
                                    <option key={c} value={c}>{c}</option>
                                ))}
                            </select>
                        </label>
                        {hayFiltroMovs && (
                            <button type="button" onClick={limpiarFiltrosMovs}
                                className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-xs font-bold text-zinc-200">
                                Limpiar filtros
                            </button>
                        )}
                        <p className="text-xs text-zinc-500 ml-auto" role="status" aria-live="polite">
                            {loadingMovs
                                ? 'Cargando…'
                                : `${movimientosVisibles.length} de ${movimientosList.length} movimientos`}
                        </p>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <ThOrden campo="fecha" etiqueta="Fecha"
                                        orden={ordenMovs} onOrdenar={alternarOrdenMovs} />
                                    <th className="px-6 py-3 text-left text-sm font-medium">Tipo</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Categoría</th>
                                    <ThOrden campo="monto" etiqueta="Monto"
                                        orden={ordenMovs} onOrdenar={alternarOrdenMovs} />
                                    <th className="px-6 py-3 text-left text-sm font-medium">Descripción</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-800">
                                {loadingMovs ? (
                                    <tr><td colSpan={5} className="px-6 py-6 text-center text-zinc-500">Cargando movimientos...</td></tr>
                                ) : movimientosList.length === 0 ? (
                                    <tr><td colSpan={5} className="px-6 py-6 text-center text-zinc-500">Sin movimientos este mes</td></tr>
                                ) : movimientosVisibles.length === 0 ? (
                                    <tr>
                                        <td colSpan={5} className="px-6 py-6 text-center text-zinc-500">
                                            Ningún movimiento del mes coincide con el filtro.
                                            <button type="button" onClick={limpiarFiltrosMovs}
                                                className="ml-2 font-bold text-emerald-500 hover:text-emerald-400 underline">
                                                Quitar filtros
                                            </button>
                                        </td>
                                    </tr>
                                ) : movimientosVisibles.map((m, i) => (
                                    <tr key={m.id} className={i % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                        <td className="px-6 py-3 text-sm text-zinc-300">{m.fecha}</td>
                                        <td className="px-6 py-3 text-sm">
                                            {m.tipo === 'ingreso' ? '⬆️ Ingreso' : '⬇️ Egreso'}
                                        </td>
                                        <td className="px-6 py-3 text-sm text-zinc-400">{m.categoria}</td>
                                        <td className={`px-6 py-3 text-sm font-bold ${m.tipo === 'ingreso' ? 'text-green-600' : 'text-red-600'}`}>
                                            {m.tipo === 'ingreso' ? '+' : '-'}${Number(m.monto).toLocaleString('es-CL')}
                                        </td>
                                        <td className="px-6 py-3 text-sm text-zinc-400">{m.descripcion || '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Modal de registro de movimiento */}
                {showMovModal && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50" onClick={() => setShowMovModal(false)}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full" onClick={e => e.stopPropagation()}>
                            <h3 className="font-bold text-lg mb-4">💰 Registrar Movimiento</h3>
                            <div className="space-y-3">
                                <div>
                                    <label className="text-sm font-medium text-zinc-300">Tipo</label>
                                    <select value={movForm.tipo} onChange={e => setMovForm({ ...movForm, tipo: e.target.value })}
                                        className="w-full border rounded px-3 py-2 text-sm mt-1">
                                        <option value="egreso">💸 Egreso</option>
                                        <option value="ingreso">💵 Ingreso</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="text-sm font-medium text-zinc-300">Categoría</label>
                                    <input type="text" value={movForm.categoria} onChange={e => setMovForm({ ...movForm, categoria: e.target.value })}
                                        className="w-full border rounded px-3 py-2 text-sm mt-1" placeholder="ej: gasto_operativo" />
                                </div>
                                <div>
                                    <label className="text-sm font-medium text-zinc-300">Monto ($)</label>
                                    <input type="number" value={movForm.monto} onChange={e => setMovForm({ ...movForm, monto: e.target.value })}
                                        className="w-full border rounded px-3 py-2 text-sm mt-1" placeholder="5000" />
                                </div>
                                <div>
                                    <label className="text-sm font-medium text-zinc-300">Descripción</label>
                                    <input type="text" value={movForm.descripcion} onChange={e => setMovForm({ ...movForm, descripcion: e.target.value })}
                                        className="w-full border rounded px-3 py-2 text-sm mt-1" placeholder="ej: gastos varios" />
                                </div>
                                <div>
                                    <label className="text-sm font-medium text-zinc-300">Fecha</label>
                                    <input type="date" value={movForm.fecha} onChange={e => setMovForm({ ...movForm, fecha: e.target.value })}
                                        className="w-full border rounded px-3 py-2 text-sm mt-1" />
                                </div>
                            </div>
                            <div className="flex gap-2 mt-5">
                                <button onClick={async () => {
                                    if (!movForm.monto || !movForm.categoria) return;
                                    try {
                                        await guardarMovimiento.mutateAsync({
                                            ...movForm,
                                            monto: parseFloat(movForm.monto),
                                            tenant_id: tenantEfectivo,
                                        });
                                        setShowMovModal(false);
                                        setMovForm({ tipo: 'egreso', categoria: '', monto: '', descripcion: '', fecha: hoyChileStr(), tenant_id: tenantEfectivo });
                                        // Los KPIs del reporte los refresca la propia mutación
                                        // (invalida `['reportes']`), no hace falta pedirlos otra vez.
                                    } catch (e) { console.error(e); alert('Error al guardar'); }
                                }} disabled={savingMov}
                                    className="flex-1 py-2 bg-blue-600 text-white rounded text-sm font-bold hover:bg-blue-700">
                                    {savingMov ? 'Guardando...' : '✅ Guardar'}
                                </button>
                                <button onClick={() => setShowMovModal(false)}
                                    className="flex-1 py-2 bg-zinc-700 rounded text-sm font-medium hover:bg-zinc-600">Cancelar</button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Botón de descarga Excel */}
                <div className="flex justify-center gap-3">
                    <button
                        onClick={() => setShowMovModal(true)}
                        className="px-6 py-3 bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-colors font-bold"
                    >
                        💰 + Registrar Movimiento
                    </button>
                    <button
                        onClick={async () => {
                            try {
                                // Mes/año del CALENDARIO CHILENO (helper compartido): el
                                // navegador del admin puede estar en otra zona, y con
                                // `new Date()` la última noche del mes el reporte salía
                                // del mes siguiente (mismo bug que en Supervisión).
                                const [anio, mes] = hoyChileStr().split('-').map(Number);

                                // El Excel lo trae la mutación compartida (blob + content-type):
                                // acá sólo queda decidir si lo que llegó es el archivo o el error.
                                const response = await descargarVentas.mutateAsync({
                                    tenantId: tenantEfectivo,
                                    mes,
                                    anio,
                                });

                                const contentType = response.headers['content-type'] || '';
                                if (contentType.includes('application/json')) {
                                    const text = await response.data.text();
                                    const json = JSON.parse(text);
                                    throw new Error(json.detail || 'Error del servidor');
                                }

                                const blob = new Blob([response.data], {
                                    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                                });
                                const url = window.URL.createObjectURL(blob);
                                const link = document.createElement('a');
                                link.href = url;
                                link.setAttribute('download', `reporte_ventas_${mes.toString().padStart(2, '0')}_${anio}.xlsx`);
                                document.body.appendChild(link);
                                link.click();
                                link.remove();
                                window.URL.revokeObjectURL(url);
                            } catch (error) {
                                console.error('Error descargando reporte:', error);
                                let errorMsg = error.message || 'Error desconocido';
                                if (error.response?.data instanceof Blob) {
                                    try {
                                        const text = await error.response.data.text();
                                        const json = JSON.parse(text);
                                        errorMsg = json.detail || errorMsg;
                                    } catch { }
                                }
                                alert(`Error al descargar el reporte: ${errorMsg}`);
                            }
                        }}
                        className="px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-bold"
                    >
                        📥 Descargar Reporte Excel
                    </button>
                </div>
            </div>
            {/* ── Detalle ampliado: histórico de membresías e ingresos ── */}
            {detalleGrafico === 'membresias' && (
                <DetalleModal
                    titulo="Crecimiento de Membresías"
                    subtitulo="Altas por mes en los últimos 6 meses"
                    onCerrar={() => setDetalleGrafico(null)}
                    explicacion={(
                        <>
                            Cuenta cuántas suscripciones NUEVAS se iniciaron en cada mes
                            (suscripciones con fecha_inicio dentro del mes), para los últimos 6 meses.
                            Son altas, no miembros activos: no descuenta los planes que vencieron en el
                            mismo mes ni las renovaciones de un mismo alumno, así que un mes con muchas
                            altas y muchas bajas se ve igual de alto que uno estable.
                        </>
                    )}
                >
                    {chartMembresias(400)}
                </DetalleModal>
            )}

            {detalleGrafico === 'ingresos' && (
                <DetalleModal
                    titulo="Ingresos Mensuales"
                    subtitulo="Ingresos netos por mes (ingresos − egresos) de los últimos 6 meses"
                    onCerrar={() => setDetalleGrafico(null)}
                    explicacion={(
                        <>
                            Ingreso NETO de cada mes: ingresos menos egresos, para los últimos 6 meses.
                            Es el MISMO cálculo que usa el resto del sistema (el bloque Financiero de
                            Inteligencia de Negocio y los KPIs mensuales), así que el número coincide
                            con esas pantallas para el mismo mes.
                        </>
                    )}
                >
                    {chartIngresos(400)}
                </DetalleModal>
            )}
        </Layout>
    );
};

export default Reportes;