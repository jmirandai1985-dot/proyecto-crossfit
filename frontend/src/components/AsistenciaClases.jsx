import React, { useState, useEffect, useCallback } from 'react';
import api from '../services/api';

/**
 * Pestaña "Asistencia" (compartida coach + admin, Fase 1).
 *
 * Muestra las clases del día actual (America/Santiago) desde la hora en
 * adelante. El backend filtra por rol: el coach ve solo sus disciplinas
 * asignadas; el admin/administrador ve TODAS las clases del tenant.
 * Al abrir una clase, lista las reservas con checks PRE-MARCADOS (si la clase
 * aún no fue marcada) y un botón único "Confirmar" que envía el batch a
 * POST /api/v1/asistencia/clases/{id}/confirmar (el backend registra la marca
 * como "via=admin" cuando la hace un admin).
 *
 * Prop:
 *   variant — 'light' (default, paneles claros, usado en el Dashboard Coach)
 *             | 'dark' (paneles zinc, usado en el panel de Administración)
 */
const AsistenciaClases = ({ variant = 'light' } = {}) => {
    const osc = variant === 'dark';

    const [clases, setClases] = useState([]);
    const [cargando, setCargando] = useState(true);
    const [error, setError] = useState(null);

    const [claseSeleccionada, setClaseSeleccionada] = useState(null);
    const [reservas, setReservas] = useState([]);
    const [marcada, setMarcada] = useState(false);
    const [cargandoReservas, setCargandoReservas] = useState(false);
    const [asistencias, setAsistencias] = useState({});
    const [confirmando, setConfirmando] = useState(false);
    const [mensaje, setMensaje] = useState(null);
    const [clasesMarcadas, setClasesMarcadas] = useState({});

    const cargarClases = useCallback(async () => {
        setCargando(true);
        setError(null);
        try {
            const r = await api.get('/api/v1/asistencia/clases-hoy');
            setClases(r.data || []);
        } catch (e) {
            setError(e.response?.data?.detail || 'Error al cargar las clases de hoy');
        }
        setCargando(false);
    }, []);

    useEffect(() => {
        cargarClases();
    }, [cargarClases]);

    const formatearHora = (h) => {
        if (!h) return '';
        const partes = h.split(':');
        if (partes.length >= 2) return `${partes[0]}:${partes[1]}`;
        return h;
    };

    const abrirClase = async (clase) => {
        setClaseSeleccionada(clase);
        setMensaje(null);
        setCargandoReservas(true);
        try {
            const r = await api.get(`/api/v1/asistencia/clases/${clase.id}/alumnos`);
            const data = r.data || {};
            const res = data.reservas || [];
            setReservas(res);
            setMarcada(!!data.marcada);
            // Checks por defecto: si la clase ya fue marcada, muestro lo
            // guardado; si no, todos pre-marcados como asistieron.
            const inicial = {};
            res.forEach((a) => {
                inicial[a.reserva_id] = data.marcada ? a.asistio : true;
            });
            setAsistencias(inicial);
        } catch (e) {
            setMensaje({ tipo: 'error', texto: e.response?.data?.detail || 'Error al cargar los alumnos de la clase' });
        }
        setCargandoReservas(false);
    };

    const cerrarClase = () => {
        setClaseSeleccionada(null);
        setReservas([]);
        setAsistencias({});
        setMensaje(null);
    };

    const toggle = (reservaId) => {
        setAsistencias((prev) => ({ ...prev, [reservaId]: !prev[reservaId] }));
    };

    const marcarTodos = (valor) => {
        const nuevo = {};
        reservas.forEach((a) => { nuevo[a.reserva_id] = valor; });
        setAsistencias(nuevo);
    };

    const confirmar = async () => {
        if (!claseSeleccionada) return;
        setConfirmando(true);
        setMensaje(null);
        try {
            const ids = Object.keys(asistencias);
            const payload = {
                asistencias: ids.map((rid) => ({
                    reserva_id: parseInt(rid, 10),
                    asistio: !!asistencias[rid],
                })),
            };
            const r = await api.post(
                `/api/v1/asistencia/clases/${claseSeleccionada.id}/confirmar`,
                payload
            );
            const confirmados = r.data?.confirmados || ids.length;
            setMensaje({ tipo: 'exito', texto: `✅ Asistencia guardada (${confirmados} alumno(s))` });
            setClasesMarcadas((prev) => ({ ...prev, [claseSeleccionada.id]: true }));
            cerrarClase();
            cargarClases();
        } catch (e) {
            setMensaje({ tipo: 'error', texto: e.response?.data?.detail || 'Error al guardar la asistencia' });
        }
        setConfirmando(false);
    };

    return (
        <div className="space-y-6">
            <div>
                <h2 className={`text-2xl font-bold ${osc ? 'text-zinc-100' : 'text-gray-900'}`}>📋 Asistencia de Hoy</h2>
                <p className={`mt-1 ${osc ? 'text-zinc-400' : 'text-gray-600'}`}>
                    Clases del día (hora de Chile) desde el horario actual. Confirmá la
                    asistencia de cada clase con un clic.
                </p>
            </div>

            {error && (
                <div className={`border-l-4 rounded-lg p-4 text-sm ${osc ? 'bg-red-500/10 border-red-500 text-red-300' : 'bg-red-50 border-red-500 text-red-700'}`}>
                    {error}
                </div>
            )}

            {cargando ? (
                <div className="flex items-center justify-center h-40">
                    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500"></div>
                </div>
            ) : clases.length === 0 ? (
                <div className={`text-center py-16 rounded-xl shadow-sm border ${osc ? 'bg-zinc-900 border-zinc-800' : 'bg-white border-gray-100'}`}>
                    <p className="text-5xl mb-4">📭</p>
                    <p className={`text-xl font-bold ${osc ? 'text-zinc-200' : 'text-gray-700'}`}>Sin clases pendientes</p>
                    <p className={`text-sm mt-2 ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>
                        No tenés clases de hoy desde este horario en tus disciplinas.
                    </p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {clases.map((clase) => (
                        <div key={clase.id} className={`rounded-xl shadow-sm border p-5 ${osc ? 'bg-zinc-900 border-zinc-800' : 'bg-white border-gray-100'}`}>
                            <div className="flex items-start justify-between">
                                <div>
                                    <p className={`font-semibold ${osc ? 'text-zinc-100' : 'text-gray-900'}`}>{clase.disciplina_nombre}</p>
                                    <p className={`text-sm mt-0.5 ${osc ? 'text-zinc-400' : 'text-gray-600'}`}>
                                        🕐 {formatearHora(clase.hora_inicio)} - {formatearHora(clase.hora_fin)}
                                    </p>
                                    <p className={`text-sm ${osc ? 'text-zinc-400' : 'text-gray-600'}`}>
                                        👥 {clase.reservas_count || 0} reservas
                                    </p>
                                </div>
                                <span
                                    className={`inline-flex items-center px-2 py-1 text-xs font-medium rounded-full ${
                                        clasesMarcadas[clase.id]
                                            ? (osc ? 'bg-green-500/20 text-green-400' : 'bg-green-100 text-green-700')
                                            : (osc ? 'bg-orange-500/20 text-orange-400' : 'bg-orange-100 text-orange-700')
                                    }`}
                                >
                                    {clasesMarcadas[clase.id] ? '✓ Confirmada' : 'Pendiente'}
                                </span>
                            </div>
                            <button
                                onClick={() => abrirClase(clase)}
                                className="mt-4 w-full px-4 py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors"
                            >
                                Marcar Asistencia
                            </button>
                        </div>
                    ))}
                </div>
            )}


            {/* Modal de confirmación por clase */}
            {claseSeleccionada && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className={`rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col ${osc ? 'bg-zinc-900 border border-zinc-800' : 'bg-white'}`}>
                        <div className={`px-6 py-4 border-b flex items-center justify-between ${osc ? 'border-zinc-800' : 'border-gray-200'}`}>
                            <div>
                                <h3 className={`text-lg font-bold ${osc ? 'text-zinc-100' : 'text-gray-900'}`}>
                                    {claseSeleccionada.disciplina_nombre}
                                </h3>
                                <p className={`text-sm ${osc ? 'text-zinc-400' : 'text-gray-600'}`}>
                                    🕐 {formatearHora(claseSeleccionada.hora_inicio)} -{' '}
                                    {formatearHora(claseSeleccionada.hora_fin)} · {reservas.length} reservas
                                </p>
                            </div>
                            <button
                                onClick={cerrarClase}
                                className={`text-2xl leading-none ${osc ? 'text-zinc-500 hover:text-zinc-300' : 'text-gray-400 hover:text-gray-600'}`}
                                aria-label="Cerrar"
                            >
                                ×
                            </button>
                        </div>

                        <div className="px-6 py-4 overflow-y-auto">
                            {mensaje && (
                                <div
                                    className={`mb-3 px-3 py-2 rounded-md text-sm font-medium border ${
                                        mensaje.tipo === 'exito'
                                            ? (osc ? 'bg-green-500/10 text-green-400 border-green-500/30' : 'bg-green-50 text-green-700 border-green-200')
                                            : (osc ? 'bg-red-500/10 text-red-400 border-red-500/30' : 'bg-red-50 text-red-700 border-red-200')
                                    }`}
                                >
                                    {mensaje.texto}
                                </div>
                            )}

                            <p className={`text-sm font-medium mb-3 ${osc ? 'text-zinc-300' : 'text-gray-700'}`}>
                                {marcada
                                    ? 'Asistencia ya guardada — corregí si hace falta y reconfirmá.'
                                    : 'Todos los alumnos vienen marcados por defecto.'}
                            </p>

                            <div className="flex gap-2 mb-3">
                                <button
                                    onClick={() => marcarTodos(true)}
                                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                                        osc ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-green-100 text-green-700 hover:bg-green-200'
                                    }`}
                                >
                                    ✓ Todos asistieron
                                </button>
                                <button
                                    onClick={() => marcarTodos(false)}
                                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                                        osc ? 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                                    }`}
                                >
                                    ✗ Ninguno
                                </button>
                            </div>

                            {cargandoReservas ? (
                                <div className="flex items-center justify-center py-10">
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                                </div>
                            ) : reservas.length === 0 ? (
                                <p className={`text-center py-10 text-sm ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>
                                    Esta clase no tiene reservas activas.
                                </p>
                            ) : (
                                <ul className="space-y-2">
                                    {reservas.map((a) => (
                                        <li
                                            key={a.reserva_id}
                                            className={`flex items-center justify-between p-3 rounded-lg border ${osc ? 'border-zinc-800' : 'border-gray-200'}`}
                                        >
                                            <span className={`text-sm font-medium ${osc ? 'text-zinc-200' : 'text-gray-800'}`}>{a.nombre}</span>
                                            <label className="flex items-center gap-2 cursor-pointer select-none">
                                                <span className={`text-xs ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>Asistió</span>
                                                <input
                                                    type="checkbox"
                                                    checked={!!asistencias[a.reserva_id]}
                                                    onChange={() => toggle(a.reserva_id)}
                                                    className="w-5 h-5 accent-orange-500"
                                                />
                                            </label>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                        <div className={`px-6 py-4 border-t flex justify-end gap-2 ${osc ? 'border-zinc-800' : 'border-gray-200'}`}>
                            <button
                                onClick={cerrarClase}
                                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                                    osc ? 'text-zinc-300 hover:bg-zinc-800' : 'text-gray-600 hover:bg-gray-100'
                                }`}
                            >
                                Cancelar
                            </button>
                            <button
                                onClick={confirmar}
                                disabled={confirmando || reservas.length === 0}
                                className="px-6 py-2 bg-orange-500 text-white rounded-lg text-sm font-bold hover:bg-orange-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {confirmando ? 'Guardando...' : 'Confirmar'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default AsistenciaClases;
