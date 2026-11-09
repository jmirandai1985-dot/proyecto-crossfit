import React, { useMemo, useState } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import {
    useCoachDisciplinas, useDesactivarUsuario, useDisciplinas, useGuardarUsuario,
    useReemplazarCoachDisciplinas, useUsuariosPorRol, SIN_DATOS,
} from '../../hooks/queries';

const AVATAR_BG = [
    'linear-gradient(135deg, #3b72f6, #1d4ed8)',
    'linear-gradient(135deg, #f0594f, #b91c1c)',
    'linear-gradient(135deg, #2dd4bf, #0d9488)',
    'linear-gradient(135deg, #9b7bff, #6d28d9)',
    'linear-gradient(135deg, #f5a524, #b45309)',
    'linear-gradient(135deg, #ec4899, #be185d)',
];

const colorIndice = (id) => {
    const s = String(id);
    let h = 0;
    for (let i = 0; i < s.length; i += 1) { h = (h * 31 + s.charCodeAt(i)) >>> 0; }
    return h % AVATAR_BG.length;
};

const iniciales = (nombre) => {
    const words = (nombre || '').trim().split(/\s+/).filter(Boolean);
    if (!words.length) return '?';
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
};

const estadoCoach = (coach) => (
    (coach.estado || (coach.activo === false ? 'baja' : 'activo')) === 'activo' ? 'activo' : 'baja'
);

