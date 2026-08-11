import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import api from '../../services/api';

const AdminAlumnosPendientes = () => {
    const [pendientes, setPendientes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [actionId, setActionId] = useState(null);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');

    const cargarPendientes = async () => {
        try {
            setLoading(true);
            const { data } = await api.get('/api/v1/alumnos/pendientes-activacion');
            setPendientes(data || []);
            setError('');
        } catch (err) {
            setError(err.response?.data?.detail || 'No se pudieron cargar las solicitudes');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        cargarPendientes();
    }, []);

    const handleAccion = async (alumnoId, accion) => {
        setActionId(alumnoId);
        setMessage('');
        setError('');
        try {
            await api.put(`/api/v1/alumnos/${alumnoId}/${accion}`);
            setMessage(accion === 'activar'
                ? 'Alumno activado y credenciales enviadas por correo'
                : 'Solicitud rechazada');
            cargarPendientes();
        } catch (err) {
            setError(err.response?.data?.detail || 'Ocurrió un error al procesar la solicitud');
        } finally {
            setActionId(null);
        }
    };

    return (
        <Layout>
            <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-2xl font-bold text-white">Alumnos Pendientes de Activación</h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            Solicitudes de registro de alumnos nuevos que esperan tu revisión
                        </p>
                    </div>
                    <button
                        onClick={cargarPendientes}
                        className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm transition-colors"
                    >
                        ⟳ Refrescar
                    </button>
                </div>

                {message && (
                    <div className="mb-4 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm">
                        ✅ {message}
                    </div>
                )}
                {error && (
                    <div className="mb-4 bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                        {error}
                    </div>
                )}

                {loading ? (
                    <div className="flex items-center justify-center py-20">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500" />
                    </div>
                ) : pendientes.length === 0 ? (
                    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-10 text-center">
                        <p className="text-3xl mb-3">🎉</p>
                        <p className="text-zinc-300 font-medium">No hay solicitudes pendientes</p>
                        <p className="text-zinc-500 text-sm mt-1">
                            Cuando un alumno nuevo se registre desde el login, su solicitud aparecerá aquí.
                        </p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                        {pendientes.map((p) => (
                            <div key={p.id} className="bg-zinc-900 border border-zinc-800 rounded-lg p-5 flex flex-col gap-3">
                                <div className="flex items-start justify-between">
                                    <div className="flex items-center gap-3">
                                        <div className="w-11 h-11 rounded-full bg-orange-500/20 border border-orange-500/40 flex items-center justify-center text-orange-400 font-bold text-lg">
                                            {(p.nombre || '?')[0]}
                                        </div>
                                        <div>
                                            <p className="text-white font-semibold">{p.nombre}</p>
                                            <p className="text-zinc-400 text-xs">{p.correo}</p>
                                        </div>
                                    </div>
                                    <span className="text-[10px] font-semibold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-1 rounded-full">
                                        Pendiente
                                    </span>
                                </div>

                                <div className="grid grid-cols-3 gap-2 text-center">
                                    <div className="bg-zinc-800 rounded-lg py-2">
                                        <p className="text-[10px] text-zinc-500 uppercase">RUT</p>
                                        <p className="text-white text-sm font-medium">{p.rut || '—'}</p>
                                    </div>
                                    <div className="bg-zinc-800 rounded-lg py-2">
                                        <p className="text-[10px] text-zinc-500 uppercase">Sexo</p>
                                        <p className="text-white text-sm font-medium">{p.genero === 'F' ? 'Femenino' : p.genero === 'M' ? 'Masculino' : '—'}</p>
                                    </div>
                                    <div className="bg-zinc-800 rounded-lg py-2">
                                        <p className="text-[10px] text-zinc-500 uppercase">Peso</p>
                                        <p className="text-white text-sm font-medium">{p.peso_kg ? `${p.peso_kg} kg` : '—'}</p>
                                    </div>
                                </div>



                                <p className="text-zinc-500 text-xs">
                                    Estatura: {p.estatura_cm ? `${p.estatura_cm} cm` : '—'}
                                    {p.fecha_registro ? ` · Solicitó el ${new Date(p.fecha_registro).toLocaleDateString('es-CL')}` : ''}
                                </p>

                                <div className="flex gap-2 mt-auto">
                                    <button
                                        onClick={() => handleAccion(p.id, 'activar')}
                                        disabled={actionId === p.id}
                                        className="flex-1 px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-sm font-semibold transition-colors"
                                    >
                                        {actionId === p.id ? 'Procesando...' : '✓ Activar'}
                                    </button>
                                    <button
                                        onClick={() => handleAccion(p.id, 'rechazar')}
                                        disabled={actionId === p.id}
                                        className="flex-1 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-red-500/20 border border-zinc-700 hover:border-red-500/40 text-zinc-300 hover:text-red-300 text-sm font-semibold transition-colors"
                                    >
                                        ✕ Rechazar
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default AdminAlumnosPendientes;
