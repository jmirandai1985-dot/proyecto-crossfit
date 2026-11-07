import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import AvisoCarga from '../../components/AvisoCarga';
import BotonVolver from '../../components/BotonVolver';
// Fase 2 (Bloque 1): los datos salen de la caché compartida (mismos datos que la
// Pizarra de RMs y el Performance Hub), no de un useEffect por pantalla.
import {
    useAsistenciaSemanal, useMovimientos, useNivelGeneral, useProgresoDestacado, useRmDeMovimiento,
} from '../../hooks/queries';
// Fecha corta DD/MM (misma función que usa Performance Hub para el eje X).
import { fmtFechaCortaChile } from '../../utils/fecha';
// Cálculo de cumplimiento + racha del gráfico de Asistencia Semanal.
import { calcularRachaAsistencia } from '../../utils/asistenciaEvolucion';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import BottomSheet from '../../components/BottomSheet';
import { getChartData } from '../../utils/evolucionChart';
// Resumen por movimiento + objetivo sugerido y plan de progresión (fuente única).
import { evolucionPorMovimiento, objetivosSugeridos } from '../../utils/evolucionRM';

// Acento de la app (orange-500): es el "emerald → naranja" que aplica `src/index.css`.
const COLOR_ACCENTO = '#f97316';
// Geometría del anillo de cumplimiento (Asistencia Semanal).
const RING_RADIO = 54;
const RING_CIRC = 2 * Math.PI * RING_RADIO;

