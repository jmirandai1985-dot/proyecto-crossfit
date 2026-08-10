import React, { useState, useEffect } from 'react';
import api from '../services/api';

/**
 * Modal de ficha completa de un alumno (reutilizable).
 * Carga el detalle real del usuario + suscripción activa + plan.
 *
 * Props:
 *   - alumnoId: ID del alumno a mostrar
 *   - tenantId: ID del tenant (box)
 *   - onClose: callback al cerrar el modal
 */
const AlumnoFichaModal = ({ alumnoId, tenantId, onClose }) => {
    const [data, setData] = useState(null);
    const [suscripcion, setSuscripcion] = useState(null);
    const [planes, setPlanes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        if (!alumnoId) return;
        setLoading(true);
        setError('');
        const carga = async () => {
            try {
                const [usrRes, susRes, planesRes] = await Promise.all([
                    api.get(`/api/v1/usuarios/${alumnoId}`),
                    api.get('/api/v1/suscripciones', {
                        params: { tenant_id: tenantId, usuario_id: alumnoId, estado: 'activo' }
                    }),
                    api.get('/api/v1/planes', {
                        params: { tenant_id: tenantId, activo: true }
                    })
                ]);
                setData(usrRes.data || {});
                setSuscripcion((susRes.data || [])[0] || null);
                setPlanes(Array.isArray(planesRes.data) ? planesRes.data : []);
            } catch (e) {
                setError(e.response?.data?.detail || e.message || 'Error al cargar el alumno');
            } finally {
                setLoading(false);
            }
        };
        carga();
    }, [alumnoId, tenantId]);

    if (!alumnoId) return null;

    const fmtFecha = (valor) => {
        if (!valor) return '—';
        const d = new Date(valor);
        if (isNaN(d.getTime())) return valor;
        return d.toLocaleDateString('es-CL');
    };

    const planActivo = planes.find(p => p.id === suscripcion?.plan_id);

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
            onClick={onClose}>
            <div className="bg-zinc-900 rounded-xl max-w-lg w-full max-h-[90vh] overflow-auto shadow-2xl border border-zinc-700"
                onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="p-4 border-b border-zinc-700 flex justify-between items-center">
                    <h3 className="font-bold text-zinc-100">👤 Ficha del Alumno</h3>
                    <button onClick={onClose}
                        className="text-zinc-400 hover:text-zinc-200 text-xl font-bold">✕</button>
                </div>

                <div className="p-5 space-y-5">
                    {loading ? (
                        <div className="flex justify-center py-10">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                        </div>
                    ) : error ? (
                        <p className="text-center text-red-400 py-6 text-sm">{error}</p>
                    ) : data ? (
                        <>
                            {/* Nombre + estado */}
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xl font-bold text-zinc-100">{data.nombre || '—'}</p>
                                    <p className="text-sm text-zinc-400">{data.correo || '—'}</p>
                                </div>
                                <span className={`px-3 py-1 rounded-full text-xs font-bold ${data.activo ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                    {data.activo ? 'Activo' : 'Inactivo'}
                                </span>
                            </div>

                            {/* Datos personales */}
                            <div className="bg-zinc-800/50 rounded-lg p-4 space-y-2">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Datos personales</p>
                                <div className="grid grid-cols-2 gap-3 text-sm">
                                    <div>
                                        <p className="text-xs text-zinc-500">RUT</p>
                                        <p className="text-zinc-200">{data.rut || '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-zinc-500">Teléfono</p>
                                        <p className="text-zinc-200">{data.telefono || '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-zinc-500">Fecha de nacimiento</p>
                                        <p className="text-zinc-200">{data.fecha_nacimiento ? fmtFecha(data.fecha_nacimiento) : '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-zinc-500">Género</p>
                                        <p className="text-zinc-200">{data.genero || '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-zinc-500">Peso</p>
                                        <p className="text-zinc-200">{data.peso_kg ? `${data.peso_kg} kg` : '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-zinc-500">Estatura</p>
                                        <p className="text-zinc-200">{data.estatura_cm ? `${data.estatura_cm} cm` : '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-zinc-500">Fecha de registro</p>
                                        <p className="text-zinc-200">{data.created_at ? fmtFecha(data.created_at) : '—'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-zinc-500">Rol</p>
                                        <p className="text-zinc-200 capitalize">{data.rol || '—'}</p>
                                    </div>
                                </div>
                            </div>

                            {/* Membresía activa */}
                            <div className="bg-zinc-800/50 rounded-lg p-4 space-y-2">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Membresía activa</p>
                                {!suscripcion ? (
                                    <p className="text-sm text-zinc-500">Sin plan activo</p>
                                ) : (
                                    <div className="grid grid-cols-2 gap-3 text-sm">
                                        <div>
                                            <p className="text-xs text-zinc-500">Plan</p>
                                            <p className="text-zinc-200 font-medium">{planActivo ? planActivo.nombre : `Plan ID ${suscripcion.plan_id}`}</p>
                                        </div>
                                        <div>
                                            <p className="text-xs text-zinc-500">Créditos disponibles</p>
                                            <p className="text-zinc-200 font-medium">
                                                {suscripcion.creditos_disponibles === null || suscripcion.creditos_disponibles === undefined
                                                    ? <span className="text-orange-500">∞</span>
                                                    : suscripcion.creditos_disponibles}
                                            </p>
                                        </div>
                                        <div>
                                            <p className="text-xs text-zinc-500">Vence el</p>
                                            <p className="text-zinc-200">{suscripcion.fecha_expiracion ? fmtFecha(suscripcion.fecha_expiracion) : '—'}</p>
                                        </div>
                                        <div>
                                            <p className="text-xs text-zinc-500">Estado</p>
                                            <p className="text-zinc-200 capitalize">{suscripcion.estado || '—'}</p>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </>
                    ) : (
                        <p className="text-center text-zinc-500 py-6 text-sm">Alumno no encontrado</p>
                    )}
                </div>

                {/* Footer */}
                <div className="p-4 border-t border-zinc-700 flex justify-end">
                    <button onClick={onClose}
                        className="px-4 py-2 bg-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-600 text-sm font-bold">
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    );
};

export default AlumnoFichaModal;

