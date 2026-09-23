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
    // Error POR BLOQUE: antes un Promise.all hacia que el fallo de UN fetch (p. ej.
    // /planes) dejara la ficha entera en blanco con un unico mensaje. Ahora cada
    // bloque se resuelve por separado (Promise.allSettled) y muestra su propio error.
    const [errores, setErrores] = useState({ usuario: '', suscripcion: '', planes: '' });

    useEffect(() => {
        if (!alumnoId) return;
        setLoading(true);
        setErrores({ usuario: '', suscripcion: '', planes: '' });
        const carga = async () => {
            const [usrRes, susRes, planesRes] = await Promise.allSettled([
                api.get(`/api/v1/usuarios/${alumnoId}`),
                api.get('/api/v1/suscripciones', {
                    params: { usuario_id: alumnoId, estado: 'activo' }
                }),
                api.get('/api/v1/planes', {
                    params: { activo: true }
                })
            ]);
            const detalle = (r) => r.reason?.response?.data?.detail
                || r.reason?.message || 'No se pudo cargar';

            if (usrRes.status === 'fulfilled') {
                setData(usrRes.value.data || {});
            } else {
                console.error('Ficha alumno: fallo /usuarios', usrRes.reason);
                setData(null);
                setErrores(prev => ({ ...prev, usuario: detalle(usrRes) }));
            }
            if (susRes.status === 'fulfilled') {
                setSuscripcion((susRes.value.data || [])[0] || null);
            } else {
                console.error('Ficha alumno: fallo /suscripciones', susRes.reason);
                setSuscripcion(null);
                setErrores(prev => ({ ...prev, suscripcion: detalle(susRes) }));
            }
            if (planesRes.status === 'fulfilled') {
                setPlanes(Array.isArray(planesRes.value.data) ? planesRes.value.data : []);
            } else {
                console.error('Ficha alumno: fallo /planes', planesRes.reason);
                setPlanes([]);
                setErrores(prev => ({ ...prev, planes: detalle(planesRes) }));
            }
            setLoading(false);
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

    // Estado del registro: la fuente de verdad es usuarios.estado
    // ('pendiente_activacion' | 'activo' | 'rechazado'); `activo` es el flag
    // heredado. Si se contradicen se muestra el conflicto, no un badge verde.
    const etiquetaEstado = (d) => {
        const est = String(d.estado || '').toLowerCase();
        if (est === 'pendiente_activacion') {
            return { texto: 'Pendiente de activación', clase: 'bg-amber-100 text-amber-800' };
        }
        if (est === 'rechazado') {
            return { texto: 'Rechazado', clase: 'bg-red-100 text-red-800' };
        }
        if (est === 'activo' && !d.activo) {
            return { texto: 'Inactivo (estado: activo)', clase: 'bg-red-100 text-red-800' };
        }
        if (est === 'activo' || d.activo) {
            return { texto: 'Activo', clase: 'bg-green-100 text-green-800' };
        }
        return { texto: 'Inactivo', clase: 'bg-red-100 text-red-800' };
    };

    const planActivo = planes.find(p => p.id === suscripcion?.plan_id);
    const estadoBadge = data ? etiquetaEstado(data) : null;

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
                    ) : errores.usuario && !data ? (
                        <p className="text-center text-red-400 py-6 text-sm">⚠️ {errores.usuario}</p>
                    ) : data ? (
                        <>
                            {/* Nombre + estado */}
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xl font-bold text-zinc-100">{data.nombre || '—'}</p>
                                    <p className="text-sm text-zinc-400">{data.correo || '—'}</p>
                                </div>
                                <span className={`px-3 py-1 rounded-full text-xs font-bold ${estadoBadge?.clase}`}>
                                    {estadoBadge?.texto}
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
                                {errores.suscripcion ? (
                                    <p className="text-sm text-red-400">⚠️ {errores.suscripcion}</p>
                                ) : !suscripcion ? (
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

