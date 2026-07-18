import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const AdminDashboard = () => {
    const { tenant_id, usuario_id } = useAuth();
    const [solicitudes, setSolicitudes] = useState([]);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [processingId, setProcessingId] = useState(null);
    const [msg, setMsg] = useState('');
    const [voucherModal, setVoucherModal] = useState({ open: false, url: '', solicitud_id: null });
    const [rechazoModal, setRechazoModal] = useState({ open: false, solicitud_id: null, motivo: '' });
    // Fidelización state
    const [alumnosRiesgo, setAlumnosRiesgo] = useState([]);
    const [vencimientos, setVencimientos] = useState([]);
    const [fidelizacionLoading, setFidelizacionLoading] = useState(true);

    useEffect(() => {
        cargarSolicitudes();
        cargarFidelizacion();
    }, [tenant_id]);

    const cargarStats = async () => {
        try {
            const res = await api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`);
            setStats(res.data);
        } catch { setStats(null); }
    };

    const cargarSolicitudes = async () => {
        try {
            const [sols, statsRes] = await Promise.all([
                api.get(`/api/v1/solicitudes/pendientes?tenant_id=${tenant_id}`),
                api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`)
            ]);
            setSolicitudes(sols.data || []);
            setStats(statsRes.data);
        } catch {
            setSolicitudes([]);
            setStats(null);
        }
        setLoading(false);
    };

    const cargarFidelizacion = async () => {
        setFidelizacionLoading(true);
        try {
            const [riesgoRes, vencRes] = await Promise.all([
                api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/en-riesgo`),
                api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/vencimientos`)
            ]);
            setAlumnosRiesgo(riesgoRes.data?.alumnos_alerta || []);
            setVencimientos(vencRes.data?.alumnos || []);
        } catch {
            setAlumnosRiesgo([]);
            setVencimientos([]);
        }
        setFidelizacionLoading(false);
    };

    const handleAprobar = async (id) => {
        setProcessingId(id);
        setMsg('');
        try {
            await api.put(`/api/v1/solicitudes/${id}/aprobar?admin_id=${usuario_id || 1}`);
            setMsg(`✅ Solicitud #${id} aprobada. Tokens asignados.`);
            setTimeout(() => setMsg(''), 4000);
            cargarSolicitudes();
            cargarFidelizacion();
        } catch (err) {
            setMsg('❌ ' + (err.response?.data?.detail || err.message));
            setTimeout(() => setMsg(''), 4000);
        }
        setProcessingId(null);
    };

    const handleRechazar = async (id, motivo) => {
        setProcessingId(id);
        setMsg('');
        try {
            await api.put(`/api/v1/solicitudes/${id}/rechazar?admin_id=${usuario_id || 1}&motivo=${encodeURIComponent(motivo)}`);
            setMsg(`✅ Solicitud #${id} rechazada.`);
            setTimeout(() => setMsg(''), 4000);
            cargarSolicitudes();
        } catch (err) {
            setMsg('❌ ' + (err.response?.data?.detail || err.message));
            setTimeout(() => setMsg(''), 4000);
        }
        setProcessingId(null);
    };

    const handleDescargarVoucher = async (solicitud_id) => {
        try {
            window.location.href = `/api/v1/solicitudes/${solicitud_id}/voucher`;
        } catch (err) {
            setMsg('❌ Error al descargar voucher');
            setTimeout(() => setMsg(''), 4000);
        }
    };

    const handleAccionRapida = (alumno, tipo) => {
        // STUB: Envío de email pendiente — falta configurar Resend
        const actionName = tipo === 'riesgo' ? 'recuperación' : 'renovación';
        setMsg(`💡 [STUB Email] Alerta de ${actionName} para ${alumno.nombre} — Pendiente configuración de Resend`);
        setTimeout(() => setMsg(''), 5000);
    };

    // Combinar alertas para la tabla de acción (máximo 10)
    const alertsCombinadas = [
        ...alumnosRiesgo.map(a => ({
            ...a,
            tipo_alerta: 'riesgo',
            label: a.tiene_historial === false
                ? 'Sin actividad registrada'
                : `Inactivo hace ${a.dias_ausente} días`
        })),
        ...vencimientos.map(v => ({
            id: v.usuario_id,
            nombre: v.nombre,
            correo: v.correo,
            tipo_alerta: 'vencimiento',
            label: `Vence en ${v.dias_restantes} días`,
            plan_nombre: v.plan_nombre
        }))
    ].slice(0, 10);

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4" />
                    <p className="text-gray-600">Cargando...</p>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Dashboard Administrativo</h1>
                        <p className="text-gray-600">Panel de gestión de membresías y fidelización</p>
                    </div>
                    <button onClick={() => { cargarSolicitudes(); cargarFidelizacion(); }} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-bold">
                        🔄 Recargar
                    </button>
                </div>

                {msg && (
                    <div className={`p-4 rounded-lg font-bold shadow-lg transition-all ${msg.includes('✅') ? 'bg-green-100 text-green-800' : msg.includes('❌') ? 'bg-red-100 text-red-800' : 'bg-blue-100 text-blue-800'}`}>
                        {msg}
                    </div>
                )}

                {/* TARJETAS DE ESTADÍSTICAS */}
                {stats && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-blue-600">
                            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Alumnos Activos</p>
                            <p className="text-3xl font-bold text-blue-700 mt-1">{stats.alumnosActivos || 0}</p>
                            <p className="text-xs text-gray-400 mt-1">Total miembros con plan vigente</p>
                        </div>
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-green-600">
                            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Membresías Mensuales</p>
                            <p className="text-3xl font-bold text-green-700 mt-1">{stats.membresiasMensuales || 0}</p>
                            <div className="flex items-center gap-1 mt-1">
                                <span className={`text-xs font-bold ${(stats.crecimientoMensual || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                    {stats.crecimientoMensual > 0 ? '📈' : '📉'} {Math.abs(stats.crecimientoMensual || 0)}%
                                </span>
                                <span className="text-xs text-gray-400">vs mes anterior</span>
                            </div>
                        </div>
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-amber-600">
                            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Ingreso Mensual</p>
                            <p className="text-3xl font-bold text-amber-700 mt-1">
                                ${(stats.ingresoMensual || 0).toLocaleString('es-CL')}
                            </p>
                            <p className="text-xs text-gray-400 mt-1">Ingresos del mes actual</p>
                        </div>
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-purple-600">
                            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Asistencia Promedio</p>
                            <p className="text-3xl font-bold text-purple-700 mt-1">{stats.asistenciaPromedio || 0}%</p>
                            <p className="text-xs text-gray-400 mt-1">Ocupación en clases</p>
                        </div>
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-indigo-600">
                            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Clases Impartidas</p>
                            <p className="text-3xl font-bold text-indigo-700 mt-1">{stats.clasesImpartidas || 0}</p>
                            <p className="text-xs text-gray-400 mt-1">Clases realizadas este mes</p>
                        </div>
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-rose-600">
                            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Solicitudes Pendientes</p>
                            <p className="text-3xl font-bold text-rose-700 mt-1">{solicitudes.length}</p>
                            <p className="text-xs text-gray-400 mt-1">Esperando aprobación</p>
                        </div>
                    </div>
                )}

                {/* TARJETAS DE FIDELIZACIÓN */}
                {!fidelizacionLoading && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Tarjeta Alumnos en Riesgo */}
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-red-600">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Alumnos en Riesgo</p>
                                    <p className="text-3xl font-bold text-red-700 mt-1">{alumnosRiesgo.length}</p>
                                    <p className="text-xs text-gray-400 mt-1">Sin actividad {'>'} 7 días</p>
                                </div>
                                <span className="text-4xl">⚠️</span>
                            </div>
                        </div>
                        {/* Tarjeta Vencimientos Inminentes */}
                        <div className="bg-white rounded-lg shadow p-5 border-l-4 border-orange-600">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Vencimientos Inminentes</p>
                                    <p className="text-3xl font-bold text-orange-700 mt-1">{vencimientos.length}</p>
                                    <p className="text-xs text-gray-400 mt-1">Próximos 5 días</p>
                                </div>
                                <span className="text-4xl">⏰</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* PANEL DE ACCIÓN Y FIDELIZACIÓN */}
                {alertsCombinadas.length > 0 && (
                    <div className="bg-white rounded-lg shadow overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-200">
                            <h2 className="text-lg font-bold text-gray-900">
                                🎯 Panel de Acción y Fidelización ({alertsCombinadas.length} alertas)
                            </h2>
                        </div>
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-amber-800 text-white">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Nombre</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Correo</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Estado de Alerta</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Acción</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-200">
                                    {alertsCombinadas.map((a, idx) => (
                                        <tr key={`${a.tipo_alerta}-${a.id}`} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                            <td className="px-6 py-4">
                                                <p className="text-sm font-bold text-gray-900">{a.nombre}</p>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-500">{a.correo}</td>
                                            <td className="px-6 py-4">
                                                <span className={`inline-block px-2 py-1 text-xs font-bold rounded-full ${a.tipo_alerta === 'riesgo'
                                                    ? 'bg-red-100 text-red-800'
                                                    : 'bg-orange-100 text-orange-800'
                                                    }`}>
                                                    {a.label}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4">
                                                <button
                                                    onClick={() => handleAccionRapida(a, a.tipo_alerta)}
                                                    className="px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700"
                                                >
                                                    ⚡ Acción Rápida
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* SOLICITUDES PENDIENTES */}
                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-gray-200">
                        <h2 className="text-lg font-bold text-gray-900">
                            📋 Solicitudes Pendientes {solicitudes.length > 0 && `(${solicitudes.length})`}
                        </h2>
                    </div>
                    {solicitudes.length === 0 ? (
                        <div className="p-8 text-center text-gray-500">No hay solicitudes pendientes</div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-amber-800 text-white">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Alumno</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Plan</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Precio</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Voucher</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Certificado</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Fecha</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-200">
                                    {solicitudes.map((s, idx) => (
                                        <tr key={s.id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                            <td className="px-6 py-4">
                                                <p className="text-sm font-bold text-gray-900">{s.alumno_nombre}</p>
                                                <p className="text-xs text-gray-500">{s.alumno_email}</p>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-900">{s.plan_nombre}</td>
                                            <td className="px-6 py-4 text-sm font-bold text-green-700">
                                                ${(s.plan_precio || 0).toLocaleString('es-CL')}
                                            </td>
                                            <td className="px-6 py-4">
                                                {s.voucher_url ? (
                                                    <button onClick={() => setVoucherModal({ open: true, url: s.voucher_url, solicitud_id: s.id })}
                                                        className="text-blue-600 underline text-xs hover:text-blue-800">
                                                        📎 Ver Voucher
                                                    </button>
                                                ) : (
                                                    <span className="text-gray-400 text-xs">Sin voucher</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4">
                                                {s.certificado_estudiante_url ? (
                                                    <button onClick={() => setVoucherModal({ open: true, url: s.certificado_estudiante_url, solicitud_id: s.id })}
                                                        className="text-amber-600 underline text-xs hover:text-amber-800">
                                                        🎓 Ver Certificado
                                                    </button>
                                                ) : (
                                                    <span className="text-gray-400 text-xs">—</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-500">
                                                {s.created_at ? new Date(s.created_at).toLocaleDateString('es-CL') : '-'}
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex gap-2">
                                                    <button onClick={() => handleAprobar(s.id)}
                                                        disabled={processingId === s.id}
                                                        className="px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-bold hover:bg-green-700 disabled:opacity-50">
                                                        {processingId === s.id ? '...' : '✅ Aprobar'}
                                                    </button>
                                                    <button onClick={() => setRechazoModal({ open: true, solicitud_id: s.id, motivo: '' })}
                                                        disabled={processingId === s.id}
                                                        className="px-3 py-1.5 bg-red-600 text-white rounded-lg text-xs font-bold hover:bg-red-700 disabled:opacity-50">
                                                        {processingId === s.id ? '...' : '❌ Rechazar'}
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

            </div>

            {/* MODAL VOUCHER */}
            {voucherModal.open && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setVoucherModal({ open: false, url: '', solicitud_id: null })}>
                    <div className="bg-white rounded-xl max-w-2xl max-h-[90vh] overflow-auto shadow-2xl"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b flex justify-between items-center">
                            <h3 className="font-bold text-gray-900">📎 Voucher de Pago</h3>
                            <button onClick={() => setVoucherModal({ open: false, url: '', solicitud_id: null })}
                                className="text-gray-500 hover:text-gray-700 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4">
                            {voucherModal.url.match(/\.(pdf)$/i) ? (
                                <iframe src={voucherModal.url} className="w-full h-96" title="Voucher PDF" />
                            ) : (
                                <img src={voucherModal.url} alt="Voucher" className="w-full rounded-lg" />
                            )}
                        </div>
                        <div className="p-4 border-t flex justify-end gap-2">
                            <button onClick={() => handleDescargarVoucher(voucherModal.solicitud_id)}
                                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-bold">
                                📥 Descargar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* MODAL RECHAZO */}
            {rechazoModal.open && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}>
                    <div className="bg-white rounded-xl max-w-md w-full shadow-2xl"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b flex justify-between items-center">
                            <h3 className="font-bold text-gray-900">❌ Rechazar Solicitud</h3>
                            <button onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}
                                className="text-gray-500 hover:text-gray-700 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4 space-y-4">
                            <p className="text-sm text-gray-600">Indica el motivo del rechazo:</p>
                            <textarea
                                value={rechazoModal.motivo}
                                onChange={e => setRechazoModal(prev => ({ ...prev, motivo: e.target.value }))}
                                placeholder="Voucher inválido, datos incorrectos, etc."
                                className="w-full p-3 border rounded-lg text-sm"
                                rows={3}
                            />
                            <div className="flex gap-2 justify-end">
                                <button onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}
                                    className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 text-sm font-bold">
                                    Cancelar
                                </button>
                                <button onClick={() => {
                                    if (rechazoModal.motivo.trim()) {
                                        handleRechazar(rechazoModal.solicitud_id, rechazoModal.motivo.trim());
                                        setRechazoModal({ open: false, solicitud_id: null, motivo: '' });
                                    }
                                }}
                                    disabled={!rechazoModal.motivo.trim()}
                                    className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm font-bold disabled:opacity-50">
                                    Rechazar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </Layout>
    );
};

export default AdminDashboard;