import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Reportes = () => {
    const { tenant_id } = useAuth();
    const [reportData, setReportData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchReportData = async () => {
            try {
                // TODO: Uncomment when backend endpoint is ready
                // const response = await api.get(`/api/v1/reportes?tenant_id=${tenant_id}`);
                // setReportData(response.data || null);

                // Using hardcoded mock data for now
                setReportData({
                    membresiasMensuales: 156,
                    crecimientoMensual: 12,
                    ingresoMensual: 4500000,
                    asistenciaPromedio: 78,
                    clasesImpartidas: 145,
                    alumnosActivos: 189,
                });
            } catch (error) {
                console.error('Error fetching reportes:', error);
                // Datos de ejemplo
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

    // Componente para gráfico simple de línea
    const LineChart = ({ title, data, color }) => {
        const maxValue = Math.max(...data);
        const chartHeight = 200;
        const chartWidth = 300;
        const padding = 40;

        const points = data.map((value, index) => {
            const x = padding + ((index + 1) / (data.length + 1)) * (chartWidth - 2 * padding);
            const y = chartHeight - padding - (value / maxValue) * (chartHeight - 2 * padding);
            return { x, y, value };
        });

        return (
            <div className="bg-white rounded-lg shadow p-6">
                <h3 className="text-lg font-bold text-gray-900 mb-4">{title}</h3>
                <svg width="100%" height={chartHeight} viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="w-full">
                    {/* Ejes */}
                    <line x1={padding} y1={chartHeight - padding} x2={chartWidth - padding} y2={chartHeight - padding} stroke="#ccc" strokeWidth="2" />
                    <line x1={padding} y1={padding} x2={padding} y2={chartHeight - padding} stroke="#ccc" strokeWidth="2" />

                    {/* Línea */}
                    {points.length > 1 && (
                        <polyline
                            points={points.map((p) => `${p.x},${p.y}`).join(' ')}
                            fill="none"
                            stroke={color}
                            strokeWidth="3"
                        />
                    )}

                    {/* Puntos */}
                    {points.map((point, index) => (
                        <g key={index}>
                            <circle cx={point.x} cy={point.y} r="4" fill={color} />
                            <text x={point.x} y={chartHeight - padding + 20} textAnchor="middle" fontSize="12" fill="#666">
                                {`M${index + 1}`}
                            </text>
                            <text x={point.x} y={point.y - 10} textAnchor="middle" fontSize="11" fill={color} fontWeight="bold">
                                {point.value}
                            </text>
                        </g>
                    ))}
                </svg>
            </div>
        );
    };

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
                    {/* Membresías Activas */}
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

                    {/* Ingresos Mensuales */}
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-green-500">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-gray-600 text-sm font-medium">Ingresos Mensuales</p>
                                <p className="text-3xl font-bold text-gray-900 mt-2">
                                    ${(reportData?.ingresoMensual || 0).toLocaleString('es-CL')}
                                </p>
                                <p className="text-xs text-gray-500 mt-2">Ingresos totales</p>
                            </div>
                            <span className="text-4xl">💰</span>
                        </div>
                    </div>

                    {/* Asistencia Promedio */}
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

                    {/* Clases Impartidas */}
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

                    {/* Alumnos Activos */}
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

                    {/* Tasa de Retención */}
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

                {/* Gráficos */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <LineChart
                        title="Crecimiento de Membresías (Últimos 6 meses)"
                        data={[120, 128, 135, 142, 148, 156]}
                        color="#FF6B35"
                    />
                    <LineChart
                        title="Ingresos Mensuales (Últimos 6 meses)"
                        data={[3500000, 3700000, 3900000, 4100000, 4300000, 4500000]}
                        color="#1F4E78"
                    />
                </div>

                {/* Tabla de resumen */}
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
                                    { nombre: 'Yoga', clases: 28, alumnos: 52, asistencia: 72, popularidad: '⭐⭐⭐⭐' },
                                    { nombre: 'Spinning', clases: 32, alumnos: 41, asistencia: 88, popularidad: '⭐⭐⭐⭐⭐' },
                                    { nombre: 'Funcional', clases: 25, alumnos: 38, asistencia: 80, popularidad: '⭐⭐⭐⭐' },
                                    { nombre: 'Pilates', clases: 15, alumnos: 28, asistencia: 75, popularidad: '⭐⭐⭐' },
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

                {/* Botón de descarga - Descarga Excel real desde el backend */}
                <div className="flex justify-center">
                    <button
                        onClick={async () => {
                            try {
                                const now = new Date();
                                const mes = now.getMonth() + 1;
                                const anio = now.getFullYear();
                                const tenantIdValue = tenant_id || 1;

                                // Descargar archivo Excel real desde el backend con responseType blob
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

                                // Verificar que la respuesta sea un blob válido (no un JSON de error)
                                const contentType = response.headers['content-type'] || '';
                                if (contentType.includes('application/json')) {
                                    const text = await response.data.text();
                                    const json = JSON.parse(text);
                                    throw new Error(json.detail || 'Error del servidor');
                                }

                                // Crear URL del blob y descargar
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
