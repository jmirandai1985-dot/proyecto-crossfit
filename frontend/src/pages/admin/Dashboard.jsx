import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const AdminDashboard = () => {
    const navigate = useNavigate();
    const { tenant_id, usuario_id } = useAuth();
    const [solicitudes, setSolicitudes] = useState([]);
    const [countPendientes, setCountPendientes] = useState(0);
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
    const [ocupacionHoy, setOcupacionHoy] = useState([]);
    const [ocupacionLoading, setOcupacionLoading] = useState(true);
    // Fidelización — modal membresías del mes
    const [fidelizacionModal, setFidelizacionModal] = useState(null); // 'membresias'

    useEffect(() => {
        cargarSolicitudes();
        cargarCountPendientes();
        cargarFidelizacion();
        cargarOcupacionHoy();
    }, [tenant_id]);

    const cargarOcupacionHoy = async () => {
        setOcupacionLoading(true);
        try {
            const res = await api.get(`/api/v1/dashboard/${tenant_id}/ocupacion-hoy`);
            setOcupacionHoy(res.data || []);
        } catch { setOcupacionHoy([]); }
        setOcupacionLoading(false);
    };

    const cargarStats = async () => {
        try {
            const res = await api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`);
            setStats(res.data);
        } catch { setStats(null); }
    };

    const cargarSolicitudes = async () => {
        try {
            const [sols, statsRes] = await Promise.all([
                api.get(`/api/v1/solicitudes/pendientes`),
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

    const cargarCountPendientes = async () => {
        try {
            const res = await api.get('/api/v1/alumnos/pendientes-activacion/count');
            setCountPendientes(res.data?.count || 0);
        } catch {
            setCountPendientes(0);
        }
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

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4" />
                    <p className="text-zinc-400">Cargando...</p>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-zinc-100">Dashboard Administrativo</h1>
                        <p className="text-zinc-400">Panel de gestión de membresías y fidelización</p>
                    </div>
                    <button onClick={() => { cargarSolicitudes(); cargarFidelizacion(); }} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-bold">
                        🔄 Recargar
                    </button>
                </div>

                {msg && (
                    <div className={`p-4 rounded-lg font-bold shadow-lg transition-all ${msg.includes('✅') ? 'bg-green-100 text-green-800' : msg.includes('❌') ? 'bg-red-100 text-red-800' : 'bg-blue-500/20 text-blue-300'}`}>
                        {msg}
                    </div>
                )}

                {/* TARJETAS DE ESTADÍSTICAS */}
                {stats && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
                        <button onClick={() => navigate('/admin/alumnos')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-blue-600 hover:shadow-md hover:border-blue-700 transition-all cursor-pointer text-left">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos Activos</p>
                            <p className="text-3xl font-bold text-blue-400 mt-1">{stats.alumnosActivos || 0}</p>
                            <p className="text-xs text-zinc-500 mt-1">Total miembros con plan vigente — Clic para ver</p>
                        </button>
                        <button onClick={() => setFidelizacionModal('membresias')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-green-600 hover:shadow-md hover:border-green-700 transition-all cursor-pointer text-left">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Membresías Mensuales</p>
                            <p className="text-3xl font-bold text-green-700 mt-1">{stats.membresiasMensuales || 0}</p>
                            <div className="flex items-center gap-1 mt-1">
                                <span className={`text-xs font-bold ${(stats.crecimientoMensual || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                    {stats.crecimientoMensual > 0 ? '📈' : '📉'} {Math.abs(stats.crecimientoMensual || 0)}%
                                </span>
                                <span className="text-xs text-zinc-500">vs mes anterior — Clic para ver detalle</span>
                            </div>
                        </button>
                        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-amber-600">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Ingreso Mensual</p>
                            <p className="text-3xl font-bold text-amber-700 mt-1">
                                ${(stats.ingresoMensual || 0).toLocaleString('es-CL')}
                            </p>
                            <p className="text-xs text-zinc-500 mt-1">Ingresos del mes actual</p>
                        </div>
                        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-purple-600">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Asistencia Promedio</p>
                            <p className="text-3xl font-bold text-purple-700 mt-1">{stats.asistenciaPromedio || 0}%</p>
                            <p className="text-xs text-zinc-500 mt-1">Ocupación en clases</p>
                        </div>
                        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-indigo-600">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Clases Impartidas</p>
                            <p className="text-3xl font-bold text-indigo-700 mt-1">{stats.clasesImpartidas || 0}</p>
                            <p className="text-xs text-zinc-500 mt-1">Clases realizadas este mes</p>
                        </div>
                        <button onClick={() => document.getElementById('solicitudes-pendientes')?.scrollIntoView({ behavior: 'smooth' })} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-rose-600 hover:shadow-md hover:border-rose-700 transition-all cursor-pointer text-left">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Solicitudes Pendientes</p>
                            <p className="text-3xl font-bold text-rose-700 mt-1">{countPendientes}</p>
                            <p className="text-xs text-zinc-500 mt-1">Esperando aprobación — Clic para ver</p>
                        </button>
                    </div>
                )}

                {/* WIDGET OCUPACION CLASES HOY */}
                <div className="bg-zinc-900 rounded-lg shadow p-5">
                    <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2">
                        📅 Clases de hoy — estado de ocupación
                    </h2>
                    <p className="text-xs text-zinc-400 mt-0.5">CrossFit y Levantamiento Olímpico, solo clases con coach asignado</p>
                    {ocupacionLoading ? (
                        <div className="flex justify-center py-6"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-900"></div></div>
                    ) : ocupacionHoy.length === 0 ? (
                        <div className="py-6 text-center text-zinc-500 text-sm">Sin clases de CrossFit/Levantamiento con coach asignado hoy</div>
                    ) : (
                        <div className="mt-4 space-y-3">
                            {ocupacionHoy.map(c => (
                                <div key={c.id} className="flex items-center gap-4">
                                    <div className="text-sm font-semibold text-zinc-300 w-16 shrink-0">{c.hora} hrs</div>
                                    <div className="flex-1 bg-zinc-800 rounded-full h-4 overflow-hidden">
                                        <div className={`h-full rounded-full transition-all ${c.color === 'red' ? 'bg-red-500' : c.color === 'amber' ? 'bg-amber-500' : 'bg-green-500'}`}
                                            style={{ width: `${Math.min(c.porcentaje, 100)}%` }} />
                                    </div>
                                    <div className="text-sm text-zinc-400 w-20 shrink-0">{c.ocupados}/{c.cupo}</div>
                                    <div className="text-sm font-semibold w-14 shrink-0">{c.porcentaje}%</div>
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium shrink-0
                                        ${c.color === 'red' ? 'bg-red-100 text-red-800' :
                                            c.color === 'amber' ? 'bg-amber-100 text-amber-800' :
                                                'bg-green-100 text-green-800'}`}>
                                        {c.estado}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* TARJETAS DE FIDELIZACIÓN */}
                {!fidelizacionLoading && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Tarjeta Alumnos en Riesgo */}
                        <button onClick={() => navigate('/admin/fidelizacion')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-red-600 hover:shadow-md hover:border-red-700 transition-all cursor-pointer text-left">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos en Riesgo</p>
                                    <p className="text-3xl font-bold text-red-700 mt-1">{alumnosRiesgo.length}</p>
                                    <p className="text-xs text-zinc-500 mt-1">Sin actividad {'>'} 7 días — Clic para ir a Fidelización</p>
                                </div>
                                <span className="text-4xl">⚠️</span>
                            </div>
                        </button>
                        {/* Tarjeta Vencimientos Inminentes */}
                        <button onClick={() => navigate('/admin/fidelizacion')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-orange-600 hover:shadow-md hover:border-orange-700 transition-all cursor-pointer text-left">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Vencimientos Inminentes</p>
                                    <p className="text-3xl font-bold text-orange-700 mt-1">{vencimientos.length}</p>
                                    <p className="text-xs text-zinc-500 mt-1">Próximos 5 días — Clic para ir a Fidelización</p>
                                </div>
                                <span className="text-4xl">⏰</span>
                            </div>
                        </button>
                    </div>
                )}

                {/* SOLICITUDES PENDIENTES */}
                <div id="solicitudes-pendientes" className="bg-zinc-900 rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-zinc-800">
                        <h2 className="text-lg font-bold text-zinc-100">
                            📋 Solicitudes Pendientes {solicitudes.length > 0 && `(${solicitudes.length})`}
                        </h2>
                    </div>
                    {solicitudes.length === 0 ? (
                        <div className="p-8 text-center text-zinc-400">No hay solicitudes pendientes</div>
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
                                <tbody className="divide-y divide-zinc-800">
                                    {solicitudes.map((s, idx) => (
                                        <tr key={s.id} className={idx % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                            <td className="px-6 py-4">
                                                <p className="text-sm font-bold text-zinc-100">{s.alumno_nombre}</p>
                                                <p className="text-xs text-zinc-400">{s.alumno_email}</p>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-100">{s.plan_nombre}</td>
                                            <td className="px-6 py-4 text-sm font-bold text-green-700">
                                                ${(s.plan_precio || 0).toLocaleString('es-CL')}
                                            </td>
                                            <td className="px-6 py-4">
                                                {s.voucher_url ? (
                                                    <button onClick={() => setVoucherModal({ open: true, url: s.voucher_url, solicitud_id: s.id })}
                                                        className="text-blue-400 underline text-xs hover:text-blue-300">
                                                        📎 Ver Voucher
                                                    </button>
                                                ) : (
                                                    <span className="text-zinc-500 text-xs">Sin voucher</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4">
                                                {s.certificado_estudiante_url ? (
                                                    <button onClick={() => setVoucherModal({ open: true, url: s.certificado_estudiante_url, solicitud_id: s.id })}
                                                        className="text-amber-600 underline text-xs hover:text-amber-800">
                                                        🎓 Ver Certificado
                                                    </button>
                                                ) : (
                                                    <span className="text-zinc-500 text-xs">—</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">
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
                    <div className="bg-zinc-900 rounded-xl max-w-2xl max-h-[90vh] overflow-auto shadow-2xl"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">📎 Voucher de Pago</h3>
                            <button onClick={() => setVoucherModal({ open: false, url: '', solicitud_id: null })}
                                className="text-zinc-400 hover:text-zinc-300 text-xl font-bold">✕</button>
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

            {/* MODAL MEMBRESÍAS DEL MES */}
            {fidelizacionModal === 'membresias' && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setFidelizacionModal(null)}>
                    <div className="bg-zinc-900 rounded-xl max-w-2xl max-h-[90vh] overflow-auto shadow-2xl border border-zinc-700"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b border-zinc-700 flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">📦 Membresías del Mes</h3>
                            <button onClick={() => setFidelizacionModal(null)}
                                className="text-zinc-400 hover:text-zinc-200 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4">
                            {!stats?.suscripcionesMes || stats.suscripcionesMes.length === 0 ? (
                                <p className="text-center text-zinc-500 py-6">No hay membresías vendidas este mes</p>
                            ) : (
                                    <table className="w-full">
                                        <thead className="bg-zinc-800">
                                            <tr>
                                                <th className="px-4 py-2 text-left text-xs font-bold text-zinc-300 uppercase">Alumno</th>
                                                <th className="px-4 py-2 text-left text-xs font-bold text-zinc-300 uppercase">Plan</th>
                                                <th className="px-4 py-2 text-left text-xs font-bold text-zinc-300 uppercase">Fecha</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-zinc-800">
                                            {(stats.suscripcionesMes || []).map((s, idx) => (
                                                <tr key={idx}>
                                                    <td className="px-4 py-2.5 text-sm font-medium text-zinc-100">{s.alumno_nombre}</td>
                                                    <td className="px-4 py-2.5 text-sm text-green-400">{s.plan_nombre}</td>
                                                    <td className="px-4 py-2.5 text-sm text-zinc-400">{s.fecha_inicio || '-'}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* MODAL RECHAZO */}
            {rechazoModal.open && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}>
                    <div className="bg-zinc-900 rounded-xl max-w-md w-full shadow-2xl"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">❌ Rechazar Solicitud</h3>
                            <button onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}
                                className="text-zinc-400 hover:text-zinc-300 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4 space-y-4">
                            <p className="text-sm text-zinc-400">Indica el motivo del rechazo:</p>
                            <textarea
                                value={rechazoModal.motivo}
                                onChange={e => setRechazoModal(prev => ({ ...prev, motivo: e.target.value }))}
                                placeholder="Voucher inválido, datos incorrectos, etc."
                                className="w-full p-3 border rounded-lg text-sm"
                                rows={3}
                            />
                            <div className="flex gap-2 justify-end">
                                <button onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}
                                    className="px-4 py-2 bg-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-600 text-sm font-bold">
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
