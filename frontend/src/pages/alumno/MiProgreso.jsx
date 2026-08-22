import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import api from '../../services/api';

// ─── Niveles de hito (1/3/6/12 meses consecutivos) ───────────────────────────
const NIVELES = { 1: '🔥', 3: '🔥🔥', 6: '🔥🔥🔥', 12: '🏆' };
const NOMBRES = {
    1: 'Primer mes completo',
    3: '3 meses de racha',
    6: '6 meses de racha',
    12: 'Un año de leyenda',
};

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

const formatearMes = (iso) => {
    if (!iso) return '—';
    const [a, m] = String(iso).slice(0, 10).split('-');
    const mes = parseInt(m, 10);
    return `${MESES[mes - 1] || m} ${a}`;
};

const MiProgreso = () => {
    const [resumen, setResumen] = useState(null);
    const [hitos, setHitos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        Promise.all([
            api.get('/api/v1/asistencia/mi-resumen'),
            api.get('/api/v1/asistencia/mis-hitos'),
        ])
            .then(([rResumen, rHitos]) => {
                setResumen(rResumen.data);
                setHitos(rHitos.data?.hitos || []);
            })
            .catch((err) => {
                console.error('Error cargando mi progreso:', err);
                setError('No se pudo cargar tu progreso. Intentalo de nuevo más tarde.');
            })
            .finally(() => setLoading(false));
    }, []);

    if (loading) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>);
    }

    const mes = resumen?.mes_en_curso || {};
    const racha = resumen?.racha_actual ?? 0;
    const proximo = resumen?.proximo_hito ?? null;
    const hitosList = (resumen?.hitos_alcanzados?.length ? resumen.hitos_alcanzados : hitos) || [];

    return (
        <Layout>
            <div className="max-w-6xl mx-auto">
                <div className="flex items-center gap-3 mb-6">
                    <span className="text-3xl">📈</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Mi Progreso</h1>
                        <p className="text-sm text-gray-500">Tu constancia en el box</p>
                    </div>
                </div>

                {error && (
                    <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-4 mb-6">{error}</div>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                    {/* Racha actual */}
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
                        <p className="text-sm text-gray-500 uppercase tracking-wide font-semibold mb-2">Racha actual</p>
                        <div className="flex items-end gap-2">
                            <span className="text-5xl font-bold text-emerald-600">{racha}</span>
                            <span className="text-gray-400 mb-1">{racha === 1 ? 'mes' : 'meses'} consecutivos al 100%</span>
                        </div>
                        {proximo ? (
                            <p className="text-sm text-gray-500 mt-3">
                                Próximo hito: <strong className="text-gray-800">{NIVELES[proximo] || '🎖️'} {proximo} meses</strong>
                            </p>
                        ) : (
                            <p className="text-sm text-emerald-600 mt-3">¡Llegaste al nivel máximo! 🏆</p>
                        )}
                    </div>

                    {/* Cumplimiento del mes en curso */}
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
                        <p className="text-sm text-gray-500 uppercase tracking-wide font-semibold mb-2">Cumplimiento del mes actual</p>
                        <div className="flex items-end gap-2">
                            <span className="text-5xl font-bold text-gray-800">{mes.pct ?? 0}%</span>
                            <span className="text-gray-400 mb-1">de asistencia</span>
                        </div>
                        {mes.total_reservadas > 0 ? (
                            <p className="text-sm text-gray-500 mt-3">
                                Asististe a <strong className="text-gray-800">{mes.asistidas} de {mes.total_reservadas}</strong> clases reservadas.
                            </p>
                        ) : (
                            <p className="text-sm text-gray-500 mt-3">Sin clases reservadas este mes aún.</p>
                        )}
                    </div>
                </div>

                {/* Hitos alcanzados */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                    <div className="px-6 py-4 border-b border-gray-100">
                        <h2 className="font-bold text-gray-800 text-xl">🏅 Tus hitos</h2>
                    </div>
                    {hitosList.length === 0 ? (
                        <div className="p-10 text-center">
                            <span className="text-6xl block mb-4">🥉</span>
                            <p className="text-gray-500">Todavía no alcanzaste hitos.</p>
                            <p className="text-sm text-gray-400 mt-1">Cada mes con asistencia perfecta suma a tu racha.</p>
                        </div>
                    ) : (
                        <div className="divide-y divide-gray-100">
                            {hitosList.map((h) => (
                                <div key={h.nivel} className="flex items-center justify-between px-6 py-4">
                                    <div className="flex items-center gap-3">
                                        <span className="text-2xl">{NIVELES[h.nivel] || '🎖️'}</span>
                                        <div>
                                            <p className="font-bold text-gray-800">{NOMBRES[h.nivel] || `${h.nivel} meses de racha`}</p>
                                            <p className="text-xs text-gray-400">
                                                {h.meses_consecutivos} meses consecutivos · alcanzado en {formatearMes(h.mes_alcanzado)}
                                            </p>
                                        </div>
                                    </div>
                                    <span className="text-xs font-bold text-emerald-600 bg-emerald-50 px-3 py-1 rounded-full">Logrado</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </Layout>
    );
};

export default MiProgreso;