const Evolucion = () => {
    // E-01: acá había `localStorage.getItem('usuario_id') || 5` y `|| 1`. Si la sesión
    // no estaba hidratada, la pantalla pedía los datos del alumno 5 (inexistente) y
    // mostraba gráficos vacíos sin avisar. Ahora la identidad sale del AuthContext y
    // NO se consulta nada hasta tenerla.
    const { usuario, usuario_id: authUsuarioId } = useAuth();
    const alumnoId = authUsuarioId || usuario?.id || null;

    // Fase 2 (Bloque 1): cada dato sale de su consulta compartida y la lista de fallos
    // es DERIVADA de esas consultas (antes era un estado sincronizado a mano desde tres
    // callbacks). El "movimiento seleccionado" sigue siendo estado de la PANTALLA.
    const [movimientoSeleccionado, setMovimientoSeleccionado] = useState('');
    // Vista expandida del gráfico "Progreso de RM" (bottom sheet).
    const [sheetAbierto, setSheetAbierto] = useState(false);
    const abrirSheet = () => setSheetAbierto(true);
    const cerrarSheet = React.useCallback(() => setSheetAbierto(false), []);

    const movimientosQ = useMovimientos();
    const progresoQ = useProgresoDestacado(alumnoId);
    const asistenciaQ = useAsistenciaSemanal();
    const historialQ = useRmDeMovimiento(alumnoId, movimientoSeleccionado);
    // Detalle por movimiento del nivel (para la tarjeta de nivel del panel expandido).
    const nivelGeneralQ = useNivelGeneral(alumnoId);

    // `?? []` DENTRO de un `useMemo`: la consulta mantiene la MISMA referencia mientras
    // el dato no cambia, así que los `useMemo`/`useEffect` de abajo no se recalculan en
    // cada render (un `|| []` suelto crearía un array nuevo cada vez).
    const movimientos = React.useMemo(() => movimientosQ.data || [], [movimientosQ.data]);
    const idsConMarcas = React.useMemo(
        () => progresoQ.data?.ids_con_marcas || [], [progresoQ.data],
    );
    const topMejoras = React.useMemo(() => progresoQ.data?.top_mejoras || [], [progresoQ.data]);
    const asistenciaSemanal = React.useMemo(() => asistenciaQ.data || [], [asistenciaQ.data]);
    const historialRM = React.useMemo(() => historialQ.data || [], [historialQ.data]);
    // Cumplimiento + racha de Asistencia Semanal, calculados en cliente (sin red).
    const asistenciaResumen = React.useMemo(
        () => calcularRachaAsistencia(asistenciaSemanal),
        [asistenciaSemanal],
    );
    // "Cargando" sólo mientras NO hay dato: al volver a la pantalla se pinta la copia en
    // caché al instante y se refresca en segundo plano (nunca una pantalla vacía falsa).
    const loadingAsistencia = asistenciaQ.isPending;
    const loadingRM = historialQ.isPending;

    // Secciones caídas (mismo copy que antes) leídas del estado real de cada consulta.
    const erroresCarga = React.useMemo(() => {
        const fallaron = [];
        if (movimientosQ.isError) fallaron.push('movimientos');
        if (progresoQ.isError) fallaron.push('progreso destacado');
        if (asistenciaQ.isError) fallaron.push('asistencia semanal');
        if (movimientoSeleccionado && historialQ.isError) fallaron.push('historial del movimiento');
        return fallaron;
    }, [movimientosQ.isError, progresoQ.isError, asistenciaQ.isError,
        historialQ.isError, movimientoSeleccionado]);

    // Reintentar = volver a pedir las cuatro (el mismo botón del banner de antes).
    const cargarTodo = () => {
        movimientosQ.refetch();
        progresoQ.refetch();
        asistenciaQ.refetch();
        historialQ.refetch();
    };

    // E-03: deep-link desde Performance Hub → /alumno/evolucion?movimiento=<id>.
    // Antes el link existía pero la pantalla no leía el parámetro: se abría sin
    // movimiento seleccionado (y el gráfico quedaba vacío).
    const [searchParams] = useSearchParams();
    useEffect(() => {
        const mid = Number(searchParams.get('movimiento'));
        if (!mid || !movimientos.length) return;
        if (movimientos.some(m => Number(m.id) === mid)) {
            setMovimientoSeleccionado(String(mid));
        }
    }, [searchParams, movimientos]);

    // ── Movimientos ordenados: con marcas primero ──
    const movimientosOrdenados = React.useMemo(() => {
        const conMarcas = [];
        const sinMarcas = [];
        movimientos.forEach(m => {
            if (idsConMarcas.includes(m.id)) {
                conMarcas.push(m);
            } else {
                sinMarcas.push(m);
            }
        });
        return [...conMarcas, ...sinMarcas];
    }, [movimientos, idsConMarcas]);

    // ── Determinar valor Y para el gráfico según categoría ──
    // getChartData() vive en utils/evolucionChart.js (pura, testeable): agrega
    // una clave única `x` por punto para que los registros de la misma fecha no
    // colapsen en el tooltip de Recharts.
    const chartData = getChartData(historialRM);
    const valorLabel = chartData[0]?.label || 'Valor';

    // ── Nombre del movimiento seleccionado ──
    const movSeleccionado = movimientos.find(m => m.id === Number(movimientoSeleccionado));

    // ── Resumen del movimiento (evolucionPorMovimiento re-sortea y calcula PR/%/días) ──
    const resumenMov = React.useMemo(() => {
        if (!historialRM.length) return null;
        const res = evolucionPorMovimiento(historialRM);
        return res.length ? res[0] : null;
    }, [historialRM]);
    // Objetivo sugerido + plan de progresión (solo fuerza/gimnástico con marca).
    const objetivo = React.useMemo(() => {
        if (!resumenMov) return null;
        const objs = objetivosSugeridos([resumenMov]);
        return objs.length ? objs[0] : null;
    }, [resumenMov]);
    // PR actual = máximo histórico (lo que el backend usa para clasificar).
    const prActual = chartData.length ? Math.max(...chartData.map((p) => p.valor)) : null;
    // % de mejora total: primer registro → último registro.
    const pctMejoraTotal = chartData.length >= 2 && chartData[0].valor
        ? ((chartData[chartData.length - 1].valor - chartData[0].valor) / chartData[0].valor) * 100
        : null;
    // Nivel para ESTE movimiento (detalle por movimiento del endpoint nivel-general).
    const nivelDetalle = React.useMemo(() => {
        const g = nivelGeneralQ.data;
        if (!g) return null;
        const id = Number(movimientoSeleccionado);
        const enFuerza = (g.detalle_fuerza || []).find((d) => d.movimiento_id === id);
        if (enFuerza) return { ...enFuerza, eje: 'fuerza' };
        const enGim = (g.detalle_gimnastico || []).find((d) => d.movimiento_id === id);
        if (enGim) return { ...enGim, eje: 'gimnastico' };
        return null;
    }, [nivelGeneralQ.data, movimientoSeleccionado]);

    // Progreso de la barra de nivel (entre el umbral del nivel actual y el siguiente).
    const pctNivel = React.useMemo(() => {
        if (!nivelDetalle) return 0;
        const a = nivelDetalle.umbral_actual;
        const b = nivelDetalle.umbral_siguiente;
        if (a == null || b == null || b <= a) return nivelDetalle.nivel === 'Elite' ? 100 : 0;
        return Math.min(100, Math.max(0, ((prActual - a) / (b - a)) * 100));
    }, [nivelDetalle, prActual]);

    // ── Custom Tooltip (dark, coherente con el resto de la pantalla) ──
    // Con `dataKey="x"` en el XAxis, `label` es el índice; la fecha sale del
    // `payload` del punto tocado (no del label) para que los duplicados no
    // muestren siempre el primer valor.
    const CustomTooltip = ({ active, payload }) => {
        if (active && payload && payload.length) {
            const data = payload[0].payload;
            return (
                <div className="rounded-lg border border-zinc-700 bg-zinc-900 shadow-lg px-4 py-3 text-sm">
                    <p className="font-semibold text-zinc-200">{fmtFechaCortaChile(data.fecha)}</p>
                    <p className="text-zinc-300 mt-1">
                        {valorLabel}: <span className="font-bold text-zinc-100">{data.valor}</span>
                    </p>
                    {data.trend && data.trend !== 'neutral' && (
                        <p className={`text-xs mt-1 ${data.trend === 'up' ? 'text-green-400' : 'text-red-400'}`}>
                            {data.trend === 'up' ? '▲ Subió' : '▼ Bajó'} respecto al anterior
                        </p>
                    )}
                </div>
            );
        }
        return null;
    };

    // ── Punto de la serie: el último (PR) va más grande y en el color de acento ──
    const renderDot = ({ cx, cy, index }) => {
        const esUltimo = index === chartData.length - 1;
        return (
            <circle
                key={`dot-${index}`}
                cx={cx}
                cy={cy}
                r={esUltimo ? 6 : 3}
                fill={COLOR_ACCENTO}
                stroke={esUltimo ? '#09090b' : 'none'}
                strokeWidth={esUltimo ? 2 : 0}
            />
        );
    };

    // ── AreaChart reutilizable: el mismo gráfico en dos alturas (tarjeta y sheet) ──
    // `referenciaValor` (opcional) dibuja la línea punteada del objetivo sugerido en el
    // panel expandido y estira el dominio del eje Y para que la línea quede visible.
    const renderGraficoRM = (height, referenciaValor = null) => (
        <ResponsiveContainer width="100%" height={height}>
            <AreaChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis
                    dataKey="x"
                    tickFormatter={(idx) => fmtFechaCortaChile(chartData[idx]?.fecha)}
                    tick={{ fill: '#a1a1aa', fontSize: 11 }}
                    angle={-45}
                    textAnchor="end"
                    height={60}
                />
                <YAxis
                    tick={{ fill: '#a1a1aa', fontSize: 12 }}
                    domain={[0, (dataMax) => Math.max(dataMax, referenciaValor || 0) * 1.1]}
                />
                <Tooltip content={<CustomTooltip />} />
                {referenciaValor !== null && (
                    <ReferenceLine
                        y={referenciaValor}
                        stroke="#f97316"
                        strokeDasharray="6 6"
                        strokeWidth={1.5}
                        label={{
                            value: `Objetivo ${referenciaValor}`,
                            fill: '#fb923c',
                            fontSize: 11,
                            position: 'insideTopRight',
                        }}
                    />
                )}
                <Area
                    type="monotone"
                    dataKey="valor"
                    name={valorLabel}
                    stroke={COLOR_ACCENTO}
                    strokeWidth={2.5}
                    fill="url(#rmAreaGradient)"
                    dot={renderDot}
                    activeDot={{ r: 5, fill: COLOR_ACCENTO, stroke: '#09090b', strokeWidth: 2 }}
                    connectNulls
                />
            </AreaChart>
        </ResponsiveContainer>
    );

    return (
        <Layout>
            <div className="grid grid-cols-1 gap-6">
                {/* P1: si la API falló, banner con Reintentar (antes se veía "vacío") */}
                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

                <div className="max-md:flex max-md:items-start max-md:gap-2">
                    <BotonVolver />
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">📈 Evolución</h1>
                        <p className="text-gray-500 mt-1">Sigue tu progreso en el tiempo</p>
                    </div>
                </div>

                {/* ============================================================ */}
                {/* TARJETAS: Mejor Progreso */}
                {/* ============================================================ */}
                <section className="rounded-2xl bg-[#12161f] border border-[#1f2430] p-6">
                    <div className="mb-5 flex items-center gap-3">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-800 text-lg" aria-hidden="true">🏆</span>
                        <h2 className="text-lg font-semibold text-gray-800">Mejor Progreso</h2>
                    </div>
                    {topMejoras.length === 0 && (
                        <div className="text-center py-6 text-gray-400 text-sm">
                            Registra más marcas para ver tu progreso destacado aquí
                        </div>
                    )}
                    {topMejoras.length > 0 && (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {topMejoras.map((item) => (
                                <div
                                    key={item.movimiento_id}
                                    className="border border-gray-200 rounded-lg p-4 bg-gradient-to-br from-purple-50 to-blue-50 hover:shadow-md transition-shadow cursor-pointer"
                                    onClick={() => setMovimientoSeleccionado(String(item.movimiento_id))}
                                >
                                    <div className="flex items-start justify-between">
                                        <div>
                                            <p className="text-sm font-semibold text-gray-800">{item.movimiento_nombre}</p>
                                            <p className="text-xs text-gray-400 capitalize">{item.categoria}</p>
                                        </div>
                                        <span className="text-2xl">📈</span>
                                    </div>
                                    <div className="mt-3 flex items-baseline gap-1">
                                        <span className="text-2xl font-bold text-emerald-600">+{item.diferencia}</span>
                                        <span className="text-sm text-gray-500">{item.unidad}</span>
                                    </div>
                                    <p className="text-xs text-gray-400 mt-1">en {item.periodo}</p>
                                </div>
                            ))}
                        </div>
                    )}
                </section>

                {/* ============================================================ */}
                {/* GRÁFICO 1: Progreso de RM */}
                {/* ============================================================ */}
                <section className="rounded-2xl bg-[#12161f] border border-[#1f2430] p-6">
                    <div className="mb-5 flex items-center gap-3">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-800 text-lg" aria-hidden="true">🏋️</span>
                        <h2 className="text-lg font-semibold text-gray-800">Progreso de RM</h2>
                    </div>

                    {/* Selector de movimiento */}
                    <div className="mb-6">
                        <label className="block text-sm font-medium text-gray-600 mb-2">
                            Selecciona un movimiento
                        </label>
                        <div className="relative max-w-md">
                            <select
                                value={movimientoSeleccionado}
                                onChange={(e) => setMovimientoSeleccionado(e.target.value)}
                                className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm appearance-none cursor-pointer"
                            >
                                <option value="">-- Elegir movimiento --</option>
                                {/* Separador: movimientos CON marcas */}
                                {movimientosOrdenados.filter(m => idsConMarcas.includes(m.id)).length > 0 && (
                                    <optgroup label="✦ Con registros">
                                        {movimientosOrdenados
                                            .filter(m => idsConMarcas.includes(m.id))
                                            .map(m => (
                                                <option key={m.id} value={m.id} className="font-semibold">
                                                    {m.nombre} ({m.categoria})
                                                </option>
                                            ))
                                        }
                                    </optgroup>
                                )}
                                {/* Separador: movimientos SIN marcas */}
                                {movimientosOrdenados.filter(m => !idsConMarcas.includes(m.id)).length > 0 && (
                                    <optgroup label="— Sin registros aún">
                                        {movimientosOrdenados
                                            .filter(m => !idsConMarcas.includes(m.id))
                                            .map(m => (
                                                <option key={m.id} value={m.id} className="text-gray-400">
                                                    {m.nombre} ({m.categoria})
                                                </option>
                                            ))
                                        }
                                    </optgroup>
                                )}
                            </select>
                            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400">
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                </svg>
                            </div>
                        </div>
                        {idsConMarcas.length > 0 && (
                            <p className="text-xs text-gray-400 mt-1">
                                {idsConMarcas.length} movimiento(s) con marcas — aparecen primero en la lista
                            </p>
                        )}
                    </div>

                    {/* SVG Defs: gradiente del área bajo la curva de RM (se desvanece hacia abajo) */}
                    <svg width="0" height="0">
                        <defs>
                            <linearGradient id="rmAreaGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor={COLOR_ACCENTO} stopOpacity={0.35} />
                                <stop offset="100%" stopColor={COLOR_ACCENTO} stopOpacity={0} />
                            </linearGradient>
                        </defs>
                    </svg>

                    {/* Gráfico de línea con área (Opción A del mockup) */}
                    {loadingRM && (
                        <div className="text-center py-8 text-gray-400">Cargando historial...</div>
                    )}
                    {!loadingRM && !movimientoSeleccionado && (
                        <div className="text-center py-8 text-gray-400">
                            Selecciona un movimiento para ver su evolución
                        </div>
                    )}
                    {!loadingRM && movimientoSeleccionado && chartData.length === 0 && (
                        <div className="text-center py-8 text-gray-400">
                            No hay registros para este movimiento
                        </div>
                    )}
                    {!loadingRM && chartData.length > 0 && (
                        <div>
                            <p className="text-sm text-gray-500 mb-3">
                                Movimiento: <strong>{movSeleccionado?.nombre}</strong> — {chartData.length} registro(s)
                            </p>
                            {/* Tocá/clickeá el gráfico para verlo en grande (bottom sheet) */}
                            <div
                                className="cursor-pointer group"
                                role="button"
                                tabIndex={0}
                                aria-label="Ampliar gráfico de Progreso de RM"
                                onClick={abrirSheet}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        abrirSheet();
                                    }
                                }}
                            >
                                {renderGraficoRM(400)}
                                <p className="mt-2 text-center text-xs text-gray-500 group-hover:text-gray-300">
                                    Toca el gráfico para verlo en grande
                                </p>
                            </div>
                        </div>
                    )}
                </section>

                {/* Vista expandida: bottom sheet con el mismo gráfico más grande + chips */}
                <BottomSheet
                    isOpen={sheetAbierto}
                    onClose={cerrarSheet}
                    title={movSeleccionado?.nombre || 'Progreso de RM'}
                    subtitle={movSeleccionado?.categoria || ''}
                >
                    <div className="space-y-4">
                        {/* Tarjeta de nivel (la más destacada, arriba de todo) */}
                        {nivelDetalle && nivelDetalle.nivel && nivelDetalle.nivel !== 'Sin datos' && (
                            <div className="rounded-xl border border-zinc-700 bg-zinc-900 p-4">
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <p className="text-xs uppercase tracking-wide text-zinc-400">Nivel actual</p>
                                        <p className="text-2xl font-bold text-zinc-100">{nivelDetalle.nivel}</p>
                                    </div>
                                    <span className="rounded-full bg-orange-500/15 px-3 py-1 text-xs font-semibold text-orange-300">
                                        {resumenMov?.categoria === 'gimnastico' ? 'Gimnástico' : 'Fuerza'}
                                    </span>
                                </div>
                                <p className="mt-2 text-sm text-zinc-300">
                                    {nivelDetalle.siguiente_nivel
                                        ? `Para subir a ${nivelDetalle.siguiente_nivel} te faltarían ${nivelDetalle.valor_faltante} ${resumenMov?.unidad || ''} en este movimiento`
                                        : 'Ya alcanzaste el nivel máximo (Elite)'}
                                </p>
                                <div className="mt-3 h-2 overflow-hidden rounded-full bg-zinc-800">
                                    <div
                                        className="h-full rounded-full bg-orange-500 transition-all"
                                        style={{ width: `${pctNivel}%` }}
                                    />
                                </div>
                            </div>
                        )}

                        {/* 4 tarjetas de estadísticas */}
                        <div className="grid grid-cols-2 gap-3">
                            <div className="rounded-xl border border-zinc-700 bg-zinc-900 p-3">
                                <p className="text-xs text-zinc-400">PR actual</p>
                                <p className="mt-1 text-lg font-bold text-zinc-100">
                                    {prActual != null ? `${prActual} ${resumenMov?.unidad || ''}` : '—'}
                                </p>
                            </div>
                            <div className="rounded-xl border border-zinc-700 bg-zinc-900 p-3">
                                <p className="text-xs text-zinc-400">% mejora total</p>
                                <p className="mt-1 text-lg font-bold text-zinc-100">
                                    {pctMejoraTotal != null ? `${pctMejoraTotal > 0 ? '+' : ''}${Math.round(pctMejoraTotal)}%` : '—'}
                                </p>
                            </div>
                            <div className="rounded-xl border border-zinc-700 bg-zinc-900 p-3">
                                <p className="text-xs text-zinc-400">Próximo objetivo</p>
                                <p className="mt-1 text-lg font-bold text-zinc-100">
                                    {objetivo ? `${objetivo.objetivoSugerido} ${objetivo.unidad}` : '—'}
                                </p>
                            </div>
                            <div className="rounded-xl border border-zinc-700 bg-zinc-900 p-3">
                                <p className="text-xs text-zinc-400">Último PR</p>
                                <p className="mt-1 text-lg font-bold text-zinc-100">
                                    {resumenMov?.diasDesdePR != null
                                        ? (resumenMov.diasDesdePR === 0 ? 'Hoy' : `hace ${resumenMov.diasDesdePR} días`)
                                        : '—'}
                                </p>
                            </div>
                        </div>

                        {/* Gráfico + panel lateral de progresión (desktop a la derecha) */}
                        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_280px] lg:gap-4">
                            <div className="min-w-0">
                                {renderGraficoRM(280, objetivo?.objetivoSugerido ?? null)}
                            </div>
                            {objetivo && objetivo.planProgresion?.length > 0 && (
                                <div className="mt-4 lg:mt-0 lg:border-l lg:border-zinc-700 lg:pl-4">
                                    <h3 className="text-sm font-semibold text-zinc-100">Plan de progresión</h3>
                                    <ol className="mt-2 space-y-2">
                                        {objetivo.planProgresion.map((paso, i) => (
                                            <li key={i} className="flex gap-2 text-sm text-zinc-300">
                                                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-orange-500/15 text-xs font-bold text-orange-300">
                                                    {i + 1}
                                                </span>
                                                <span className="min-w-0">{paso.texto}</span>
                                            </li>
                                        ))}
                                    </ol>
                                    <p className="mt-2 text-xs text-zinc-400">{objetivo.ventanaReintento}</p>
                                </div>
                            )}
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {chartData.map((p) => (
                                <span
                                    key={p.x}
                                    className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-300"
                                >
                                    <span className="text-zinc-400">{fmtFechaCortaChile(p.fecha)}</span>
                                    <span className="font-bold text-orange-300">{p.valor}</span>
                                </span>
                            ))}
                        </div>
                    </div>
                </BottomSheet>

                {/* ============================================================ */}
                {/* GRÁFICO 2: Asistencia Semanal */}
                {/* ============================================================ */}
                <section className="rounded-2xl bg-[#12161f] border border-[#1f2430] p-6">
                    <div className="mb-5 flex items-center gap-3">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-800 text-lg" aria-hidden="true">📊</span>
                        <h2 className="text-lg font-semibold text-gray-800">Asistencia Semanal (últimos 3 meses)</h2>
                    </div>

                    {loadingAsistencia && (
                        <div className="text-center py-8 text-gray-400">Cargando asistencia...</div>
                    )}
                    {!loadingAsistencia && asistenciaSemanal.length === 0 && (
                        <div className="text-center py-8 text-gray-400">
                            No hay datos de asistencia en los últimos 3 meses
                        </div>
                    )}
                    {!loadingAsistencia && asistenciaSemanal.length > 0 && (
                        <div className="flex flex-col items-center">
                            {/* Anillo de cumplimiento (Opción C del mockup) */}
                            <div className="relative w-44 h-44">
                                <svg
                                    viewBox="0 0 120 120"
                                    className="w-full h-full"
                                    style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }}
                                >
                                    <circle cx="60" cy="60" r={RING_RADIO} fill="none" stroke="#27272a" strokeWidth="12" />
                                    <circle
                                        cx="60"
                                        cy="60"
                                        r={RING_RADIO}
                                        fill="none"
                                        stroke={COLOR_ACCENTO}
                                        strokeWidth="12"
                                        strokeLinecap="round"
                                        strokeDasharray={RING_CIRC}
                                        strokeDashoffset={RING_CIRC * (1 - asistenciaResumen.cumplimientoPct / 100)}
                                    />
                                </svg>
                                <div className="absolute inset-0 flex flex-col items-center justify-center">
                                    <span className="text-3xl font-bold text-zinc-100">{asistenciaResumen.cumplimientoPct}%</span>
                                    <span className="text-xs text-zinc-400">cumplimiento</span>
                                </div>
                            </div>

                            <p className="mt-4 text-sm text-zinc-300">
                                {asistenciaResumen.totalAsistencias} de {asistenciaResumen.totalReservas} clases reservadas
                            </p>

                            <span className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-orange-500/15 text-orange-300 text-xs font-semibold px-3 py-1">
                                🔥 Racha actual: {asistenciaResumen.rachaActual} semana{asistenciaResumen.rachaActual === 1 ? '' : 's'}
                            </span>

                            <p className="mt-2 text-xs text-zinc-400">
                                Mejor racha histórica: {asistenciaResumen.mejorRacha} semana{asistenciaResumen.mejorRacha === 1 ? '' : 's'}
                            </p>
                        </div>
                    )}
                </section>
            </div>
        </Layout>
    );
};

export default Evolucion;