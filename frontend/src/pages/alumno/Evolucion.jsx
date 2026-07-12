import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';

const Evolucion = () => {
    const { usuario } = useAuth();
    const alumnoId = localStorage.getItem('usuario_id') || 5;
    const tenantId = localStorage.getItem('tenant_id') || 1;

    // ── Estado para RM ──
    const [movimientos, setMovimientos] = useState([]);
    const [movimientoSeleccionado, setMovimientoSeleccionado] = useState('');
    const [historialRM, setHistorialRM] = useState([]);
    const [loadingRM, setLoadingRM] = useState(false);

    // ── Estado para asistencia ──
    const [asistenciaSemanal, setAsistenciaSemanal] = useState([]);
    const [loadingAsistencia, setLoadingAsistencia] = useState(false);

    // ── Cargar movimientos disponibles ──
    useEffect(() => {
        api.get(`/api/v1/movimientos?tenant_id=${tenantId}`)
            .then(res => {
                if (Array.isArray(res.data)) {
                    setMovimientos(res.data);
                }
            })
            .catch(err => console.error('Error cargando movimientos:', err));
    }, [tenantId]);

    // ── Cargar historial del movimiento seleccionado ──
    useEffect(() => {
        if (!movimientoSeleccionado) {
            setHistorialRM([]);
            return;
        }
        setLoadingRM(true);
        api.get(`/api/v1/historial-rm/alumnos/${alumnoId}/movimiento/${movimientoSeleccionado}?tenant_id=${tenantId}`)
            .then(res => {
                const data = Array.isArray(res.data) ? res.data : [];
                setHistorialRM(data);
            })
            .catch(err => {
                console.error('Error cargando historial RM:', err);
                setHistorialRM([]);
            })
            .finally(() => setLoadingRM(false));
    }, [movimientoSeleccionado, alumnoId, tenantId]);

    // ── Cargar asistencia semanal ──
    useEffect(() => {
        setLoadingAsistencia(true);
        api.get(`/api/v1/reservas/asistencia-semanal?tenant_id=${tenantId}&usuario_id=${alumnoId}`)
            .then(res => {
                const data = Array.isArray(res.data) ? res.data : [];
                setAsistenciaSemanal(data);
            })
            .catch(err => {
                console.error('Error cargando asistencia semanal:', err);
                setAsistenciaSemanal([]);
            })
            .finally(() => setLoadingAsistencia(false));
    }, [alumnoId, tenantId]);

    // ── Determinar valor Y para el gráfico según categoría ──
    const getChartData = () => {
        if (!historialRM.length) return [];
        const categoria = historialRM[0]?.categoria || 'fuerza';
        return historialRM.map((r, idx) => {
            let valor = r.peso_kg || 0;
            let label = 'Peso (kg)';
            if (categoria === 'gimnastico') {
                valor = r.repeticiones || r.peso_kg || 0;
                label = 'Repeticiones';
            } else if (categoria === 'cardio') {
                valor = r.minutos || r.km || r.vueltas || 0;
                label = r.minutos ? 'Minutos' : r.km ? 'Km' : 'Vueltas';
            } else if (categoria === 'metabolico') {
                valor = r.calorias || r.km || r.vueltas || 0;
                label = r.calorias ? 'Calorías' : r.km ? 'Km' : 'Vueltas';
            }
            // Trend: compare with previous
            let trend = 'neutral';
            if (idx > 0) {
                const prev = historialRM[idx - 1];
                let prevValor = prev.peso_kg || 0;
                if (categoria === 'gimnastico') prevValor = prev.repeticiones || prev.peso_kg || 0;
                else if (categoria === 'cardio') prevValor = prev.minutos || prev.km || prev.vueltas || 0;
                else if (categoria === 'metabolico') prevValor = prev.calorias || prev.km || prev.vueltas || 0;
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
                <div>
                    <h1 className="text-2xl font-bold text-gray-800">📈 Evolución</h1>
                    <p className="text-gray-500 mt-1">Sigue tu progreso en el tiempo</p>
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
                            {movimientos.map(m => (
                                <option key={m.id} value={m.id}>
                                    {m.nombre} ({m.categoria})
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* SVG Defs for gradients */}
                    <svg width="0" height="0">
                        <defs>
                            <linearGradient id="barGradientUp" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#7c3aed" />   {/* purple-600 */}
                                <stop offset="100%" stopColor="#3b82f6" />  {/* blue-500 */}
                            </linearGradient>
                            <linearGradient id="barGradientDown" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#ef4444" />   {/* red-500 */}
                                <stop offset="100%" stopColor="#f97316" />  {/* orange-500 */}
                            </linearGradient>
                            <linearGradient id="barGradientNeutral" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#8b5cf6" />   {/* purple-500 */}
                                <stop offset="100%" stopColor="#6366f1" />  {/* indigo-500 */}
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
                                        backgroundColor: '#fff',
                                        border: '1px solid #e5e7eb',
                                        borderRadius: '8px',
                                        fontSize: '13px',
                                    }}
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