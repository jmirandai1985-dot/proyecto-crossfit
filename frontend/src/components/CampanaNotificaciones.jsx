import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Bell, CheckCheck, Inbox, RefreshCw, X } from 'lucide-react';
import api from '../services/api';

// ══════════════════════════════════════════════════════════════════════════
//  N-2 — Campana de notificaciones del ALUMNO (Layout del panel alumno)
//
//  Contrato de la UI:
//    * contador de NO leídas: UNA consulta al montar (sin polling);
//    * el panel se REFRESCA AL ABRIRLO (no hay timer de fondo);
//    * marcar una leída (PUT /{id}/leer) y marcar todas (PUT /leer-todas);
//    * estados de CARGA y de ERROR visibles, con Reintentar (sin catch mudo).
//
//  Endpoints: todos derivan el `alumno_id` del token JWT (notificaciones.py),
//  así que la campana nunca manda el id de otro alumno.
// ══════════════════════════════════════════════════════════════════════════

const formatearFecha = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('es-CL', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
};

const ETIQUETAS_TIPO = {
    aprobado: 'Plan aprobado',
    rechazado: 'Plan rechazado',
    plan_activo: 'Plan activo',
};

const CampanaNotificaciones = () => {
    const [abierto, setAbierto] = useState(false);
    const [noLeidas, setNoLeidas] = useState(0);
    const [contadorError, setContadorError] = useState('');
    const [notificaciones, setNotificaciones] = useState([]);
    const [cargando, setCargando] = useState(false);
    const [error, setError] = useState('');
    const [accionando, setAccionando] = useState(false);

    // ── Contador inicial: una sola consulta, sin polling ──
    const cargarContador = useCallback(async () => {
        try {
            const { data } = await api.get('/api/v1/notificaciones',
                { params: { solo_no_leidas: true } });
            setNoLeidas(Array.isArray(data) ? data.length : 0);
            setContadorError('');
        } catch (e) {
            console.error('No se pudo consultar las notificaciones no leídas:', e);
            setContadorError('No se pudo consultar el contador de notificaciones.');
        }
    }, []);

    useEffect(() => { cargarContador(); }, [cargarContador]);

    // ── Lista: se pide cada vez que se ABRE el panel ──
    const cargarLista = useCallback(async () => {
        setCargando(true);
        setError('');
        try {
            const { data } = await api.get('/api/v1/notificaciones');
            const lista = Array.isArray(data) ? data : [];
            setNotificaciones(lista);
            setNoLeidas(lista.filter((n) => !n.leida).length);
            setContadorError('');
        } catch (e) {
            console.error('No se pudieron cargar las notificaciones:', e);
            setError('No se pudieron cargar tus notificaciones. Verifica la conexión '
                + 'con el servidor e intenta de nuevo.');
        } finally {
            setCargando(false);
        }
    }, []);

    const togglePanel = () => {
        if (abierto) {
            setAbierto(false);
            return;
        }
        setAbierto(true);
        cargarLista();
    };

    // ── Marcar una como leída ──
    const marcarLeida = async (id) => {
        setAccionando(true);
        setError('');
        try {
            await api.put(`/api/v1/notificaciones/${id}/leer`);
            // Actualización local: no hace falta repedir la lista.
            setNotificaciones((prev) => prev.map(
                (n) => (n.id === id ? { ...n, leida: true } : n)));
            setNoLeidas((n) => Math.max(0, n - 1));
        } catch (e) {
            console.error('No se pudo marcar la notificación como leída:', e);
            setError('No se pudo marcar la notificación como leída. Intenta de nuevo.');
        } finally {
            setAccionando(false);
        }
    };

    // ── Marcar todas como leídas ──
    const marcarTodas = async () => {
        setAccionando(true);
        setError('');
        try {
            await api.put('/api/v1/notificaciones/leer-todas');
            setNotificaciones((prev) => prev.map((n) => ({ ...n, leida: true })));
            setNoLeidas(0);
        } catch (e) {
            console.error('No se pudieron marcar todas las notificaciones:', e);
            setError('No se pudieron marcar todas como leídas. Intenta de nuevo.');
        } finally {
            setAccionando(false);
        }
    };

    return (
        <div className="relative">
            <button
                type="button"
                onClick={togglePanel}
                aria-label="Notificaciones"
                aria-expanded={abierto}
                title="Notificaciones"
                className="relative p-2 rounded-lg text-zinc-300 hover:text-white hover:bg-zinc-800 transition-colors"
            >
                <Bell className="w-5 h-5" />
                {noLeidas > 0 && (
                    <span
                        aria-label={`${noLeidas} notificaciones sin leer`}
                        className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-orange-500 text-white text-[10px] font-bold flex items-center justify-center"
                    >
                        {noLeidas > 99 ? '99+' : noLeidas}
                    </span>
                )}
            </button>


            {abierto && (
                <>
                    {/* Cierra al hacer click fuera del panel */}
                    <button
                        type="button"
                        aria-label="Cerrar notificaciones"
                        onClick={() => setAbierto(false)}
                        className="fixed inset-0 z-40 cursor-default"
                    />
                    <div
                        role="dialog"
                        aria-label="Notificaciones"
                        className="absolute right-0 mt-2 w-80 sm:w-96 max-h-[70vh] overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl z-50"
                    >
                        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
                            <p className="text-sm font-semibold text-zinc-100">
                                Notificaciones
                                {noLeidas > 0 && (
                                    <span className="ml-2 text-xs font-normal text-orange-400">
                                        {noLeidas} sin leer
                                    </span>
                                )}
                            </p>
                            <div className="flex items-center gap-1">
                                <button
                                    type="button"
                                    onClick={marcarTodas}
                                    disabled={accionando || noLeidas === 0}
                                    title="Marcar todas como leídas"
                                    aria-label="Marcar todas como leídas"
                                    className="p-1.5 rounded-lg text-zinc-400 hover:text-emerald-400 hover:bg-zinc-800 disabled:opacity-40 disabled:hover:text-zinc-400 transition-colors"
                                >
                                    <CheckCheck className="w-4 h-4" />
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setAbierto(false)}
                                    aria-label="Cerrar panel de notificaciones"
                                    className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            </div>
                        </div>

                        {contadorError && (
                            <div className="px-4 py-2 text-[11px] text-amber-300 bg-amber-500/10 border-b border-amber-500/20">
                                ⚠️ {contadorError}
                            </div>
                        )}

                        {error && (
                            <div className="px-4 py-3 border-b border-zinc-800 bg-red-500/10">
                                <p className="text-xs text-red-300 flex items-start gap-2">
                                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                                    <span>{error}</span>
                                </p>
                                <button
                                    type="button"
                                    onClick={cargarLista}
                                    className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-red-200 hover:text-white"
                                >
                                    <RefreshCw className="w-3.5 h-3.5" /> Reintentar
                                </button>
                            </div>
                        )}

                        {cargando ? (
                            <p className="px-4 py-8 text-center text-sm text-zinc-400">
                                Cargando notificaciones…
                            </p>
                        ) : (!error && notificaciones.length === 0) ? (
                            <div className="px-4 py-8 text-center text-sm text-zinc-400">
                                <Inbox className="w-8 h-8 mx-auto mb-2 text-zinc-600" />
                                No tenés notificaciones.
                            </div>
                        ) : (
                            <ul className="divide-y divide-zinc-800">
                                {notificaciones.map((n) => (
                                    <li key={n.id}
                                        className={`px-4 py-3 ${n.leida ? 'opacity-60' : ''}`}>
                                        <div className="flex items-start justify-between gap-2">
                                            <div className="min-w-0">
                                                <p className="text-[11px] uppercase tracking-wide text-orange-400 font-semibold">
                                                    {!n.leida && (
                                                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-orange-400 mr-1.5 align-middle" />
                                                    )}
                                                    {ETIQUETAS_TIPO[n.tipo] || n.tipo || 'Aviso'}
                                                </p>
                                                <p className="text-sm text-zinc-100 mt-0.5 break-words">
                                                    {n.mensaje}
                                                </p>
                                                <p className="text-[11px] text-zinc-500 mt-1">
                                                    {formatearFecha(n.created_at)}
                                                </p>
                                            </div>
                                            {!n.leida && (
                                                <button
                                                    type="button"
                                                    onClick={() => marcarLeida(n.id)}
                                                    disabled={accionando}
                                                    className="shrink-0 text-[11px] font-semibold text-emerald-400 hover:text-emerald-300 disabled:opacity-40"
                                                >
                                                    Marcar leída
                                                </button>
                                            )}
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default CampanaNotificaciones;

