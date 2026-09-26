import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import AvisoCarga from '../../components/AvisoCarga';
import api from '../../services/api';
// H-03: valor/etiqueta de cada RM desde la fuente única (utils/rm.js).
import { valorRM, etiquetaValorRM } from '../../utils/rm';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';

const Evolucion = () => {
    // E-01: acá había `localStorage.getItem('usuario_id') || 5` y `|| 1`. Si la sesión
    // no estaba hidratada, la pantalla pedía los datos del alumno 5 (inexistente) y
    // mostraba gráficos vacíos sin avisar. Ahora la identidad sale del AuthContext y
    // NO se consulta nada hasta tenerla.
    const { usuario, usuario_id: authUsuarioId, tenant_id: authTenantId } = useAuth();
    const alumnoId = authUsuarioId || usuario?.id || null;
    const tenantId = authTenantId || usuario?.tenant_id || null;

    // P1: secciones que fallaron al cargar (banner con Reintentar en vez de "vacío").
    const [erroresCarga, setErroresCarga] = useState([]);

    // ── Estado para RM ──
    const [movimientos, setMovimientos] = useState([]);
    const [idsConMarcas, setIdsConMarcas] = useState([]);
    const [topMejoras, setTopMejoras] = useState([]);
    const [movimientoSeleccionado, setMovimientoSeleccionado] = useState('');
    const [historialRM, setHistorialRM] = useState([]);
    const [loadingRM, setLoadingRM] = useState(false);

    // ── Estado para asistencia ──
    const [asistenciaSemanal, setAsistenciaSemanal] = useState([]);
    const [loadingAsistencia, setLoadingAsistencia] = useState(false);

    // ── P1: carga única con Promise.allSettled ──────────────────────────────
    // Antes cada fetch tenía su propio `.catch(console.error)` y dejaba la lista
    // vacía: si la API fallaba, la pantalla mostraba "sin datos" como si el alumno
    // no tuviera historial. Ahora el fallo se acumula y se muestra en el banner.
    const cargarTodo = useCallback(async () => {
        if (!alumnoId) return;   // E-01: sin identidad no se consulta nada
        const fallaron = [];
        const [movRes, progRes, asisRes] = await Promise.allSettled([
            api.get(`/api/v1/movimientos`),
            api.get(`/api/v1/historial-rm/alumnos/${alumnoId}/progreso-destacado`),
            api.get(`/api/v1/reservas/asistencia-semanal`),
        ]);
        if (movRes.status === 'fulfilled') {
            setMovimientos(Array.isArray(movRes.value.data) ? movRes.value.data : []);
        } else {
            console.error('Error cargando movimientos:', movRes.reason);
            fallaron.push('movimientos');
        }
        if (progRes.status === 'fulfilled') {
            const data = progRes.value.data || {};
            setIdsConMarcas(data.ids_con_marcas || []);
            setTopMejoras(data.top_mejoras || []);
        } else {
            console.error('Error cargando progreso destacado:', progRes.reason);
            fallaron.push('progreso destacado');
        }
        if (asisRes.status === 'fulfilled') {
            setAsistenciaSemanal(Array.isArray(asisRes.value.data) ? asisRes.value.data : []);
        } else {
            console.error('Error cargando asistencia semanal:', asisRes.reason);
            fallaron.push('asistencia semanal');
        }
        setErroresCarga(fallaron);
    }, [alumnoId, tenantId]);

    useEffect(() => {
        setLoadingAsistencia(true);
        cargarTodo().finally(() => setLoadingAsistencia(false));
    }, [cargarTodo]);

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

    // ── Cargar historial del movimiento seleccionado ──
    useEffect(() => {
        if (!movimientoSeleccionado) {
            setHistorialRM([]);
            return;
        }
        setLoadingRM(true);
        api.get(`/api/v1/historial-rm/alumnos/${alumnoId}/movimiento/${movimientoSeleccionado}`)
            .then(res => {
                const data = Array.isArray(res.data) ? res.data : [];
                setHistorialRM(data);
                setErroresCarga(prev => prev.filter(x => x !== 'historial del movimiento'));
            })
            .catch(err => {
                console.error('Error cargando historial RM:', err);
                setHistorialRM([]);
                setErroresCarga(prev => prev.includes('historial del movimiento')
                    ? prev : [...prev, 'historial del movimiento']);
            })
            .finally(() => setLoadingRM(false));
    }, [movimientoSeleccionado, alumnoId, tenantId]);

    // ── Determinar valor Y para el gráfico según categoría ──
    const getChartData = () => {
        if (!historialRM.length) return [];
        return historialRM.map((r, idx) => {
            // H-03: el valor y su etiqueta salen de la fuente única (utils/rm.js)
            const valor = valorRM(r);
            const label = etiquetaValorRM(r);
            // Trend: compare with previous (mismo criterio de valor)
            let trend = 'neutral';
            if (idx > 0) {
                const prevValor = valorRM(historialRM[idx - 1]);
                trend = valor > prevValor ? 'up' : valor < prevValor ? 'down' : 'neutral';
            }
            return {
                fecha: r.fecha,
                valor: valor,
                label: label,
                trend: trend,
            };
        });
    };

    const chartData = getChartData();
    const valorLabel = chartData[0]?.label || 'Valor';

    // ── Nombre del movimiento seleccionado ──
    const movSeleccionado = movimientos.find(m => m.id === Number(movimientoSeleccionado));

    // ── Custom Tooltip ──
    const CustomTooltip = ({ active, payload, label }) => {
        if (active && payload && payload.length) {
            const data = payload[0].payload;
            return (
                <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-4 py-3 text-sm">
                    <p className="font-semibold text-gray-700">{label}</p>
                    <p className="text-gray-600 mt-1">
                        {valorLabel}: <span className="font-bold text-gray-800">{data.valor}</span>
                    </p>
                    {data.trend && data.trend !== 'neutral' && (
                        <p className={`text-xs mt-1 ${data.trend === 'up' ? 'text-green-600' : 'text-red-600'}`}>
                            {data.trend === 'up' ? '▲ Subió' : '▼ Bajó'} respecto al anterior
                        </p>
                    )}
                </div>
            );
        }
        return null;
    };

    return (
        <Layout>
            <div className="space-y-8">
                {/* P1: si la API falló, banner con Reintentar (antes se veía "vacío") */}
                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

                <div>
                    <h1 className="text-2xl font-bold text-gray-800">📈 Evolución</h1>
                    <p className="text-gray-500 mt-1">Sigue tu progreso en el tiempo</p>
                </div>

                {/* ============================================================ */}
                {/* TARJETAS: Mejor Progreso */}
                {/* ============================================================ */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-semibold text-gray-800 mb-4">
                        🏆 Mejor Progreso
                    </h2>
                    {topMejoras.length === 0 && (
                        <div className="text-center py-6 text-gray-400 text-sm">
                            Registra más marcas para ver tu progreso destacado aquí
                        </div>
                    )}
                    {topMejoras.length > 0 && (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {topMejoras.map((item, idx) => (
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
                </div>

                {/* ============================================================ */}
                {/* GRÁFICO 1: Progreso de RM */}
                {/* ============================================================ */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-semibold text-gray-800 mb-4">
                        🏋️ Progreso de RM
                    </h2>

                    {/* Selector de movimiento */}
                    <div className="mb-6">
                        <label className="block text-sm font-medium text-gray-600 mb-2">
                            Selecciona un movimiento
                        </label>
                        <select
                            value={movimientoSeleccionado}
                            onChange={(e) => setMovimientoSeleccionado(e.target.value)}
                            className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm"
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
                        {idsConMarcas.length > 0 && (
                            <p className="text-xs text-gray-400 mt-1">
                                {idsConMarcas.length} movimiento(s) con marcas — aparecen primero en la lista
                            </p>
                        )}
                    </div>

                    {/* SVG Defs for gradients */}
                    <svg width="0" height="0">
                        <defs>
                            <linearGradient id="barGradientUp" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#7c3aed" />
                                <stop offset="100%" stopColor="#3b82f6" />
                            </linearGradient>
                            <linearGradient id="barGradientDown" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#ef4444" />
                                <stop offset="100%" stopColor="#f97316" />
                            </linearGradient>
                            <linearGradient id="barGradientNeutral" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#8b5cf6" />
                                <stop offset="100%" stopColor="#6366f1" />
                            </linearGradient>
                        </defs>
                    </svg>

                    {/* Gráfico de barras */}
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
                            <ResponsiveContainer width="100%" height={400}>
                                <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                                    <XAxis
                                        dataKey="fecha"
                                        tick={{ fontSize: 11, angle: -45, textAnchor: 'end' }}
                                        height={60}
                                    />
                                    <YAxis tick={{ fontSize: 12 }} />
                                    <Tooltip content={<CustomTooltip />} />
                                    <Legend />
                                    <Bar dataKey="valor" name={valorLabel} radius={[6, 6, 0, 0]} barSize={40}>
                                        {chartData.map((entry, index) => {
                                            let fill = 'url(#barGradientNeutral)';
                                            if (entry.trend === 'up') fill = 'url(#barGradientUp)';
                                            else if (entry.trend === 'down') fill = 'url(#barGradientDown)';
                                            return <Cell key={`cell-${index}`} fill={fill} />;
                                        })}
                                    </Bar>
                                </BarChart>
                            </ResponsiveContainer>

                            {/* Trend legend */}
                            <div className="flex gap-6 mt-4 text-sm text-gray-500 justify-center">
                                <span><span className="inline-block w-3 h-3 rounded-sm bg-gradient-to-b from-purple-600 to-blue-500 mr-1" /> Subió</span>
                                <span><span className="inline-block w-3 h-3 rounded-sm bg-gradient-to-b from-red-500 to-orange-500 mr-1" /> Bajó</span>
                                <span><span className="inline-block w-3 h-3 rounded-sm bg-gradient-to-b from-purple-500 to-indigo-500 mr-1" /> Sin cambios</span>
                            </div>
                        </div>
                    )}
                </div>

                {/* ============================================================ */}
                {/* GRÁFICO 2: Asistencia Semanal */}
                {/* ============================================================ */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-semibold text-gray-800 mb-4">
                        📊 Asistencia Semanal (últimos 3 meses)
                    </h2>

                    {loadingAsistencia && (
                        <div className="text-center py-8 text-gray-400">Cargando asistencia...</div>
                    )}
                    {!loadingAsistencia && asistenciaSemanal.length === 0 && (
                        <div className="text-center py-8 text-gray-400">
                            No hay datos de asistencia en los últimos 3 meses
                        </div>
                    )}
                    {!loadingAsistencia && asistenciaSemanal.length > 0 && (
                        <ResponsiveContainer width="100%" height={350}>
                            <BarChart data={asistenciaSemanal} margin={{ top: 5, right: 30, left: 20, bottom: 60 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                                <XAxis dataKey="semana" tick={{ fontSize: 11, angle: -45, textAnchor: 'end' }} height={60} />
                                <YAxis tick={{ fontSize: 12 }} />
                                <Tooltip
                                    contentStyle={{
                                        backgroundColor: '#18181b',
                                        border: '1px solid #3f3f46',
                                        borderRadius: '8px',
                                        fontSize: '13px',
                                        color: '#f4f4f5',
                                    }}
                                    labelStyle={{ color: '#f4f4f5' }}
                                    itemStyle={{ color: '#d4d4d8' }}
                                />
                                <Legend />
                                <Bar dataKey="asistencias" name="Asistió" fill="#10b981" radius={[4, 4, 0, 0]} />
                                <Bar dataKey="total" name="Total reservas" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    )}
                </div>
            </div>
        </Layout>
    );
};

export default Evolucion;