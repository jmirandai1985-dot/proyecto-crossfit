import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Bell, CheckCheck, Inbox, RefreshCw, X } from 'lucide-react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';

// ══════════════════════════════════════════════════════════════════════════
//  N-2 — Campana de notificaciones del ALUMNO (Layout del panel alumno)
//
//  Contrato de la UI:
//    * contador de NO leídas: consulta al montar + refresco cada 45 s y al
//      volver el foco a la ventana. Sin eso, el admin aprobaba un voucher o
//      entraba un pedido y el badge seguía en 0 hasta recargar la página;
//    * el panel se REFRESCA AL ABRIRLO y el refresco de fondo se PAUSA mientras
//      está abierto (no se pisa la lista que el usuario está leyendo);
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
    // Solicitud de plan con voucher: la pide el alumno y la revisa el ADMIN
    // (solicitudes_planes.py -> notificar_admins_del_tenant).
    plan_solicitado: 'Solicitud de plan (voucher)',
    // Alta de alumno por autoservicio (alumnos.py -> admins del box).
    alumno_nuevo: 'Alumno nuevo',
    // Cobertura de emergencia: un coach cubrió una clase que no era suya
    // (core/dependencies.py -> admins del box).
    emergencia: 'Cobertura de emergencia',
    // Bazar: aviso de campana al admin del box y al alumno dueño (pedidos.py).
    pedido_nuevo: 'Pedido nuevo (Bazar)',
    pedido_validado: 'Pedido validado',
    pedido_entregado: 'Pedido entregado',
    // Supervisión → Coach (B3/B4): el admin asignó, reasignó o liberó una clase
    // y el coach se entera por SU campana (services/asignaciones_clases.py).
    clase_asignada: 'Clase asignada',
    clase_reasignada: 'Clase reasignada',
    clase_liberada: 'Clase liberada',
};

// Pantalla propia de cada tipo de aviso: la fila navega al hacer click. El
// backend no guarda URLs, así que el destino se deriva del `tipo` (igual que
// hace la tabla de Notificaciones Enviadas con destinoNotificacion.js).
const DESTINOS_TIPO = {
    pedido_nuevo: '/admin/pedidos',
    pedido_validado: '/alumno/mis-pedidos',
    pedido_entregado: '/alumno/mis-pedidos',
    // Planes: la solicitud pendiente se revisa en el Dashboard del admin; el
    // alumno ve el estado de su trámite en su pantalla de solicitar plan.
    plan_solicitado: '/admin/dashboard',
    aprobado: '/alumno/solicitar-plan',
    rechazado: '/alumno/solicitar-plan',
    // Alta de alumno: la lista de alumnos del box.
    alumno_nuevo: '/admin/alumnos-pendientes',
    // Cobertura de emergencia: la grilla de Supervisión (marca "emergencia").
    emergencia: '/admin/supervision-clases',
    // Los avisos de clase van SIEMPRE a un coach: su grilla de clases.
    clase_asignada: '/coach/gestion-clases',
    clase_reasignada: '/coach/gestion-clases',
    clase_liberada: '/coach/gestion-clases',
};

// Rol(es) que pueden abrir cada destino. Evita ofrecer (y seguir) un link a una
// pantalla de otro rol si un aviso llegara a un destinatario inesperado: en ese
// caso la fila queda sin link, pero se puede leer y marcar como leída.
// La campana es la MISMA para alumno, admin y coach (Layout.jsx).
const ROLES_POR_TIPO = {
    pedido_nuevo: ['administrador', 'admin'],
    pedido_validado: ['alumno'],
    pedido_entregado: ['alumno'],
    plan_solicitado: ['administrador', 'admin'],
    aprobado: ['alumno'],
    rechazado: ['alumno'],
    alumno_nuevo: ['administrador', 'admin'],
    emergencia: ['administrador', 'admin'],
    clase_asignada: ['coach'],
    clase_reasignada: ['coach'],
    clase_liberada: ['coach'],
};

/** Ruta del aviso para el rol actual (null = la fila NO navega). */
const destinoDe = (tipo, rol) => {
    const destino = DESTINOS_TIPO[tipo];
    if (!destino) return null;
    const roles = ROLES_POR_TIPO[tipo];
    if (roles && !roles.includes(rol)) return null;
    return destino;
};

const CampanaNotificaciones = () => {
    // El rol decide si un aviso puede abrir su pantalla (ROLES_POR_TIPO): la
    // misma campana la usan alumno, admin y —desde B4— el coach.
    const { rol } = useAuth();
    const [abierto, setAbierto] = useState(false);
    const [noLeidas, setNoLeidas] = useState(0);
    const [contadorError, setContadorError] = useState('');
    const [notificaciones, setNotificaciones] = useState([]);
    const [cargando, setCargando] = useState(false);
    const [error, setError] = useState('');
    const [accionando, setAccionando] = useState(false);
    const navigate = useNavigate();

    // ── Contador: consulta al montar + refresco de fondo (ver el efecto de abajo) ──
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

    // ── F4: el contador se entera SOLO de los avisos nuevos ──
    // El aviso lo provoca OTRO usuario (el alumno sube el voucher, compra en el
    // Bazar, se registra) mientras el admin puede estar en cualquier pantalla:
    // sin este refresco el badge sólo cambiaba al recargar la página. Mismo
    // intervalo que la grilla de Supervisión (45 s) y también al volver el foco
    // a la ventana (el caso más común: volver después de estar en otra app).
    // Se PAUSA con el panel abierto: la lista se refresca al abrirlo y el usuario
    // puede estar leyéndola (no se pisa).
    useEffect(() => {
        const vigilarContador = () => {
            if (!abierto) cargarContador();
        };
        const intervalo = setInterval(vigilarContador, 45000);
        window.addEventListener('focus', vigilarContador);
        return () => {
            clearInterval(intervalo);
            window.removeEventListener('focus', vigilarContador);
        };
    }, [cargarContador, abierto]);

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

    // Ir a la pantalla del aviso (si el tipo tiene una) y cerrar el panel.
    const abrirDestino = (tipo) => {
        const destino = destinoDe(tipo, rol);
        if (!destino) return;
        setAbierto(false);
        navigate(destino);
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
                                No tienes notificaciones.
                            </div>
                        ) : (
                            <ul className="divide-y divide-zinc-800">
                                {notificaciones.map((n) => {
                                    const destino = destinoDe(n.tipo, rol);
                                    return (
                                    <li key={n.id}
                                        {...(destino ? {
                                            onClick: () => abrirDestino(n.tipo),
                                            role: 'button',
                                            tabIndex: 0,
                                            onKeyDown: (e) => {
                                                if (e.key === 'Enter' || e.key === ' ') {
                                                    e.preventDefault();
                                                    abrirDestino(n.tipo);
                                                }
                                            },
                                        } : {})}
                                        className={`px-4 py-3 ${n.leida ? 'opacity-60' : ''} ${destino ? 'cursor-pointer hover:bg-zinc-800/60 transition-colors' : ''}`}>
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
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        marcarLeida(n.id);
                                                    }}
                                                    disabled={accionando}
                                                    className="shrink-0 text-[11px] font-semibold text-emerald-400 hover:text-emerald-300 disabled:opacity-40"
                                                >
                                                    Marcar leída
                                                </button>
                                            )}
                                        </div>
                                    </li>
                                    );
                                })}
                            </ul>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default CampanaNotificaciones;

