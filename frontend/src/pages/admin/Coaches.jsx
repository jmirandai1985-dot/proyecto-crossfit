import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Coaches = () => {
    const { tenant_id } = useAuth();
    const [coaches, setCoaches] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [editingCoach, setEditingCoach] = useState(null);
    const [disciplinas, setDisciplinas] = useState([]);
    const [errorCoaches, setErrorCoaches] = useState('');
    const [errorDisciplinas, setErrorDisciplinas] = useState('');
    const [errorAsignaciones, setErrorAsignaciones] = useState('');
    const [asignacionesListas, setAsignacionesListas] = useState(false);
    const [msgOperacion, setMsgOperacion] = useState(null);
    const [confirmarEliminar, setConfirmarEliminar] = useState(null);
    const [coachDisciplinasMap, setCoachDisciplinasMap] = useState({});
    const [formData, setFormData] = useState({
        nombre: '',
        correo: '',
        password: '',
        disciplina_ids: [],
        estado: 'activo',
    });

    const fetchCoaches = async () => {
        try {
            const response = await api.get('/api/v1/usuarios', { params: { rol: 'coach' } });
            setCoaches(response.data || []);
        } catch (error) {
            console.error('Error fetching coaches:', error); setErrorCoaches('No se pudieron cargar los coaches. Reintenta.');
            setCoaches([]);
        } finally {
            setLoading(false);
        }
    };

    const fetchDisciplinas = async () => {
        try {
            const r = await api.get('/api/v1/disciplinas');
            setDisciplinas(r.data?.filter(d => d.activo !== false) || []);
        } catch (e) { console.error(e); setErrorDisciplinas('No se pudieron cargar las disciplinas.'); }
    };

    const fetchCoachDisciplinas = async () => {
        try {
            const r = await api.get('/api/v1/coach-disciplinas', { params: { limit: 500 } });
            const data = r.data || [];
            const map = {};
            data.forEach(cd => {
                if (cd.activo) {
                    if (!map[cd.coach_id]) map[cd.coach_id] = [];
                    map[cd.coach_id].push(cd.disciplina_id);
                }
            });
            setCoachDisciplinasMap(map);
        setAsignacionesListas(true);
        setErrorAsignaciones('');
        } catch (e) { console.error(e); setErrorAsignaciones('No se pudieron cargar las asignaciones del coach.'); setAsignacionesListas(false); }
    };

    useEffect(() => {
        fetchCoaches();
        fetchDisciplinas();
        fetchCoachDisciplinas();
    }, [tenant_id]);

    const openModal = (coach = null) => {
        if (coach && !asignacionesListas) { setErrorAsignaciones('No se pudieron cargar las asignaciones del coach: la edicion esta bloqueada hasta que carguen. Reintenta.'); return; }
        if (coach) {
            setEditingCoach(coach);
            setFormData({
                nombre: coach.nombre,
                correo: coach.correo,
                password: '',
                disciplina_ids: coachDisciplinasMap[coach.id] || [],
                estado: coach.activo ? 'activo' : 'inactivo',
            });
        } else {
            setEditingCoach(null);
            setFormData({ nombre: '', correo: '', password: '', disciplina_ids: [], estado: 'activo' });
        }
        setShowModal(true);
    };

    const closeModal = () => {
        setShowModal(false);
        setEditingCoach(null);
        setFormData({ nombre: '', correo: '', password: '', disciplina_ids: [], estado: 'activo' });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!asignacionesListas) { setErrorAsignaciones('No se pudieron cargar las asignaciones actuales del coach. Para no borrar sus disciplinas, no se guarda. Reintenta la carga.'); return; }
        setMsgOperacion(null);
        try {
            let coachId;
            if (editingCoach) {
                await api.put(`/api/v1/usuarios/${editingCoach.id}`, {
                    nombre: formData.nombre,
                    correo: formData.correo,
                    activo: formData.estado === 'activo',
                });
                coachId = editingCoach.id;
            } else {
                const res = await api.post('/api/v1/usuarios', {
                    nombre: formData.nombre,
                    correo: formData.correo,
                    password: formData.password,
                    rol: 'coach',
                    rut: 'TEMP-' + Date.now().toString().slice(-7), // PLACEHOLDER temporal: RUT unico por coach (backend exige rut 7-12 chars, no lo pide el form todavia)
                    tenant_id: tenant_id,
                });
                coachId = res.data.id;
            }

            // Asignar disciplinas en coach_disciplinas
            if (coachId) {
                await api.put('/api/v1/coach-disciplinas/reemplazar', {
                    tenant_id: tenant_id,
                    coach_id: coachId,
                    disciplina_ids: formData.disciplina_ids,
                });
            }

            setMsgOperacion({ tipo: 'exito', texto: 'Coach guardado' });
            fetchCoaches();
            fetchCoachDisciplinas();
        } catch (error) {
            setMsgOperacion({ tipo: 'error', texto: error.response?.data?.detail || error.message });
        }
    };

    const handleDelete = async (coach) => {
        if (!window.confirm(`¿Estás seguro de eliminar a ${coach.nombre}?`)) return;
        try {
            await api.delete(`/api/v1/usuarios/${coach.id}`);
            setCoaches(coaches.filter((c) => c.id !== coach.id));
        } catch (error) {
            setMsgOperacion({ tipo: 'error', texto: error.response?.data?.detail || 'No se pudo desactivar' });
        }
    };

    const toggleDisciplina = (discId) => {
        setFormData(prev => ({
            ...prev,
            disciplina_ids: prev.disciplina_ids.includes(discId)
                ? prev.disciplina_ids.filter(id => id !== discId)
                : [...prev.disciplina_ids, discId],
        }));
    };

    const getDisciplinaNombre = (discId) => {
        const disc = disciplinas.find(d => d.id === discId);
        return disc ? disc.nombre : `ID ${discId}`;
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                        <p className="text-zinc-400">Cargando coaches...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    // Desactivacion (soft delete en el backend): la confirmacion vive en el modal propio.
    const desactivarConfirmado = async () => {
        const coach = confirmarEliminar;
        setConfirmarEliminar(null);
        try {
            await api.delete(`/api/v1/usuarios/${coach.id}`);
            setCoaches(coaches.filter((c) => c.id !== coach.id));
            setMsgOperacion({ tipo: 'exito', texto: 'Coach desactivado' });
        } catch (error) {
            setMsgOperacion({ tipo: 'error', texto: error.response?.data?.detail || 'No se pudo desactivar el coach' });
        }
    };

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-zinc-100">Gestión de Coaches</h1><p className="text-zinc-400 mt-1">Administra los entrenadores de tu box</p></div>
                    <button onClick={() => openModal()} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Agregar Coach</button>
                </div>

                {errorCoaches && (
                    <div className="border-l-4 rounded-lg p-4 text-sm bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-3">
                        <span>{errorCoaches}</span>
                        <button onClick={fetchCoaches} className="px-3 py-1.5 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                    </div>
                )}
                {errorAsignaciones && (
                    <div className="border-l-4 rounded-lg p-4 text-sm bg-orange-500/10 border-orange-500 text-orange-300 flex items-center justify-between gap-3">
                        <span>{errorAsignaciones} Mientras no carguen, la edicion de coaches esta bloqueada.</span>
                        <button onClick={fetchCoachDisciplinas} className="px-3 py-1.5 bg-orange-500 text-white rounded text-xs font-medium hover:bg-orange-600">Reintentar</button>
                    </div>
                )}
                {errorDisciplinas && (
                    <div className="border-l-4 rounded-lg p-4 text-sm bg-amber-500/10 border-amber-500 text-amber-300 flex items-center justify-between gap-3">
                        <span>{errorDisciplinas}</span>
                        <button onClick={fetchDisciplinas} className="px-3 py-1.5 bg-amber-600 text-white rounded text-xs font-medium hover:bg-amber-700">Reintentar</button>
                    </div>
                )}
                {msgOperacion && (
                    <div className={`border-l-4 rounded-lg p-4 text-sm ${msgOperacion.tipo === 'exito' ? 'bg-green-500/10 border-green-500 text-green-300' : 'bg-red-500/10 border-red-500 text-red-300'}`}>
                        {msgOperacion.texto}
                    </div>
                )}

                {/* Estadísticas */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div className="bg-zinc-900 rounded-lg shadow p-6 border-l-4 border-blue-500">
                        <p className="text-zinc-400 text-sm font-medium">Total de Coaches</p>
                        <p className="text-3xl font-bold text-zinc-100 mt-2">{coaches.length}</p>
                    </div>
                    <div className="bg-zinc-900 rounded-lg shadow p-6 border-l-4 border-green-500">
                        <p className="text-zinc-400 text-sm font-medium">Coaches Activos</p>
                        <p className="text-3xl font-bold text-zinc-100 mt-2">{coaches.filter((c) => c.activo !== false).length}</p>
                    </div>
                    <div className="bg-zinc-900 rounded-lg shadow p-6 border-l-4 border-orange-500">
                        <p className="text-zinc-400 text-sm font-medium">Disciplinas Asignadas</p>
                        <p className="text-3xl font-bold text-zinc-100 mt-2">{new Set(Object.values(coachDisciplinasMap).flat()).size}</p>
                    </div>
                </div>

                {/* Grid de tarjetas */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {coaches.length > 0 ? (
                        coaches.map((coach) => {
                            const discIds = coachDisciplinasMap[coach.id] || [];
                            return (
                                <div key={coach.id} className="bg-zinc-900 rounded-lg shadow hover:shadow-lg transition-shadow overflow-hidden">
                                    <div className="bg-gradient-to-r from-blue-900 to-blue-800 px-6 py-4">
                                        <div className="flex items-center justify-between">
                                            <div>
                                                <h3 className="text-lg font-bold text-white">{coach.nombre}</h3>
                                                <p className="text-blue-100 text-sm">
                                                    {discIds.length > 0
                                                        ? discIds.map(id => getDisciplinaNombre(id)).join(', ')
                                                        : 'Sin disciplinas asignadas'}
                                                </p>
                                            </div>
                                            <span className="text-3xl">🏋️</span>
                                        </div>
                                    </div>
                                    <div className="px-6 py-4 space-y-4">
                                        <div className="flex items-center space-x-3">
                                            <span className="text-zinc-500">📧</span>
                                            <div>
                                                <p className="text-xs text-zinc-400">Correo</p>
                                                <p className="text-sm text-zinc-100 font-medium">{coach.correo}</p>
                                            </div>
                                        </div>
                                        {discIds.length > 0 && (
                                            <div className="flex flex-wrap gap-1.5">
                                                {discIds.map(id => (
                                                    <span key={id} className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700">
                                                        {getDisciplinaNombre(id)}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                        <div className="pt-2 border-t border-zinc-800">
                                            <span className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${coach.activo !== false ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                                {coach.activo !== false ? '✓ Activo' : '✗ Inactivo'}
                                            </span>
                                        </div>
                                    </div>
                                    <div className="px-6 py-4 bg-zinc-800/50 border-t border-zinc-800 flex gap-2">
                                        <button onClick={() => openModal(coach)} disabled={!asignacionesListas} className="flex-1 px-3 py-2 text-blue-400 hover:bg-zinc-800 rounded text-sm font-medium">Editar</button>
                                        <button onClick={() => setConfirmarEliminar(coach)} className="flex-1 px-3 py-2 text-red-600 hover:bg-red-50 rounded text-sm font-medium">Desactivar</button>
                                    </div>
                                </div>
                            );
                        })
                    ) : (
                        <div className="col-span-full text-center py-12"><p className="text-zinc-400 text-lg">No hay coaches registrados</p></div>
                    )}
                </div>

                {showModal && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full">
                            <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                                <h2 className="text-xl font-bold">{editingCoach ? 'Editar Coach' : 'Nuevo Coach'}</h2>
                            </div>
                            <form onSubmit={handleSubmit} className="p-6 space-y-4">
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Nombre Completo</label>
                                    <input type="text" value={formData.nombre} onChange={e => setFormData({ ...formData, nombre: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Correo Electrónico</label>
                                    <input type="email" value={formData.correo} onChange={e => setFormData({ ...formData, correo: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg" required />
                                </div>
                                {!editingCoach && (
                                    <div>
                                        <label className="block text-sm font-medium text-zinc-300 mb-1">Contraseña</label>
                                        <input type="password" value={formData.password} onChange={e => setFormData({ ...formData, password: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg" required />
                                    </div>
                                )}
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-2">Disciplinas Asignadas</label>
                                    <div className="space-y-2 max-h-48 overflow-y-auto border border-zinc-800 rounded-lg p-3">
                                        {disciplinas.length === 0 && (
                                            <p className="text-sm text-zinc-500 italic">No hay disciplinas activas</p>
                                        )}
                                        {disciplinas.map(d => (
                                            <label key={d.id} className="flex items-center gap-2 cursor-pointer hover:bg-zinc-800/50 p-1.5 rounded">
                                                <input
                                                    type="checkbox"
                                                    checked={formData.disciplina_ids.includes(d.id)}
                                                    onChange={() => toggleDisciplina(d.id)}
                                                    className="rounded border-zinc-700 text-orange-500 focus:ring-orange-500"
                                                />
                                                <span className="text-sm text-zinc-300">{d.nombre}</span>
                                            </label>
                                        ))}
                                    </div>
                                </div>
                                {editingCoach && (
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Estado</label>
                                    <select value={formData.estado} onChange={e => setFormData({ ...formData, estado: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg">
                                        <option value="activo">Activo</option>
                                        <option value="inactivo">Inactivo</option>
                                    </select>
                                </div>
                                )}
                                {!editingCoach && (
                                    <p className="text-xs text-zinc-500">Al crear, el coach queda activo. El estado se edita despues.</p>
                                )}
                                <div className="flex gap-3 pt-4">
                                    <button type="button" onClick={closeModal} className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium">Cancelar</button>
                                    <button type="submit" disabled={!asignacionesListas} className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium">{editingCoach ? 'Actualizar' : 'Crear'}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
                {confirmarEliminar && (
                    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6">
                            <h2 className="text-xl font-bold text-zinc-100 mb-3">Desactivar coach</h2>
                            <p className="text-sm text-zinc-300 mb-5">Confirma desactivar a {confirmarEliminar.nombre}? Dejara de aparecer como activo (no se borra su historial).</p>
                            <div className="flex gap-3">
                                <button onClick={() => setConfirmarEliminar(null)} className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium">Cancelar</button>
                                <button onClick={desactivarConfirmado} className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium">Desactivar</button>
                            </div>
                        </div>
                    </div>
                )}
        </Layout>
    );
};

export default Coaches;