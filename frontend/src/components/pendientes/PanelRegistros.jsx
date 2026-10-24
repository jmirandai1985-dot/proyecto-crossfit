import React, { useState } from 'react';
import { useAccionAlumnoPendiente, usePendientesActivacion } from '../../hooks/queries';

/**
 * Pestaña "Registros" de `/admin/pendientes`.
 *
 * Es la COLA 1 que antes vivía apilada en `/admin/alumnos-pendientes`: alumnos que
 * se dieron de alta solos desde el login y quedaron en `pendiente_activacion`.
 *
 * Se movió a su propio componente (y no a una función del archivo de la pantalla)
 * por dos motivos:
 *   1. cada pestaña pide SÓLO su endpoint: entrar a "Pedidos" no descarga los
 *      registros, y así el panel no hace tres consultas para pintar una;
 *   2. el formulario de credenciales provisionales (abajo) es estado propio de esta
 *      cola: si viviera en la pantalla padre, cambiar de pestaña lo borraría.
 *
 * La lista y el auto-refresh los maneja React Query (`usePendientesActivacion`);
 * la mutación invalida `['alumnos','pendientes-activacion']` y el resumen de
 * badges, así que los números del encabezado se actualizan solos.
 */
const PanelRegistros = () => {
    const registrosQ = usePendientesActivacion({ staleTime: 15_000 });
    const accionAlumno = useAccionAlumnoPendiente();

    const pendientes = registrosQ.data || [];
    const loading = registrosQ.isLoading;
    const errorRegistros = registrosQ.error
        ? (registrosQ.error.response?.data?.detail || 'No se pudieron cargar los registros')
        : '';

    const [actionId, setActionId] = useState(null);
    const [confirmarRechazo, setConfirmarRechazo] = useState(null); // alumno
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    // El correo de credenciales puede fallar DESPUÉS de activar al alumno: en ese
    // caso se le muestra al admin la contraseña provisional para que se la pase.
    const [credenciales, setCredenciales] = useState(null);

    // ── Acciones sobre un registro (activar / rechazar) ──────────────────────
    const handleAccion = async (alumnoId, accion) => {
        setActionId(alumnoId);
        setMessage('');
        setError('');
        try {
            const data = await accionAlumno.mutateAsync({ alumnoId, accion });
            if (accion === 'activar') {
                if (data?.email_enviado) {
                    setMessage('Alumno activado y credenciales enviadas por correo');
                    setCredenciales(null);
                } else {
                    // El correo NO salió: el backend generó la contraseña igual, así
                    // que hay que mostrarla para que el admin se la entregue.
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
            // Sin recarga manual: la mutación ya invalidó la cola y el resumen.
        } catch (err) {
            setError(err.response?.data?.detail || 'Ocurrió un error al procesar la solicitud');
        } finally {
            setActionId(null);
        }
    };

    return (
        <div>
            {message && (
                <div className="mb-4 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm">
                    ✅ {message}
                </div>
            )}
            {(error || errorRegistros) && (
                <div className="mb-4 bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                    {error || errorRegistros}
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
                                    <p className="text-white text-sm font-medium">
                                        {p.genero === 'F' ? 'Femenino' : p.genero === 'M' ? 'Masculino' : '—'}
                                    </p>
                                </div>
                                <div className="bg-zinc-800 rounded-lg py-2">
                                    <p className="text-[10px] text-zinc-500 uppercase">Peso</p>
                                    <p className="text-white text-sm font-medium">
                                        {p.peso_kg ? `${p.peso_kg} kg` : '—'}
                                    </p>
                                </div>
                            </div>

                            <p className="text-zinc-500 text-xs">
                                Estatura: {p.estatura_cm ? `${p.estatura_cm} cm` : '—'}
                                {p.fecha_registro
                                    ? ` · Solicitó el ${new Date(p.fecha_registro).toLocaleDateString('es-CL')}`
                                    : ''}
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

            {/* Confirmación del rechazo: el alumno NO se borra, queda 'rechazado'. */}
            {confirmarRechazo && (
                <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4">
                    <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6">
                        <h2 className="text-xl font-bold text-zinc-100 mb-3">Rechazar solicitud</h2>
                        <p className="text-sm text-zinc-300 mb-5">
                            Confirma rechazar la solicitud de {confirmarRechazo.nombre} ({confirmarRechazo.correo}).
                            El alumno quedará con estado &quot;rechazado&quot; y sin acceso (no se borra su registro).
                        </p>
                        <div className="flex gap-3">
                            <button
                                onClick={() => setConfirmarRechazo(null)}
                                className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium"
                            >
                                Cancelar
                            </button>
                            <button
                                onClick={() => {
                                    const pend = confirmarRechazo;
                                    setConfirmarRechazo(null);
                                    handleAccion(pend.id, 'rechazar');
                                }}
                                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium"
                            >
                                Rechazar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default PanelRegistros;

