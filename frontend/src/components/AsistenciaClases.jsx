import React, { useMemo, useState } from 'react';
import AsistenciaGrupoDisciplina from './AsistenciaGrupoDisciplina';
// Fase 2 (Bloque 2): las clases del día y el detalle de cada una salen de la caché
// compartida (la pestaña Asistencia del coach y del admin piden lo MISMO) y confirmar la
// asistencia es una mutación que invalida la familia `['asistencia']`.
import {
    useAlumnosDeClase, useAmpliarCupo, useClasesAsistenciaHoy, useConfirmarAsistenciaClase,
} from '../hooks/queries';

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

    // ─── Clases de hoy (React Query) ───────────────────────────────────
    const clasesQ = useClasesAsistenciaHoy();
    const clases = clasesQ.data || [];
    const cargando = clasesQ.isPending;
    const error = clasesQ.isError
        ? (clasesQ.error?.response?.data?.detail || 'Error al cargar las clases de hoy')
        : null;

    // ─── Clase abierta ─────────────────────────────────────────────────
    const [claseSeleccionada, setClaseSeleccionada] = useState(null);
    const [aviso, setAviso] = useState(null);

    const alumnosQ = useAlumnosDeClase(claseSeleccionada?.id);
    const reservas = useMemo(() => alumnosQ.data?.reservas || [], [alumnosQ.data]);
    const marcada = !!alumnosQ.data?.marcada;
    const cargandoReservas = Boolean(claseSeleccionada) && alumnosQ.isPending;

    // Si el detalle de la clase falla, el aviso del modal lo dice (mismo texto de antes).
    const mensaje = alumnosQ.isError
        ? {
            tipo: 'error',
            texto: alumnosQ.error?.response?.data?.detail || 'Error al cargar los alumnos de la clase',
        }
        : aviso;

    const confirmarAsistencia = useConfirmarAsistenciaClase();
    const ampliarCupoMut = useAmpliarCupo();
    const confirmando = confirmarAsistencia.isPending;

    // El marcado: la BASE es lo que dice el backend (si la clase ya fue marcada, lo
    // guardado; si no, NINGUNO — así un clic en Confirmar no marca la clase entera por
    // accidente) y `overrides` guarda SÓLO las decisiones del usuario. Sin estado que
    // haya que sembrar cuando llega la respuesta.
    const [overrides, setOverrides] = useState({});
    const guardado = useMemo(() => {
        const m = {};
        reservas.forEach((a) => { m[a.reserva_id] = !!a.asistio; });
        return m;
    }, [reservas]);
    const valor = (reservaId) => (
        reservaId in overrides ? overrides[reservaId] : (marcada ? !!guardado[reservaId] : false)
    );

    const formatearHora = (h) => {
        if (!h) return '';
        const partes = h.split(':');
        if (partes.length >= 2) return `${partes[0]}:${partes[1]}`;
        return h;
    };

    const abrirClase = (clase) => {
        setAviso(null);
        setOverrides({});   // cada clase arranca con su propio marcado
        setClaseSeleccionada(clase);
    };

    const cerrarClase = () => {
        setClaseSeleccionada(null);
        setOverrides({});
        setAviso(null);
    };

    const toggle = (reservaId) => {
        setOverrides((prev) => ({ ...prev, [reservaId]: !valor(reservaId) }));
    };

    const marcarTodos = (valorNuevo) => {
        const nuevo = {};
        reservas.forEach((a) => { nuevo[a.reserva_id] = valorNuevo; });
        setOverrides(nuevo);
    };

    const confirmar = async () => {
        if (!claseSeleccionada) return;
        setAviso(null);
        try {
            const asistencias = reservas.map((a) => ({
                reserva_id: parseInt(a.reserva_id, 10),
                asistio: !!valor(a.reserva_id),
            }));
            const r = await confirmarAsistencia.mutateAsync({
                claseId: claseSeleccionada.id,
                asistencias,
            });
            const confirmados = r?.confirmados ?? asistencias.length;
            cerrarClase();
            // La lista del día y el detalle de la clase se refrescan SOLOS (la mutación
            // invalida `['asistencia']`): la misma verdad para el panel del admin.
            setAviso({ tipo: 'exito', texto: `✅ Asistencia guardada (${confirmados} alumno(s))` });
        } catch (e) {
            setAviso({ tipo: 'error', texto: e.response?.data?.detail || 'Error al guardar la asistencia' });
        }
    };

    // Fase 2: agrupacion por disciplina respetando el orden del backend (dentro de
    // cada grupo tambien). El acordeon arranca abierto y el estado es local, no
    // persistido: al recargar vuelven a estar todos abiertos.
    const [cerradas, setCerradas] = useState({});
    const estaAbierta = (disciplina) => !cerradas[disciplina];
    const toggleGrupo = (disciplina) =>
        setCerradas((prev) => ({ ...prev, [disciplina]: !prev[disciplina] }));

    const grupos = useMemo(() => {
        const m = new Map();
        for (const c of clases) {
            const k = c.disciplina_nombre || 'Sin disciplina';
            if (!m.has(k)) m.set(k, []);
            m.get(k).push(c);
        }
        return [...m.entries()].map(([disciplina, items]) => ({ disciplina, clases: items }));
    }, [clases]);

    // Ampliar cupo de UNA clase puntual (el backend valida permisos y el tope +10).
    // Devuelve la promesa: el hijo pinta el cupo nuevo con la respuesta.
    const ampliarCupo = (clase, extra) => ampliarCupoMut.mutateAsync({ claseId: clase.id, extra });

    return (
        <div className="space-y-6">
            <div>
                <h2 className={`text-2xl font-bold ${osc ? 'text-zinc-100' : 'text-gray-900'}`}>📋 Asistencia de Hoy</h2>
                <p className={`mt-1 ${osc ? 'text-zinc-400' : 'text-gray-600'}`}>
                    Clases del día (hora de Chile) desde el horario actual. Confirma la
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
                        No hay clases de hoy desde este horario en tus disciplinas.
                    </p>
                </div>
            ) : (
                <div className="space-y-4">
                    {grupos.map((grupo) => (
                        <AsistenciaGrupoDisciplina
                            key={grupo.disciplina}
                            grupo={grupo}
                            osc={osc}
                            abierta={estaAbierta(grupo.disciplina)}
                            onToggle={() => toggleGrupo(grupo.disciplina)}
                            onAbrir={abrirClase}
                            formatearHora={formatearHora}
                            onAmpliarCupo={ampliarCupo}
                        />
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
                                    ? 'Asistencia ya guardada — corrige si hace falta y reconfirma.'
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
                                                    checked={valor(a.reserva_id)}
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