const Coaches = () => {
    const { tenant_id } = useAuth();
    // Bloque 3 (parte A): los tres GET de esta pantalla salen de la caché compartida.
    // El padrón de coaches es el MISMO `GET /usuarios/?rol=coach` que pedía el modal de
    // clase (antes eran dos llamadas idénticas), las disciplinas las comparten Clases,
    // Horarios y ese mismo modal, y las relaciones coach<->disciplina también las lee el
    // Dashboard del coach. Guardar/desactivar invalida los prefijos correspondientes.
    const {
        data: coachesData, isPending: cargandoCoaches, isError: errorCargaCoaches, refetch: refetchCoaches,
    } = useUsuariosPorRol('coach');
    const coaches = coachesData || SIN_DATOS;
    const { data: discData, isError: errorCargaDisciplinas, refetch: refetchDisciplinas } = useDisciplinas();
    // Sólo las activas son asignables (mismo filtro que hacía el fetch a mano).
    const disciplinas = useMemo(
        () => (discData ? discData.filter((d) => d.activo !== false) : SIN_DATOS),
        [discData],
    );
    const {
        data: asignacionesData, isPending: cargandoAsignaciones, isError: errorCargaAsignaciones,
        refetch: refetchAsignaciones,
    } = useCoachDisciplinas();
    // Mapa coach_id -> [disciplina_id] con las asignaciones ACTIVAS (el backend también
    // devuelve filas dadas de baja).
    const coachDisciplinasMap = useMemo(() => {
        const map = {};
        (asignacionesData || []).forEach((cd) => {
            if (cd.activo) {
                if (!map[cd.coach_id]) map[cd.coach_id] = [];
                map[cd.coach_id].push(cd.disciplina_id);
            }
        });
        return map;
    }, [asignacionesData]);
    // Si las asignaciones no cargaran, guardar un coach le borraría sus disciplinas: la
    // pantalla bloquea el guardado (mismo contrato que antes, ahora derivado del query).
    const asignacionesListas = !cargandoAsignaciones && !errorCargaAsignaciones;
    const errorCoaches = errorCargaCoaches ? 'No se pudieron cargar los coaches. Reintenta.' : '';
    const errorDisciplinas = errorCargaDisciplinas ? 'No se pudieron cargar las disciplinas.' : '';
    // El aviso de "asignaciones bloqueadas" lo dispara la pantalla (openModal/handleSubmit);
    // si el query falló, el mensaje del query tiene prioridad.
    const [avisoAsignaciones, setAvisoAsignaciones] = useState('');
    // El aviso se apaga solo cuando las asignaciones ya cargaron: si el admin reintenta y la
    // carga sale bien, el aviso deja de mostrar una traba que ya no existe.
    const errorAsignaciones = errorCargaAsignaciones
        ? 'No se pudieron cargar las asignaciones del coach.'
        : (asignacionesListas ? '' : avisoAsignaciones);
    const loading = cargandoCoaches;
    const guardarUsuario = useGuardarUsuario();
    const reemplazarDisciplinas = useReemplazarCoachDisciplinas();
    const desactivarUsuario = useDesactivarUsuario();
    const [showModal, setShowModal] = useState(false);
    const [editingCoach, setEditingCoach] = useState(null);
    const [msgOperacion, setMsgOperacion] = useState(null);
    const [confirmarEliminar, setConfirmarEliminar] = useState(null);
    const [formData, setFormData] = useState({
        nombre: '',
        correo: '',
        password: '',
        disciplina_ids: [],
        estado: 'activo',
    });

    const openModal = (coach = null) => {
        if (coach && !asignacionesListas) { setAvisoAsignaciones('No se pudieron cargar las asignaciones del coach: la edicion esta bloqueada hasta que carguen. Reintenta.'); return; }
        if (coach) {
            setEditingCoach(coach);
            setFormData({
                nombre: coach.nombre,
                correo: coach.correo,
                password: '',
                disciplina_ids: coachDisciplinasMap[coach.id] || [],
                estado: (coach.estado === 'activo' || (!coach.estado && coach.activo)) ? 'activo' : 'inactivo',
            });
        } else {
            setEditingCoach(null);
            setFormData({ nombre: '', correo: '', password: '', disciplina_ids: [], estado: 'activo' });
        }
        setShowModal(true);
    };

    const closeModal = () => {
        setShowModal(false);
        setEditingCoach(null);
        setFormData({ nombre: '', correo: '', password: '', disciplina_ids: [], estado: 'activo' });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!asignacionesListas) { setAvisoAsignaciones('No se pudieron cargar las asignaciones actuales del coach. Para no borrar sus disciplinas, no se guarda. Reintenta la carga.'); return; }
        setMsgOperacion(null);
        try {
            let coachId;
            if (editingCoach) {
                await guardarUsuario.mutateAsync({
                    id: editingCoach.id,
                    payload: {
                        nombre: formData.nombre,
                        correo: formData.correo,
                        estado: formData.estado === 'activo' ? 'activo' : 'baja',
                    },
                });
                coachId = editingCoach.id;
            } else {
                const res = await guardarUsuario.mutateAsync({
                    payload: {
                        nombre: formData.nombre,
                        correo: formData.correo,
                        password: formData.password,
                        rol: 'coach',
                        rut: 'TEMP-' + Date.now().toString().slice(-7), // PLACEHOLDER temporal: RUT unico por coach (backend exige rut 7-12 chars, no lo pide el form todavia)
                    },
                });
                coachId = res.id;
            }

            // Asignar disciplinas en coach_disciplinas: reemplaza el set completo.
            if (coachId) {
                await reemplazarDisciplinas.mutateAsync({
                    tenant_id: tenant_id,
                    coach_id: coachId,
                    disciplina_ids: formData.disciplina_ids,
                });
            }

            setMsgOperacion({ tipo: 'exito', texto: 'Coach guardado' });
        } catch (error) {
            setMsgOperacion({ tipo: 'error', texto: error.response?.data?.detail || error.message });
        }
    };

    const toggleDisciplina = (discId) => {
        setFormData(prev => ({
            ...prev,
            disciplina_ids: prev.disciplina_ids.includes(discId)
                ? prev.disciplina_ids.filter(id => id !== discId)
                : [...prev.disciplina_ids, discId],
        }));
    };

    const getDisciplinaNombre = (discId) => {
        const disc = disciplinas.find(d => d.id === discId);
        return disc ? disc.nombre : `ID ${discId}`;
    };

    const activos = coaches.filter((c) => estadoCoach(c) === 'activo');
    const bajas = coaches.filter((c) => estadoCoach(c) !== 'activo');

    const renderCoach = (coach) => {
        const discIds = coachDisciplinasMap[coach.id] || [];
        const activo = estadoCoach(coach) === 'activo';
        return (
            <article key={coach.id} className={`rounded-2xl border border-zinc-800 border-l-4 ${activo ? 'border-l-green-500' : 'border-l-zinc-500'} bg-zinc-900 p-4`}>
                <div className="flex items-start gap-3">
                    <span className="w-12 h-12 rounded-full flex items-center justify-center text-white font-bold shrink-0"
                        style={{ background: AVATAR_BG[colorIndice(coach.id)] }}>
                        {iniciales(coach.nombre)}
                    </span>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                            <h3 className="font-bold text-zinc-100 truncate">{coach.nombre}</h3>
                            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-bold ${activo ? 'bg-green-500/15 text-green-300' : 'bg-zinc-700/40 text-zinc-400'}`}>
                                {activo ? 'Activo' : 'Baja'}
                            </span>
                        </div>
                        <p className="text-sm text-zinc-400 truncate">{coach.correo}</p>
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {discIds.length > 0 ? discIds.map((id) => (
                                <span key={id} className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700">
                                    {getDisciplinaNombre(id)}
                                </span>
                            )) : (
                                <span className="text-xs text-zinc-500">Sin disciplinas asignadas</span>
                            )}
                        </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                        <button onClick={() => openModal(coach)} disabled={!asignacionesListas}
                            title="Editar" aria-label={`Editar ${coach.nombre}`}
                            className="w-8 h-8 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-400 hover:border-blue-500 hover:text-blue-400 transition-colors disabled:opacity-50">✎</button>
                        <button onClick={() => setConfirmarEliminar(coach)}
                            title="Dar de baja" aria-label={`Dar de baja a ${coach.nombre}`}
                            className="w-8 h-8 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-400 hover:border-red-500 hover:text-red-500 transition-colors">✕</button>
                    </div>
                </div>
            </article>
        );
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                        <p className="text-zinc-400">Cargando coaches...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    // Desactivacion (soft delete en el backend): la confirmacion vive en el modal propio.
    const desactivarConfirmado = async () => {
        const coach = confirmarEliminar;
        setConfirmarEliminar(null);
        try {
            // La baja la aplica el backend (estado='baja') y la mutación invalida
            // `['usuarios']`: la tabla y el modal de clase se refrescan solos.
            await desactivarUsuario.mutateAsync(coach.id);
            setMsgOperacion({ tipo: 'exito', texto: 'Coach desactivado' });
        } catch (error) {
            setMsgOperacion({ tipo: 'error', texto: error.response?.data?.detail || 'No se pudo desactivar el coach' });
        }
    };

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-zinc-100">Gestión de Coaches</h1><p className="text-zinc-400 mt-1">Administra los entrenadores de tu box</p></div>
                    <button onClick={() => openModal()} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Agregar Coach</button>
                </div>

                {errorCoaches && (
                    <div className="border-l-4 rounded-lg p-4 text-sm bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-3">
                        <span>{errorCoaches}</span>
                        <button onClick={() => refetchCoaches()} className="px-3 py-1.5 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                    </div>
                )}
                {errorAsignaciones && (
                    <div className="border-l-4 rounded-lg p-4 text-sm bg-orange-500/10 border-orange-500 text-orange-300 flex items-center justify-between gap-3">
                        <span>{errorAsignaciones} Mientras no carguen, la edicion de coaches esta bloqueada.</span>
                        <button onClick={() => refetchAsignaciones()} className="px-3 py-1.5 bg-orange-500 text-white rounded text-xs font-medium hover:bg-orange-600">Reintentar</button>
                    </div>
                )}
                {errorDisciplinas && (
                    <div className="border-l-4 rounded-lg p-4 text-sm bg-amber-500/10 border-amber-500 text-amber-300 flex items-center justify-between gap-3">
                        <span>{errorDisciplinas}</span>
                        <button onClick={() => refetchDisciplinas()} className="px-3 py-1.5 bg-amber-600 text-white rounded text-xs font-medium hover:bg-amber-700">Reintentar</button>
                    </div>
                )}
                {msgOperacion && (
                    <div className={`border-l-4 rounded-lg p-4 text-sm ${msgOperacion.tipo === 'exito' ? 'bg-green-500/10 border-green-500 text-green-300' : 'bg-red-500/10 border-red-500 text-red-300'}`}>
                        {msgOperacion.texto}
                    </div>
                )}

                {/* KPIs en franja horizontal */}
                <div className="flex flex-wrap gap-3">
                    <div className="flex items-center gap-2.5 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5">
                        <span className="w-1 h-8 rounded-full bg-blue-500 shrink-0"></span>
                        <div>
                            <div className="text-[10.5px] text-zinc-400 font-semibold uppercase tracking-wide">Total de Coaches</div>
                            <div className="text-xl font-extrabold text-zinc-100 leading-tight">{coaches.length}</div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2.5 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5">
                        <span className="w-1 h-8 rounded-full bg-green-500 shrink-0"></span>
                        <div>
                            <div className="text-[10.5px] text-zinc-400 font-semibold uppercase tracking-wide">Coaches Activos</div>
                            <div className="text-xl font-extrabold text-zinc-100 leading-tight">{coaches.filter((c) => (c.estado || (c.activo === false ? 'baja' : 'activo')) === 'activo').length}</div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2.5 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5">
                        <span className="w-1 h-8 rounded-full bg-orange-500 shrink-0"></span>
                        <div>
                            <div className="text-[10.5px] text-zinc-400 font-semibold uppercase tracking-wide">Disciplinas Asignadas</div>
                            <div className="text-xl font-extrabold text-zinc-100 leading-tight">{new Set(Object.values(coachDisciplinasMap).flat()).size}</div>
                        </div>
                    </div>
                </div>

                {/* Coaches agrupados por estado */}
                {coaches.length > 0 ? (
                    <>
                        {activos.length > 0 && (
                            <div>
                                <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-zinc-300">Activos</h2>
                                <div className="space-y-3">{activos.map(renderCoach)}</div>
                            </div>
                        )}
                        {bajas.length > 0 && (
                            <div>
                                <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-zinc-300">Dados de baja</h2>
                                <div className="space-y-3">{bajas.map(renderCoach)}</div>
                            </div>
                        )}
                    </>
                ) : (
                    <div className="text-center py-12"><p className="text-zinc-400 text-lg">No hay coaches registrados</p></div>
                )}

                {showModal && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full">
                            <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                                <h2 className="text-xl font-bold">{editingCoach ? 'Editar Coach' : 'Nuevo Coach'}</h2>
                            </div>
                            <form onSubmit={handleSubmit} className="p-6 space-y-4">
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Nombre Completo</label>
                                    <input type="text" value={formData.nombre} onChange={e => setFormData({ ...formData, nombre: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500" required />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Correo Electrónico</label>
                                    <input type="email" value={formData.correo} onChange={e => setFormData({ ...formData, correo: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg" required />
                                </div>
                                {!editingCoach && (
                                    <div>
                                        <label className="block text-sm font-medium text-zinc-300 mb-1">Contraseña</label>
                                        <input type="password" value={formData.password} onChange={e => setFormData({ ...formData, password: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg" required />
                                    </div>
                                )}
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-2">Disciplinas Asignadas</label>
                                    <div className="space-y-2 max-h-48 overflow-y-auto border border-zinc-800 rounded-lg p-3">
                                        {disciplinas.length === 0 && (
                                            <p className="text-sm text-zinc-500 italic">No hay disciplinas activas</p>
                                        )}
                                        {disciplinas.map(d => (
                                            <label key={d.id} className="flex items-center gap-2 cursor-pointer hover:bg-zinc-800/50 p-1.5 rounded">
                                                <input
                                                    type="checkbox"
                                                    checked={formData.disciplina_ids.includes(d.id)}
                                                    onChange={() => toggleDisciplina(d.id)}
                                                    className="rounded border-zinc-700 text-orange-500 focus:ring-orange-500"
                                                />
                                                <span className="text-sm text-zinc-300">{d.nombre}</span>
                                            </label>
                                        ))}
                                    </div>
                                </div>
                                {editingCoach && (
                                <div>
                                    <label className="block text-sm font-medium text-zinc-300 mb-1">Estado</label>
                                    <select value={formData.estado} onChange={e => setFormData({ ...formData, estado: e.target.value })} className="w-full px-3 py-2 border border-zinc-700 rounded-lg">
                                        <option value="activo">Activo</option>
                                        <option value="inactivo">Inactivo</option>
                                    </select>
                                </div>
                                )}
                                {!editingCoach && (
                                    <p className="text-xs text-zinc-500">Al crear, el coach queda activo. El estado se edita despues.</p>
                                )}
                                <div className="flex gap-3 pt-4">
                                    <button type="button" onClick={closeModal} className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium">Cancelar</button>
                                    <button type="submit" disabled={!asignacionesListas} className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium">{editingCoach ? 'Actualizar' : 'Crear'}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
                {confirmarEliminar && (
                    <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4">
                        <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6">
                            <h2 className="text-xl font-bold text-zinc-100 mb-3">Desactivar coach</h2>
                            <p className="text-sm text-zinc-300 mb-5">Confirma desactivar a {confirmarEliminar.nombre}? Dejara de aparecer como activo (no se borra su historial).</p>
                            <div className="flex gap-3">
                                <button onClick={() => setConfirmarEliminar(null)} className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium">Cancelar</button>
                                <button onClick={desactivarConfirmado} className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium">Desactivar</button>
                            </div>
                        </div>
                    </div>
                )}
        </Layout>
    );
};

export default Coaches;