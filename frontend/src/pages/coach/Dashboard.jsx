import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const CoachDashboard = () => {
    const { tenant_id } = useAuth();
    const [clasesHoy, setClasesHoy] = useState([]);
    const [stats, setStats] = useState({
        totalClasesHoy: 0,
        totalAlumnosAsistidos: 0,
    });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchCoachData = async () => {
            try {
                const response = await api.get(`/api/v1/coach/dashboard?tenant_id=${tenant_id}`);
                setStats(response.data.stats || stats);
                setClasesHoy(response.data.clasesHoy || []);
            } catch (error) {
                console.error('Error fetching coach data:', error);
                // Datos de ejemplo
                setStats({
                    totalClasesHoy: 3,
                    totalAlumnosAsistidos: 28,
                });
                setClasesHoy([
                    { id: 1, nombre: 'CrossFit Matutino', hora: '08:00', alumnos: 12, disciplina: 'CrossFit' },
                    { id: 2, nombre: 'CrossFit Tarde', hora: '18:00', alumnos: 10, disciplina: 'CrossFit' },
                    { id: 3, nombre: 'Funcional Noche', hora: '20:00', alumnos: 6, disciplina: 'Funcional' },
                ]);
            } finally {
                setLoading(false);
            }
        };

        fetchCoachData();
    }, [tenant_id]);

    const StatCard = ({ title, value, icon, color }) => (
        <div className={`bg-white rounded-lg shadow p-6 border-l-4 ${color}`}>
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-gray-600 text-sm font-medium">{title}</p>
                    <p className="text-3xl font-bold text-gray-900 mt-2">{value}</p>
                </div>
                <div className="text-4xl">{icon}</div>
            </div>
        </div>
    );

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4"></div>
                        <p className="text-gray-600">Cargando dashboard...</p>
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
                    <h1 className="text-3xl font-bold text-gray-900">Dashboard Coach</h1>
                    <p className="text-gray-600 mt-1">Gestiona tus clases y alumnos</p>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <StatCard
                        title="Mis Clases Hoy"
                        value={stats.totalClasesHoy}
                        icon="📅"
                        color="border-blue-500"
                    />
                    <StatCard
                        title="Total Alumnos Asistidos"
                        value={stats.totalAlumnosAsistidos}
                        icon="👥"
                        color="border-orange-500"
                    />
                </div>

                {/* Clases del Día */}
                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-gray-200">
                        <h2 className="text-lg font-bold text-gray-900">Mis Clases de Hoy</h2>
                    </div>
                    <div className="divide-y divide-gray-200">
                        {clasesHoy.map((clase) => (
                            <div key={clase.id} className="p-6 hover:bg-gray-50 transition-colors">
                                <div className="flex items-center justify-between">
                                    <div className="flex-1">
                                        <h3 className="text-lg font-semibold text-gray-900">{clase.nombre}</h3>
                                        <div className="flex items-center space-x-4 mt-2 text-sm text-gray-600">
                                            <span>🕐 {clase.hora}</span>
                                            <span>👥 {clase.alumnos} alumnos</span>
                                            <span>📌 {clase.disciplina}</span>
                                        </div>
                                    </div>
                                    <button className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium">
                                        Marcar Asistencia
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </Layout>
    );
};

export default CoachDashboard;
