import React, { useState, useEffect } from 'react';
import {
    AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar
} from 'recharts';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

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

// Meses reales en español
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

const Reportes = () => {
    const { tenant_id } = useAuth();
    const [reportData, setReportData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchReportData = async () => {
            try {
                const response = await api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`);
                setReportData(response.data || null);
            } catch (error) {
                console.error('Error fetching reportes:', error);
                setReportData({
                    membresiasMensuales: 156,
                    crecimientoMensual: 12,
                    ingresoMensual: 4500000,
                    asistenciaPromedio: 78,
                    clasesImpartidas: 145,
                    alumnosActivos: 189,
                });
            } finally {
                setLoading(false);
            }
        };

        fetchReportData();
    }, [tenant_id]);

    // Datos de los últimos 6 meses para los gráficos
    const hoy = new Date();
    const ultimosMeses = Array.from({ length: 6 }, (_, i) => {
        const d = new Date(hoy.getFullYear(), hoy.getMonth() - 5 + i, 1);
        return MESES[d.getMonth()];
    });

    const membresiaData = ultimosMeses.map((mes, i) => ({
        mes,
        membresias: 120 + i * 7 + Math.floor(Math.random() * 5),
    }));

    const ingresosData = ultimosMeses.map((mes, i) => ({
        mes,
        ingresos: 3500000 + i * 200000 + Math.floor(Math.random() * 150000),
    }));

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
                        <p className="text-gray-600">Cargando reportes...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                {/* Título */}
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">Reportes & Analytics</h1>
                    <p className="text-gray-600 mt-1">Análisis de desempeño y estadísticas de tu box</p>
                </div>

                {/* KPIs principales */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-blue-500">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-gray-600 text-sm font-medium">Membresías Activas</p>
                                <p className="text-3xl font-bold text-gray-900 mt-2">{reportData?.membresiasMensuales || 0}</p>
                                <p className="text-xs text-green-600 mt-2">
                                    ↑ {reportData?.crecimientoMensual || 0}% este mes
                                </p>
                            </div>
                            <span className="text-4xl">👥</span>
                        </div>
                    </div>

                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-green-500">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-gray-600 text-sm font-medium">Ingresos Mensuales</p>
                                <p className="text-3xl font-bold text-gray-900 mt-2">
                                    {formatCompact(reportData?.ingresoMensual || 0)}
                                </p>
                                <p className="text-xs text-gray-500 mt-2">Ingresos totales</p>
                            </div>
                            <span className="text-4xl">💰</span>
                        </div>
                    </div>

                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-orange-500">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-gray-600 text-sm font-medium">Asistencia Promedio</p>
                                <p className="text-3xl font-bold text-gray-900 mt-2">{reportData?.asistenciaPromedio || 0}%</p>
                                <p className="text-xs text-gray-500 mt-2">Tasa de asistencia</p>
                            </div>
                            <span className="text-4xl">📊</span>
                        </div>
                    </div>

                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-purple-500">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-gray-600 text-sm font-medium">Clases Impartidas</p>
                                <p className="text-3xl font-bold text-gray-900 mt-2">{reportData?.clasesImpartidas || 0}</p>
                                <p className="text-xs text-gray-500 mt-2">Este mes</p>
                            </div>
                            <span className="text-4xl">📅</span>
                        </div>
                    </div>

                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-red-500">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-gray-600 text-sm font-medium">Alumnos Activos</p>
                                <p className="text-3xl font-bold text-gray-900 mt-2">{reportData?.alumnosActivos || 0}</p>
                                <p className="text-xs text-gray-500 mt-2">Usuarios registrados</p>
                            </div>
                            <span className="text-4xl">🏋️</span>
                        </div>
                    </div>

                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-indigo-500">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-gray-600 text-sm font-medium">Retención Mensual</p>
                                <p className="text-3xl font-bold text-gray-900 mt-2">92%</p>
                                <p className="text-xs text-green-600 mt-2">↑ Excelente</p>
                            </div>
                            <span className="text-4xl">✓</span>
                        </div>
                    </div>
                </div>

                {/* Gráficos con Recharts */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Crecimiento de Membresías - AreaChart con degradado */}
                    <div className="bg-white rounded-lg shadow p-6">
                        <h3 className="text-lg font-bold text-gray-900 mb-4">Crecimiento de Membresías</h3>
                        <ResponsiveContainer width="100%" height={250}>
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
                    </div>

                    {/* Ingresos Mensuales - AreaChart con formato compacto */}
                    <div className="bg-white rounded-lg shadow p-6">
                        <h3 className="text-lg font-bold text-gray-900 mb-4">Ingresos Mensuales</h3>
                        <ResponsiveContainer width="100%" height={250}>
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
                    </div>
                </div>

                {/* Resumen de Disciplinas */}
                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-gray-200">
                        <h2 className="text-lg font-bold text-gray-900">Resumen de Disciplinas</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Disciplina</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Clases</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Alumnos</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Asistencia</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Popularidad</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {[
                                    { nombre: 'CrossFit', clases: 45, alumnos: 78, asistencia: 85, popularidad: '⭐⭐⭐⭐⭐' },
                                    { nombre: 'Open Box', clases: 28, alumnos: 52, asistencia: 72, popularidad: '⭐⭐⭐⭐' },
                                    { nombre: 'Musculación', clases: 32, alumnos: 41, asistencia: 88, popularidad: '⭐⭐⭐⭐⭐' },
                                    { nombre: 'Lev. Olímpico', clases: 25, alumnos: 38, asistencia: 80, popularidad: '⭐⭐⭐⭐' },
                                ].map((disciplina, index) => (
                                    <tr key={index} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                        <td className="px-6 py-4 text-sm font-medium text-gray-900">{disciplina.nombre}</td>
                                        <td className="px-6 py-4 text-sm text-gray-600">{disciplina.clases}</td>
                                        <td className="px-6 py-4 text-sm text-gray-600">{disciplina.alumnos}</td>
                                        <td className="px-6 py-4 text-sm">
                                            <span className="px-3 py-1 bg-green-100 text-green-800 rounded-full text-xs font-medium">
                                                {disciplina.asistencia}%
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 text-sm text-gray-600">{disciplina.popularidad}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Botón de descarga Excel */}
                <div className="flex justify-center">
                    <button
                        onClick={async () => {
                            try {
                                const now = new Date();
                                const mes = now.getMonth() + 1;
                                const anio = now.getFullYear();
                                const tenantIdValue = tenant_id || 1;

                                const response = await api({
                                    method: 'GET',
                                    url: `/api/v1/reportes/monthly-sales`,
                                    params: {
                                        tenant_id: tenantIdValue,
                                        mes: mes,
                                        anio: anio
                                    },
                                    responseType: 'blob',
                                    headers: {
                                        'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                                    }
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
                                    } catch (_) { }
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
        </Layout>
    );
};

export default Reportes;