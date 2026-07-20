import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import ModalClase from '../../components/ModalClase';

const TURNOS = [
    { id: 'am', label: '🌅 Turno AM', desde: 7, hasta: 11 },
    { id: 'md', label: '☀️ Turno Medio Día', desde: 12, hasta: 17 },
    { id: 'pm', label: '🌆 Turno Tarde/Noche', desde: 18, hasta: 23 },
];

function parseHora(h) {
    if (!h) return -1;
    return parseInt(h.split(':')[0]) || -1;
}

const Clases = () => {
    const { tenant_id } = useAuth();
    const [clases, setClases] = useState([]);
    const [disciplinas, setDisciplinas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [claseEditar, setClaseEditar] = useState(null);
    const [filtroDisciplina, setFiltroDisciplina] = useState('');
    const [filtroTurno, setFiltroTurno] = useState('');

    const fetchDisciplinas = useCallback(async () => {
        try {
            const r = await api.get('/api/v1/disciplinas', { params: { tenant_id } });
            setDisciplinas(r.data || []);
        } catch (e) { console.error(e); }
    }, [tenant_id]);

    const fetchClases = async (disciplinaId, turnoId) => {
        setLoading(true);
        try {
            const params = { tenant_id, limit: 500 };
            if (disciplinaId) params.disciplina_id = disciplinaId;
            const response = await api.get('/api/v1/clases', { params });
            let data = response.data || [];
            if (turnoId) {
                const turno = TURNOS.find(t => t.id === turnoId);
                if (turno) data = data.filter(c => { const h = parseHora(c.hora_inicio); return h >= turno.desde && h <= turno.hasta; });
            }
            setClases(data);
        } catch (error) {
            console.error('Error fetching clases:', error);
            setClases([]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchDisciplinas();
        fetchClases('', '');
    }, [tenant_id]);

    useEffect(() => {
        fetchClases(filtroDisciplina, filtroTurno);
    }, [filtroDisciplina, filtroTurno]);

    const getOccupancyColor = (inscritos, cupo) => {
        const percentage = ((inscritos || 0) / (cupo || 1)) * 100;
        if (percentage >= 90) return 'bg-red-100 text-red-800';
        if (percentage >= 70) return 'bg-yellow-100 text-yellow-800';
        return 'bg-green-100 text-green-800';
    };

    const handleNuevaClase = () => {
        setClaseEditar(null);
        setShowModal(true);
    };

    const handleEditarClase = (clase) => {
        setClaseEditar(clase);
        setShowModal(true);
    };

    const handleEliminarClase = async (claseId) => {
        if (!window.confirm('¿Estás seguro de eliminar esta clase?')) return;
        try {
            await api.delete(`/api/v1/clases/${claseId}?tenant_id=${tenant_id}`);
            fetchClases();
        } catch (error) {
            console.error('Error eliminando clase:', error);
            alert('Error al eliminar la clase. Intente nuevamente.');
        }
    };

    const handleModalClose = () => {
        setShowModal(false);
        setClaseEditar(null);
    };

    const handleModalSuccess = () => {
        setShowModal(false);
        setClaseEditar(null);
        fetchClases();
    };

    if (loading && clases.length === 0) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4"></div>
                        <p className="text-gray-600">Cargando clases...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">Gestión de Clases</h1>
                    <p className="text-gray-600 mt-1">Administra el calendario de clases de tu box</p>
                </div>

                {/* Filtros */}
                <div className="bg-white rounded-lg shadow p-4 flex flex-wrap gap-4 items-center">
                    <div>
                        <label className="text-xs font-medium text-gray-600 block mb-1">Disciplina</label>
                        <select value={filtroDisciplina} onChange={e => setFiltroDisciplina(e.target.value)} className="border rounded px-3 py-1.5 text-sm">
                            <option value="">Todas</option>
                            {disciplinas.map(d => <option key={d.id} value={d.id}>{d.nombre}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="text-xs font-medium text-gray-600 block mb-1">Turno</label>
                        <select value={filtroTurno} onChange={e => setFiltroTurno(e.target.value)} className="border rounded px-3 py-1.5 text-sm">
                            <option value="">Todos</option>
                            {TURNOS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
                        </select>
                    </div>
                    <div className="text-sm text-gray-500 self-end pb-1">
                        {clases.length} clase{clases.length !== 1 ? 's' : ''} encontrada{clases.length !== 1 ? 's' : ''}
                    </div>
                </div>

                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-gray-200">
                        <div className="flex items-center justify-between">
                            <h2 className="text-lg font-bold text-gray-900">Clases Programadas</h2>
                            <button onClick={handleNuevaClase} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium text-sm">+ Nueva Clase</button>
                        </div>
                    </div>

                    {/* Tabla responsiva */}
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Clase</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Disciplina</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Fecha</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Hora</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Coach</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Ocupación</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {clases.length > 0 ? (
                                    clases.map((clase, index) => (
                                        <tr key={clase.id || `clase-${index}`} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                            <td className="px-6 py-4 text-sm font-medium text-gray-900">
                                                {clase.disciplina_nombre || 'Sin disciplina'} — {clase.hora_inicio?.slice(0, 5) || '00:00'} a {clase.hora_fin?.slice(0, 5) || '00:00'}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-600">
                                                <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
                                                    {clase.disciplina_nombre || 'Sin disciplina'}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-600">{clase.fecha || 'Sin fecha'}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600 font-medium">
                                                {clase.hora_inicio?.slice(0, 5) || '00:00'}
                                            </td>
                                            <td className="px-6 py-4 text-sm">
                                                <span className={`px-2 py-1 rounded text-xs font-medium ${!clase.coach_nombre ? (clase.disciplina_nombre === 'CrossFit' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-500') : 'bg-green-100 text-green-800'}`}>
                                                    {clase.coach_nombre || (clase.disciplina_nombre === 'CrossFit' ? '⚠️ Pendiente' : 'Sin asignar')}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 text-sm">
                                                <div className="flex items-center space-x-2">
                                                    <span
                                                        className={`px-3 py-1 rounded-full text-xs font-medium ${getOccupancyColor(
                                                            clase.asistentes_confirmados || 0,
                                                            clase.cupo_maximo || 1
                                                        )}`}
                                                    >
                                                        {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || 0}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 text-sm space-x-2">
                                                <button
                                                    onClick={() => handleEditarClase(clase)}
                                                    className="px-3 py-1 text-blue-600 hover:bg-blue-50 rounded transition-colors text-xs font-medium"
                                                >
                                                    Editar
                                                </button>
                                                <button
                                                    onClick={() => handleEliminarClase(clase.id)}
                                                    className="px-3 py-1 text-red-600 hover:bg-red-50 rounded transition-colors text-xs font-medium"
                                                >
                                                    Eliminar
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                ) : (
                                    <tr>
                                        <td colSpan="7" className="px-6 py-8 text-center text-gray-600">
                                            No hay clases programadas
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>

                    {/* Footer */}
                    <div className="px-6 py-4 bg-gray-50 border-t border-gray-200">
                        <p className="text-sm text-gray-600">
                            Total de clases: <span className="font-bold text-gray-900">{clases.length}</span>
                        </p>
                    </div>
                </div>

                <ModalClase
                    isOpen={showModal}
                    onClose={handleModalClose}
                    onSuccess={handleModalSuccess}
                    tenant_id={tenant_id}
                    claseEditar={claseEditar}
                />
            </div>
        </Layout>
    );
};

export default Clases;
