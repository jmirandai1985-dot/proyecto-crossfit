import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import AlumnoFichaModal from '../../components/AlumnoFichaModal';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const Fidelizacion = () => {
    const { tenant_id } = useAuth();
    const [alumnosRiesgo, setAlumnosRiesgo] = useState([]);
    const [vencimientos, setVencimientos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [menuAccion, setMenuAccion] = useState(null);
    const [enviandoCorreo, setEnviandoCorreo] = useState(null);
    const [fichaAlumnoId, setFichaAlumnoId] = useState(null);
    const [msg, setMsg] = useState('');

    const cargarFidelizacion = async () => {
        setLoading(true);
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
        setLoading(false);
    };

    useEffect(() => {
        cargarFidelizacion();
    }, [tenant_id]);

    const toggleMenuAccion = (id) => {
        setMenuAccion(menuAccion === id ? null : id);
    };

    const enviarCorreoManual = async (alumno, tipo) => {
        setMenuAccion(null);
        setEnviandoCorreo(alumno.id);
        setMsg('');
        try {
            // tipo_alerta: 'riesgo' → 'inactividad' | 'vencimiento' → 'vencimiento'
            const tipoEnvio = tipo === 'riesgo' ? 'inactividad' : 'vencimiento';
            const res = await api.post(`/api/v1/notificaciones-enviadas/enviar-manual`, null, {
                params: { alumno_id: alumno.id, tipo: tipoEnvio }
            });
            if (res.data?.exito) {
                setMsg(`✅ Correo de ${tipoEnvio === 'inactividad' ? 'recuperación' : 'renovación'} enviado a ${alumno.nombre}`);
            } else {
                const detalle = res.data?.detalle_error || 'No se pudo enviar el correo via Gmail SMTP (revisar credenciales o destinatario).';
                setMsg(`❌ Error al enviar correo a ${alumno.nombre}: ${detalle}`);
            }
        } catch (err) {
            setMsg('❌ ' + (err.response?.data?.detail || err.message));
        }
        setEnviandoCorreo(null);
        setTimeout(() => setMsg(''), 5000);
    };

    const verDetalleAlumno = (id) => {
        setMenuAccion(null);
        setFichaAlumnoId(id);
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

    const chartData = [
        { name: 'En riesgo', total: alumnosRiesgo.length },
        { name: 'Vencimiento próximo', total: vencimientos.length },
    ];

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-zinc-100">🎯 Fidelización</h1>
                        <p className="text-zinc-400">Alumnos en riesgo de abandono y vencimientos próximos</p>
                    </div>
                    <button onClick={cargarFidelizacion} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-bold">
                        🔄 Recargar
                    </button>
                </div>

                {msg && (
                    <div className={`p-4 rounded-lg font-bold shadow-lg transition-all ${msg.includes('✅') ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                        {msg}
                    </div>
                )}

                {loading ? (
                    <div className="flex justify-center py-12">
                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
                    </div>
                ) : (
                    <>
                        {/* Tarjetas resumen */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-red-600">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos en Riesgo</p>
                                <p className="text-3xl font-bold text-red-700 mt-1">{alumnosRiesgo.length}</p>
                                <p className="text-xs text-zinc-500 mt-1">Sin actividad {'>'} 7 días</p>
                            </div>
                            <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-orange-600">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Vencimientos Inminentes</p>
                                <p className="text-3xl font-bold text-orange-700 mt-1">{vencimientos.length}</p>
                                <p className="text-xs text-zinc-500 mt-1">Próximos 5 días</p>
                            </div>
                        </div>

                        {/* Gráfico de barras: desglose alertas */}
                        <div className="bg-zinc-900 rounded-lg shadow p-5">
                            <h2 className="text-lg font-bold text-zinc-100 mb-2">📊 Desglose de alertas</h2>
                            <p className="text-xs text-zinc-400 mb-4">Alumnos "en riesgo" vs "vencimiento próximo"</p>
                            {alertsCombinadas.length === 0 ? (
                                <div className="py-8 text-center text-zinc-500 text-sm">Sin alertas activas 🎉</div>
                            ) : (
                                <ResponsiveContainer width="100%" height={220}>
                                    <BarChart data={chartData} barSize={70}>
                                        <CartesianGrid strokeDasharray="3 3" />
                                        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                                        <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                                        <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} />
                                        <Bar dataKey="total" name="Alumnos" radius={[6, 6, 0, 0]}>
                                            {chartData.map((d, idx) => (
                                                <Cell key={idx} fill={d.name === 'En riesgo' ? '#dc2626' : '#f97316'} />
                                            ))}
                                        </Bar>
                                    </BarChart>
                                </ResponsiveContainer>
                            )}
                        </div>


                        {/* Tabla de acción y fidelización */}
                        <div className="bg-zinc-900 rounded-lg shadow overflow-hidden">
                            <div className="px-6 py-4 border-b border-zinc-800">
                                <h2 className="text-lg font-bold text-zinc-100">
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
                                    <tbody className="divide-y divide-zinc-800">
                                        {alertsCombinadas.map((a, idx) => (
                                            <tr key={`${a.tipo_alerta}-${a.id}`} className={idx % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                                <td className="px-6 py-4">
                                                    <p className="text-sm font-bold text-zinc-100">{a.nombre}</p>
                                                </td>
                                                <td className="px-6 py-4 text-sm text-zinc-400">{a.correo}</td>
                                                <td className="px-6 py-4">
                                                    <span className={`inline-block px-2 py-1 text-xs font-bold rounded-full ${a.tipo_alerta === 'riesgo'
                                                        ? 'bg-red-100 text-red-800'
                                                        : 'bg-orange-100 text-orange-800'
                                                        }`}>
                                                        {a.label}
                                                    </span>
                                                </td>
                                                <td className="px-6 py-4">
                                                    <div className="relative inline-block">
                                                        <button
                                                            onClick={() => toggleMenuAccion(a.id)}
                                                            disabled={enviandoCorreo === a.id}
                                                            className="px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700 disabled:opacity-50"
                                                        >
                                                            {enviandoCorreo === a.id ? '⏳ Enviando...' : '⚡ Acción Rápida'}
                                                        </button>
                                                        {menuAccion === a.id && (
                                                            <div className="absolute right-0 mt-1 w-44 bg-zinc-900 rounded-lg shadow-xl border border-zinc-700 z-20 overflow-hidden">
                                                                <button
                                                                    onClick={() => enviarCorreoManual(a, a.tipo_alerta)}
                                                                    disabled={enviandoCorreo === a.id}
                                                                    className="w-full px-4 py-2.5 text-left text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
                                                                >
                                                                    ✉️ Enviar correo
                                                                </button>
                                                                <button
                                                                    onClick={() => verDetalleAlumno(a.id)}
                                                                    className="w-full px-4 py-2.5 text-left text-sm text-zinc-200 hover:bg-zinc-800 border-t border-zinc-700"
                                                                >
                                                                    👤 Ver detalle
                                                                </button>
                                                            </div>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </>
                )}
            </div>

            {/* MODAL FICHA ALUMNO */}
            {fichaAlumnoId && (
                <AlumnoFichaModal
                    alumnoId={fichaAlumnoId}
                    tenantId={tenant_id}
                    onClose={() => setFichaAlumnoId(null)}
                />
            )}
        </Layout>
    );
};

export default Fidelizacion;
