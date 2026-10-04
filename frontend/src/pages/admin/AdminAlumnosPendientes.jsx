import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import api from '../../services/api';
// Vista previa del comprobante (blob autenticado): hook compartido con el Dashboard.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';

const AdminAlumnosPendientes = () => {
    const [pendientes, setPendientes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [actionId, setActionId] = useState(null);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    // Contraseña provisional para mostrar al admin cuando el correo NO se pudo
    // enviar (antes se decía "credenciales enviadas" aunque el envío fallara).
    const [credenciales, setCredenciales] = useState(null);
    const [confirmarRechazo, setConfirmarRechazo] = useState(null);

    // ── Cola 2: SOLICITUDES DE PLAN con comprobante (voucher) ─────────────────
    // Esta pantalla se llamaba solo a los REGISTROS pendientes de activación, así
    // que una solicitud de plan esperando aprobación del comprobante NO aparecía
    // en ninguna parte (el admin leía "No hay solicitudes pendientes" y creía que
    // no había nada que revisar). Ahora se listan las dos colas.
    const [solicitudes, setSolicitudes] = useState([]);
    const [solicitudesError, setSolicitudesError] = useState('');
    const [solicitudActionId, setSolicitudActionId] = useState(null);
    const [rechazoPlanModal, setRechazoPlanModal] = useState(null); // solicitud
    const [motivoRechazo, setMotivoRechazo] = useState('');
    // Vista previa del voucher por el endpoint AUTENTICADO (blob): la URL pública
    // /static/uploads/... no lleva token. La lógica vive en el hook compartido.
    const [voucherSolicitud, setVoucherSolicitud] = useState(null); // solicitud

    const cargarPendientes = async ({ silencioso = false } = {}) => {
        // Las DOS colas se piden en paralelo con allSettled: si una falla, la otra
        // se sigue mostrando y la sección afectada avisa con su propio error.
        if (!silencioso) setLoading(true);
        const [regs, sols] = await Promise.allSettled([
            api.get('/api/v1/alumnos/pendientes-activacion'),
            api.get('/api/v1/solicitudes/pendientes'),
        ]);
        if (regs.status === 'fulfilled') {
            setPendientes(regs.value.data || []);
            setError('');
        } else {
            console.error('Error cargando registros pendientes', regs.reason);
            setError(regs.reason?.response?.data?.detail || 'No se pudieron cargar las solicitudes');
        }
        if (sols.status === 'fulfilled') {
            setSolicitudes(sols.value.data || []);
            setSolicitudesError('');
        } else {
            console.error('Error cargando solicitudes de plan', sols.reason);
            setSolicitudes([]);
            setSolicitudesError(sols.reason?.response?.data?.detail
                || 'No se pudieron cargar las solicitudes de plan');
        }
        if (!silencioso) setLoading(false);
    };

    useEffect(() => {
        cargarPendientes();
    }, []);

    // AUTO-REFRESH (30s): pueden entrar solicitudes mientras el admin tiene la
    // pantalla abierta. Silencioso para no parpadear el spinner ni perder el foco.
    useEffect(() => {
        const id = setInterval(() => cargarPendientes({ silencioso: true }), 30000);
        return () => clearInterval(id);
    }, []);

    const handleAccion = async (alumnoId, accion) => {
        setActionId(alumnoId);
        setMessage('');
        setError('');
        try {
            const { data } = await api.put(`/api/v1/alumnos/${alumnoId}/${accion}`);
            if (accion === 'activar') {
                if (data?.email_enviado) {
                    setMessage('Alumno activado y credenciales enviadas por correo');
                    setCredenciales(null);
                } else {
                    // El correo NO salió: hay que mostrarle la contraseña provisional
                    // al admin para que se la pase al alumno (el backend la genera igual).
                    setMessage('');
                    setCredenciales({
                        password: data?.password_provisional || '',
                        error: data?.email_error || 'no se pudo enviar el correo',
                    });
                }
            } else {
                setMessage('Solicitud rechazada');
                setCredenciales(null);
            }
            cargarPendientes({ silencioso: true });
        } catch (err) {
            setError(err.response?.data?.detail || 'Ocurrió un error al procesar la solicitud');
        } finally {
            setActionId(null);
        }
    };

    // ── Acciones sobre solicitudes de PLAN (aprobar / rechazar) ───────────────
    const handleSolicitudAccion = async (id, accion, motivo = '') => {
        setSolicitudActionId(id);
        setMessage('');
        setError('');
        try {
            if (accion === 'aprobar') {
                await api.put(`/api/v1/solicitudes/${id}/aprobar`);
                setMessage(`Solicitud #${id} aprobada. Plan activado y alumno notificado.`);
            } else {
                await api.put(`/api/v1/solicitudes/${id}/rechazar?motivo=${encodeURIComponent(motivo || 'Rechazado')}`);
                setMessage(`Solicitud #${id} rechazada.`);
            }
            cargarPendientes({ silencioso: true });
        } catch (err) {
            setError(err.response?.data?.detail || 'Ocurrió un error al procesar la solicitud de plan');
        } finally {
            setSolicitudActionId(null);
        }
    };

    // Vista previa del comprobante: el hook pide el archivo CON el token (endpoint
    // protegido) y revoca el object URL al cerrar el modal / desmontar.
    const { preview: voucherPreview } = useDocumentoAutenticado({
        previewUrl: voucherSolicitud?.id
            ? `/api/v1/solicitudes/${voucherSolicitud.id}/voucher?inline=1`
            : '',
        nombreFallback: `comprobante_${voucherSolicitud?.id || ''}`,
    });

    return (
        <Layout>
            <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-2xl font-bold text-white">Pendientes de revisión</h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            Registros de alumnos nuevos y solicitudes de plan con comprobante esperando tu revisión
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
                {credenciales && (
                    <div className="mb-4 bg-amber-500/15 border border-amber-500/40 text-amber-200 px-4 py-3 rounded-lg text-sm space-y-2">
                        <p className="font-semibold">
                            ⚠️ El alumno quedó activo, pero el correo de credenciales NO se pudo enviar
                            ({credenciales.error}).
                        </p>
                        <p>Pásale esta contraseña provisional y pídele que la cambie al entrar:</p>
                        <div className="flex items-center gap-2">
                            <code className="bg-zinc-900/70 border border-amber-500/30 rounded px-3 py-1 font-mono text-base text-amber-100">
                                {credenciales.password}
                            </code>
                            <button
                                onClick={() => navigator.clipboard?.writeText(credenciales.password)
                                    .then(() => setMessage('Contraseña copiada al portapapeles'))
                                    .catch(() => {})}
                                className="px-3 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-xs font-semibold"
                            >Copiar</button>
                        </div>
                    </div>
                )}

                {/* ── COLA 1: registros de alumnos nuevos (pendiente_activacion) ──── */}
                <h2 className="text-lg font-bold text-zinc-100 mb-3">
                    📝 Registros de alumnos nuevos
                    {pendientes.length > 0 && <span className="text-zinc-500 font-normal"> ({pendientes.length})</span>}
                </h2>
                {loading ? (
                    <div className="flex items-center justify-center py-20">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500" />
                    </div>
                ) : pendientes.length === 0 ? (
                    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-10 text-center">
                        <p className="text-3xl mb-3">🎉</p>
                        <p className="text-zinc-300 font-medium">No hay registros de alumnos nuevos pendientes</p>
                        <p className="text-zinc-500 text-sm mt-1">
                            Cuando un alumno nuevo se registre desde el login, su solicitud aparecerá aquí.
                            Las solicitudes de PLAN se listan más abajo.
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
                                        onClick={() => setConfirmarRechazo(p)}
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

                {/* ── COLA 2: SOLICITUDES DE PLAN con comprobante (voucher) ─────────
                    Cuota independiente de la anterior: /solicitudes/pendientes devuelve
                    alumno, plan, precio final (con el beneficio aplicado) y el voucher.
                    Sin esta sección la solicitud quedaba invisible para el admin. */}
                <div className="mt-10">
                    <h2 className="text-lg font-bold text-zinc-100 mb-3">
                        🧾 Solicitudes de plan (comprobante)
                        {solicitudes.length > 0 && <span className="text-zinc-500 font-normal"> ({solicitudes.length})</span>}
                    </h2>
                    <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
                        {solicitudesError ? (
                            <div className="p-8 text-center">
                                <p className="text-red-300 text-sm">⚠️ {solicitudesError}</p>
                                <button
                                    onClick={() => cargarPendientes({ silencioso: true })}
                                    className="mt-3 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm transition-colors"
                                >
                                    Reintentar
                                </button>
                            </div>
                        ) : solicitudes.length === 0 ? (
                            <div className="p-8 text-center">
                                <p className="text-zinc-300 text-sm">
                                    {loading ? 'Cargando…' : 'No hay solicitudes de plan esperando revisión'}
                                </p>
                                {!loading && (
                                    <p className="text-zinc-500 text-xs mt-1">
                                        Aparecen acá cuando un alumno sube el comprobante de un plan desde su panel.
                                    </p>
                                )}
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead className="bg-zinc-800">
                                        <tr>
                                            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Alumno</th>
                                            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Plan</th>
                                            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Precio</th>
                                            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Comprobante</th>
                                            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Fecha</th>
                                            <th className="px-4 py-3 text-right text-xs font-medium text-zinc-400 uppercase">Acciones</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800">
                                        {solicitudes.map((s) => (
                                            <tr key={s.id}>
                                                <td className="px-4 py-3">
                                                    <p className="text-sm font-semibold text-white">{s.alumno_nombre}</p>
                                                    <p className="text-xs text-zinc-400">{s.alumno_email}</p>
                                                </td>
                                                <td className="px-4 py-3 text-sm text-zinc-200">{s.plan_nombre}</td>
                                                <td className="px-4 py-3 text-sm font-bold text-emerald-400">
                                                    ${(s.precio_final ?? s.plan_precio ?? 0).toLocaleString('es-CL')}
                                                    {s.descuento_pct != null && (
                                                        <span className="block text-[11px] font-medium text-amber-400">
                                                            Beneficio: −{s.descuento_pct} %
                                                            <span className="ml-1 text-zinc-500 line-through">
                                                                ${(s.plan_precio || 0).toLocaleString('es-CL')}
                                                            </span>
                                                        </span>
                                                    )}
                                                </td>
                                                <td className="px-4 py-3">
                                                    {s.voucher_url ? (
                                                        <button
                                                            onClick={() => setVoucherSolicitud(s)}
                                                            className="text-blue-400 underline text-xs hover:text-blue-300"
                                                        >
                                                            📎 Ver comprobante
                                                        </button>
                                                    ) : (
                                                        <span className="text-zinc-500 text-xs">Sin comprobante</span>
                                                    )}
                                                </td>
                                                <td className="px-4 py-3 text-xs text-zinc-400">
                                                    {s.created_at ? new Date(s.created_at).toLocaleDateString('es-CL') : '—'}
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center justify-end gap-2">
                                                        <button
                                                            onClick={() => handleSolicitudAccion(s.id, 'aprobar')}
                                                            disabled={solicitudActionId === s.id}
                                                            className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white text-xs font-semibold transition-colors"
                                                        >
                                                            {solicitudActionId === s.id ? '…' : '✓ Aprobar'}
                                                        </button>
                                                        <button
                                                            onClick={() => { setRechazoPlanModal(s); setMotivoRechazo(''); }}
                                                            disabled={solicitudActionId === s.id}
                                                            className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-red-500/20 border border-zinc-700 hover:border-red-500/40 text-zinc-300 hover:text-red-300 text-xs font-semibold transition-colors"
                                                        >
                                                            ✕ Rechazar
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
                    <p className="text-zinc-500 text-xs mt-2">
                        Al aprobar, el plan se activa y el alumno recibe la notificación. Al rechazar se le
                        pide el motivo y el alumno lo ve en su panel.
                    </p>
                </div>
            </div>
                {confirmarRechazo && (
                    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6">
                            <h2 className="text-xl font-bold text-zinc-100 mb-3">Rechazar solicitud</h2>
                            <p className="text-sm text-zinc-300 mb-5">
                                Confirma rechazar la solicitud de {confirmarRechazo.nombre} ({confirmarRechazo.correo})?
                                El alumno quedará con estado "rechazado" y sin acceso (no se borra su registro).
                            </p>
                            <div className="flex gap-3">
                                <button onClick={() => setConfirmarRechazo(null)} className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium">
                                    Cancelar
                                </button>
                                <button
                                    onClick={() => { const pend = confirmarRechazo; setConfirmarRechazo(null); handleAccion(pend.id, 'rechazar'); }}
                                    className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium"
                                >
                                    Rechazar
                                </button>
                            </div>
                        </div>
                    </div>
                )}
                {/* MODAL RECHAZO DE SOLICITUD DE PLAN (con motivo para el alumno) */}
                {rechazoPlanModal && (
                    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6">
                            <h2 className="text-xl font-bold text-zinc-100 mb-3">Rechazar solicitud de plan</h2>
                            <p className="text-sm text-zinc-300 mb-4">
                                ¿Rechazar la solicitud #{rechazoPlanModal.id} de {rechazoPlanModal.alumno_nombre}
                                {' '}para el plan {rechazoPlanModal.plan_nombre}? El alumno verá el motivo en su
                                panel y podrá enviar otra solicitud.
                            </p>
                            <label className="block text-xs font-semibold text-zinc-400 uppercase mb-2">
                                Motivo (se envía al alumno)
                            </label>
                            <textarea
                                value={motivoRechazo}
                                onChange={(e) => setMotivoRechazo(e.target.value)}
                                rows={3}
                                placeholder="Ej: el comprobante no es legible, el monto no coincide…"
                                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-red-500"
                            />
                            <div className="flex gap-3 mt-5">
                                <button
                                    onClick={() => { setRechazoPlanModal(null); setMotivoRechazo(''); }}
                                    className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium"
                                >
                                    Cancelar
                                </button>
                                <button
                                    onClick={() => { const s = rechazoPlanModal; setRechazoPlanModal(null); handleSolicitudAccion(s.id, 'rechazar', motivoRechazo); }}
                                    disabled={!motivoRechazo.trim() || solicitudActionId === rechazoPlanModal.id}
                                    className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
                                >
                                    Rechazar
                                </button>
                            </div>
                        </div>
                    </div>
                )}
                {/* MODAL VISTA PREVIA DEL COMPROBANTE: se pide el archivo al endpoint
                    autenticado (blob) porque /static/uploads/... se sirve sin token. */}
                {voucherSolicitud && (
                    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4"
                        onClick={() => setVoucherSolicitud(null)}>
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
                            onClick={(e) => e.stopPropagation()}>
                            <div className="p-4 border-b border-zinc-800 flex justify-between items-center">
                                <h3 className="font-bold text-zinc-100">
                                    📎 Comprobante de {voucherSolicitud.alumno_nombre} · {voucherSolicitud.plan_nombre}
                                </h3>
                                <button onClick={() => setVoucherSolicitud(null)}
                                    className="text-zinc-400 hover:text-zinc-300 text-xl font-bold">✕</button>
                            </div>
                            <div className="p-4 min-h-[12rem] flex items-center justify-center">
                                {voucherPreview.loading ? (
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                                ) : voucherPreview.error ? (
                                    <p className="text-center text-red-400 text-sm py-6">{voucherPreview.error}</p>
                                ) : voucherPreview.blobUrl ? (
                                    voucherPreview.mime.includes('pdf') ? (
                                        <iframe src={voucherPreview.blobUrl} className="w-full h-96" title="Comprobante PDF" />
                                    ) : (
                                        <img src={voucherPreview.blobUrl} alt="Comprobante" className="w-full rounded-lg" />
                                    )
                                ) : (
                                    <p className="text-zinc-400 text-sm">Sin vista previa</p>
                                )}
                            </div>
                            <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                                <button
                                    onClick={() => { const s = voucherSolicitud; setVoucherSolicitud(null); handleSolicitudAccion(s.id, 'aprobar'); }}
                                    className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold"
                                >
                                    ✓ Aprobar
                                </button>
                                <button
                                    onClick={() => setVoucherSolicitud(null)}
                                    className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm"
                                >
                                    Cerrar
                                </button>
                            </div>
                        </div>
                    </div>
                )}
        </Layout>
    );
};

export default AdminAlumnosPendientes;
