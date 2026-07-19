import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import Layout from '../../components/Layout';
import api from '../../services/api';

const API_BASE = '/api/v1';

const TURNOS = [
    { id: 'am', label: '🌅 Turno AM', desde: 7, hasta: 11, horas: '07:00 - 11:59' },
    { id: 'md', label: '☀️ Turno Medio Día', desde: 12, hasta: 17, horas: '12:00 - 17:59' },
    { id: 'pm', label: '🌆 Turno Tarde/Noche', desde: 18, hasta: 23, horas: '18:00+' },
];

function parseHora(h) {
    if (!h) return -1;
    const partes = h.split(':');
    return parseInt(partes[0]) || -1;
}

function hoyStr() {
    return new Date().toISOString().split('T')[0];
}

export default function SupervisionClases() {
    const { tenant_id: authTenant } = useAuth();
    const tenant_id = authTenant || parseInt(localStorage.getItem('tenant_id') || '1');

    const [disciplinas, setDisciplinas] = useState([]);
    const [disciplinaActiva, setDisciplinaActiva] = useState(null);
    const [fecha, setFecha] = useState(hoyStr());
    const [clases, setClases] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // Cargar disciplinas
    useEffect(() => {
        api.get(`${API_BASE}/disciplinas`, { params: { tenant_id } })
            .then(r => {
                const data = r.data || [];
                setDisciplinas(data);
                if (data.length > 0 && !disciplinaActiva) {
                    setDisciplinaActiva(data[0].id);
                }
            })
            .catch(e => console.error('Error disciplinas', e));
    }, [tenant_id]);

    const cargarClases = useCallback(async (f, dId) => {
        setLoading(true);
        setError('');
        try {
            const r = await api.get(`${API_BASE}/clases`, {
                params: { tenant_id, disciplina_id: dId, fecha_desde: f, fecha_hasta: f, limit: 200 }
            });
            const data = r.data || [];
            const lista = Array.isArray(data) ? data : (data.clases || []);
            // Ordenar por hora
            lista.sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));
            setClases(lista);
        } catch (e) {
            console.error('Error clases', e);
            setError('Error al cargar clases');
            setClases([]);
        } finally {
            setLoading(false);
        }
    }, [tenant_id]);

    useEffect(() => {
        if (disciplinaActiva) {
            cargarClases(fecha, disciplinaActiva);
        }
    }, [fecha, disciplinaActiva, cargarClases]);

    const clasesPorTurno = (desde, hasta) => {
        return clases.filter(c => {
            const hora = parseHora(c.hora_inicio);
            return hora >= desde && hora <= hasta;
        });
    };

    const getOcupacionColor = (inscritos, cupo) => {
        const pct = ((inscritos || 0) / (cupo || 1)) * 100;
        if (pct >= 90) return 'bg-red-100 text-red-800 border-red-300';
        if (pct >= 70) return 'bg-yellow-100 text-yellow-800 border-yellow-300';
        return 'bg-green-100 text-green-800 border-green-300';
    };

    return (
        <Layout>
            <div className="p-6 max-w-7xl mx-auto">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Supervisión de Clases</h1>
                <p className="text-gray-500 mb-6">Vista general de la programación del box por disciplina y turno</p>

                {/* Fecha */}
                <div className="flex items-center gap-4 mb-6">
                    <label className="font-medium text-gray-700">Fecha:</label>
                    <input
                        type="date"
                        value={fecha}
                        onChange={e => setFecha(e.target.value)}
                        className="border rounded px-3 py-1.5 text-sm"
                    />
                    {fecha === hoyStr() && <span className="text-emerald-600 text-sm font-medium">• Hoy</span>}
                </div>

                {/* Pestañas de disciplinas */}
                <div className="flex gap-1 mb-6 border-b overflow-x-auto">
                    {disciplinas.map(d => (
                        <button
                            key={d.id}
                            onClick={() => setDisciplinaActiva(d.id)}
                            className={`px-4 py-2 font-medium rounded-t text-sm whitespace-nowrap transition-colors ${disciplinaActiva === d.id
                                ? 'bg-blue-900 text-white'
                                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                                }`}
                        >
                            {d.nombre}
                            {d.es_open_box && d.nombre !== "Open Box" && <span className="ml-1 text-xs">(Open Box)</span>}
                        </button>
                    ))}
                </div>

                {/* Contenido */}
                {loading ? (
                    <div className="flex items-center justify-center h-64">
                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-900"></div>
                    </div>
                ) : error ? (
                    <div className="p-4 bg-red-50 text-red-700 rounded-lg border border-red-200">{error}</div>
                ) : clases.length === 0 ? (
                    <div className="text-center py-16 text-gray-400">
                        <div className="text-5xl mb-4">📅</div>
                        <p className="text-lg">No hay clases programadas para esta disciplina en la fecha seleccionada</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        {TURNOS.map(turno => {
                            const clasesTurno = clasesPorTurno(turno.desde, turno.hasta);
                            return (
                                <div key={turno.id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                                    <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
                                        <div className="font-bold text-gray-800">{turno.label}</div>
                                        <div className="text-xs text-gray-500">{turno.horas}</div>
                                    </div>
                                    <div className="p-3 space-y-2 min-h-[200px]">
                                        {clasesTurno.length === 0 ? (
                                            <p className="text-gray-400 text-sm text-center py-8">Sin clases en este turno</p>
                                        ) : (
                                            clasesTurno.map(c => (
                                                <div key={c.id} className="border rounded-lg p-3 hover:shadow-md transition-shadow">
                                                    <div className="flex items-center justify-between mb-1">
                                                        <span className="font-bold text-blue-900 text-sm">
                                                            {c.hora_inicio?.slice(0, 5)} - {c.hora_fin?.slice(0, 5)}
                                                        </span>
                                                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${getOcupacionColor(c.asistentes_confirmados, c.cupo_maximo)}`}>
                                                            {c.asistentes_confirmados || 0}/{c.cupo_maximo || '?'}
                                                        </span>
                                                    </div>
                                                    <div className="text-xs text-gray-500">
                                                        Coach: {c.coach_nombre || 'Sin asignar'}
                                                    </div>
                                                    {c.wod_titulo && (
                                                        <div className="text-xs text-gray-600 mt-1 truncate">
                                                            WOD: {c.wod_titulo}
                                                        </div>
                                                    )}
                                                    {c.horario_base_id && (
                                                        <div className="text-xs text-gray-400 mt-1">
                                                            Horario #{c.horario_base_id}
                                                        </div>
                                                    )}
                                                </div>
                                            ))
                                        )}
                                    </div>
                                    <div className="bg-gray-50 px-4 py-2 border-t border-gray-200 text-xs text-gray-500 text-center">
                                        {clasesTurno.length} clase{clasesTurno.length !== 1 ? 's' : ''}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                {/* Resumen */}
                {!loading && clases.length > 0 && (
                    <div className="mt-6 bg-white rounded-lg border border-gray-200 p-4 text-sm text-gray-600">
                        <span className="font-medium">Total para hoy:</span>{' '}
                        {clases.length} clases en {TURNOS.filter(t => clasesPorTurno(t.desde, t.hasta).length > 0).length} turnos
                    </div>
                )}
            </div>
        </Layout>
    );
}