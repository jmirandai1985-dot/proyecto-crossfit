/**
 * Ficha del alumno para el panel COACH (P2).
 *
 * Por qué no se reusa el AlumnoFichaModal de Admin: ese modal pega a
 * GET /usuarios/{id} y GET /suscripciones, que son admin-only (un coach
 * recibiría 403). Acá se usa un único endpoint coach-scoped que devuelve
 * EXACTAMENTE los 4 datos que el coach necesita: teléfono, antigüedad
 * (fecha de alta), plan actual y créditos/vencimiento reales.
 * Sin datos financieros.
 *
 * El dato lo trae `useFichaAlumnoCoach` (caché compartida, Bloque 6): reabrir la ficha pinta
 * al instante lo último visto y revalida en segundo plano; "Reintentar" es un `refetch`.
 */
import React, { useEffect, useState } from 'react';
import { useActualizarPerfilAlumnoCoach, useFichaAlumnoCoach, useRmsAlumno } from '../hooks/queries';
import { fmtFechaChile, fmtFechaCortaChile } from '../utils/fecha';
// El valor y la categoría de un RM salen de la fuente única (utils/rm.js, H-03): acá NO se
// repite el criterio. Importa de verdad: el `peso_kg` de cardio/máquinas es un dummy
// (en la BD real hay Air Runner con 530 "kg"), así que pintar `peso_kg` mostraría un número
// sin sentido; `formatResultadoRM` usa la medida de la categoría (km/min/vueltas/cal/reps).
import { formatResultadoRM, inferirCategoriaRM } from '../utils/rm';

const fmtFecha = (f) => (f ? fmtFechaChile(f) : '—');

// Nombre de la categoría (mismo vocabulario que el resto de la UI: "Fuerza"/"Gimnasia").
const CATEGORIA_RM = {
    fuerza: 'Fuerza', gimnastico: 'Gimnasia', cardio: 'Cardio', metabolico: 'Máquinas',
};

const AlumnoFichaCoach = ({ alumnoId, coachId, onClose }) => {
    // El dato sale de la caché compartida (Bloque 6): volver a abrir la ficha pinta al
    // instante lo último visto mientras React Query revalida en segundo plano.
    const fichaQ = useFichaAlumnoCoach(coachId, alumnoId);
    const ficha = fichaQ.data || null;
    // `isPending` = primera carga (todavía no hay dato); una revalidación no la esconde.
    const cargando = Boolean(alumnoId) && fichaQ.isPending;
    const error = fichaQ.isError
        ? (fichaQ.error?.response?.data?.detail || 'No se pudo cargar la ficha del alumno.')
        : '';

    // RMs del alumno: MISMO endpoint coach-scoped que usa el panel del tab Alumnos
    // (`GET /historial-rm/alumnos/{id}/rms`), así que no hace falta ningún permiso nuevo.
    // Consulta aparte de la ficha: si la ficha falla, los RMs se muestran igual.
    const rmsQ = useRmsAlumno(alumnoId);
    const rms = rmsQ.data || [];
    const cargandoRms = Boolean(alumnoId) && rmsQ.isPending;
    const errorRms = rmsQ.isError
        ? (rmsQ.error?.response?.data?.detail || 'No se pudieron cargar los RMs.')
        : '';

    // ── D2: peso y género editables por el coach ──────────────────────────────
    // Son los dos datos que el motor de niveles necesita. El formulario se hidrata con la
    // ficha y se re-sincroniza cuando llega una ficha nueva (revalidación al guardar).
    const perfilMut = useActualizarPerfilAlumnoCoach();
    const [peso, setPeso] = useState('');
    const [genero, setGenero] = useState('');
    const [avisoPerfil, setAvisoPerfil] = useState('');

    useEffect(() => {
        if (!ficha) return;
        setPeso(ficha.peso_kg !== null && ficha.peso_kg !== undefined ? String(ficha.peso_kg) : '');
        setGenero(ficha.genero || '');
    }, [ficha]);

    const guardarPerfil = async (e) => {
        e.preventDefault();
        setAvisoPerfil('');
        const pesoNum = parseFloat(peso);
        if (!Number.isFinite(pesoNum) || pesoNum <= 0 || pesoNum > 400) {
            setAvisoPerfil('Ingresá un peso válido (1–400 kg).');
            return;
        }
        if (!['M', 'F'].includes(genero)) {
            setAvisoPerfil('Elegí masculino (M) o femenino (F).');
            return;
        }
        try {
            await perfilMut.mutateAsync({ coachId, alumnoId, peso_kg: pesoNum, genero });
            setAvisoPerfil('Perfil actualizado.');
        } catch (err) {
            setAvisoPerfil(err.response?.data?.detail || 'No se pudo guardar el perfil.');
        }
    };

    if (!alumnoId) return null;

    const plan = ficha?.plan;
    const creditos = plan?.creditos_disponibles;

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" data-testid="ficha-coach-modal">
            {/* La ficha ahora lleva los RMs: con `max-h` + cuerpo scrolleable entra en un
                teléfono chico (375×568) y el botón Cerrar queda siempre a la vista. */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div>
                        <h3 className="text-lg font-bold text-zinc-100">
                            {ficha?.nombre || 'Ficha del alumno'}
                        </h3>
                        <p className="text-sm text-zinc-400">{ficha?.correo || '—'}</p>
                    </div>
                    <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100 text-xl leading-none" aria-label="Cerrar">×</button>
                </div>

                <div className="p-5 space-y-4 overflow-y-auto min-h-0">
                    {cargando && (
                        <div className="flex justify-center py-8">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                        </div>
                    )}

                    {!cargando && error && (
                        <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300">
                            <p className="font-medium">⚠️ {error}</p>
                            <button onClick={() => fichaQ.refetch()} className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">
                                Reintentar
                            </button>
                        </div>
                    )}

                    {!cargando && !error && ficha && (
                        <>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="bg-zinc-800/60 rounded-lg p-3">
                                    <p className="text-xs text-zinc-500">Teléfono</p>
                                    <p className="text-zinc-100 font-medium" data-testid="ficha-telefono">
                                        {ficha.telefono || 'Sin teléfono'}
                                    </p>
                                </div>
                                <div className="bg-zinc-800/60 rounded-lg p-3">
                                    <p className="text-xs text-zinc-500">Alumno desde</p>
                                    <p className="text-zinc-100 font-medium" data-testid="ficha-alta">
                                        {fmtFecha(ficha.created_at)}
                                    </p>
                                    {ficha.antiguedad_dias !== null && ficha.antiguedad_dias !== undefined && (
                                        <p className="text-xs text-zinc-500 mt-0.5">{ficha.antiguedad_dias} días</p>
                                    )}
                                </div>
                            </div>

                            <div className="bg-zinc-800/60 rounded-lg p-4">
                                <p className="text-xs text-zinc-500 mb-2">Plan actual</p>
                                {plan ? (
                                    <div className="space-y-3">
                                        <p className="text-zinc-100 font-semibold" data-testid="ficha-plan">
                                            {plan.nombre || `Plan ID ${plan.plan_id}`}
                                        </p>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div>
                                                <p className="text-xs text-zinc-500">Créditos disponibles</p>
                                                <p className="text-zinc-100 font-bold text-lg" data-testid="ficha-creditos">
                                                    {plan.es_ilimitado ? '∞' : (creditos === null || creditos === undefined ? '—' : creditos)}
                                                </p>
                                            </div>
                                            <div>
                                                <p className="text-xs text-zinc-500">Vence el</p>
                                                <p className="text-zinc-100 font-medium" data-testid="ficha-vencimiento">
                                                    {plan.fecha_expiracion ? fmtFecha(plan.fecha_expiracion) : '—'}
                                                </p>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <p className="text-zinc-400 text-sm" data-testid="ficha-sin-plan">
                                        Sin plan activo
                                    </p>
                                )}
                            </div>

                            {/* ── D2: peso y género ───────────────────────────────────────
                                Son los datos que el motor de niveles necesita (ratio y tabla
                                M/F). El alta vieja no los pedía: acá el coach los carga o
                                corrige, y el badge de nivel sale de esta información. */}
                            <div className="bg-zinc-800/60 rounded-lg p-4" data-testid="ficha-perfil-nivel">
                                <div className="flex items-center justify-between mb-2">
                                    <p className="text-xs text-zinc-500">Datos para el nivel</p>
                                    {ficha.perfil_completo ? (
                                        <span className="text-[10px] px-2 py-0.5 rounded-full border border-emerald-500/40 text-emerald-300">
                                            Completo
                                        </span>
                                    ) : (
                                        <span className="text-[10px] px-2 py-0.5 rounded-full border border-orange-500/40 text-orange-300">
                                            Falta completar
                                        </span>
                                    )}
                                </div>
                                <form onSubmit={guardarPerfil} className="flex flex-col gap-3 sm:flex-row sm:items-end">
                                    <div className="flex-1">
                                        <label htmlFor="ficha-peso" className="block text-xs text-zinc-500 mb-1">
                                            Peso (kg)
                                        </label>
                                        <input
                                            id="ficha-peso"
                                            data-testid="ficha-peso"
                                            type="number" min="1" max="400" step="0.1"
                                            value={peso}
                                            onChange={(e) => setPeso(e.target.value)}
                                            className="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500/60"
                                            required
                                        />
                                    </div>
                                    <div className="flex-1">
                                        <label htmlFor="ficha-genero" className="block text-xs text-zinc-500 mb-1">
                                            Género
                                        </label>
                                        <select
                                            id="ficha-genero"
                                            data-testid="ficha-genero"
                                            value={genero}
                                            onChange={(e) => setGenero(e.target.value)}
                                            className="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500/60"
                                            required
                                        >
                                            <option value="">Seleccionar</option>
                                            <option value="M">Masculino (M)</option>
                                            <option value="F">Femenino (F)</option>
                                        </select>
                                    </div>
                                    <button
                                        type="submit"
                                        data-testid="ficha-guardar-perfil"
                                        disabled={perfilMut.isPending}
                                        className="px-3 py-1.5 bg-orange-600 text-white rounded-md text-sm font-semibold hover:bg-orange-500 disabled:opacity-50"
                                    >
                                        {perfilMut.isPending ? 'Guardando…' : 'Guardar'}
                                    </button>
                                </form>
                                {avisoPerfil && (
                                    <p className="mt-2 text-xs text-zinc-300" data-testid="ficha-perfil-aviso">
                                        {avisoPerfil}
                                    </p>
                                )}
                            </div>
                        </>
                    )}

                    {/* ── RMs del alumno ──────────────────────────────────────────────
                        Mismo endpoint coach-scoped que alimenta el panel del tab Alumnos
                        (`GET /historial-rm/alumnos/{id}/rms`), por eso se pinta SIN soltar
                        la ficha: es el dato de fuerza que el coach usa para programar. El
                        valor sale de `formatResultadoRM` (fuente única H-03) y no de
                        `peso_kg`: en cardio/máquinas ese campo es un dummy. */}
                    <div className="bg-zinc-800/60 rounded-lg p-4" data-testid="ficha-rms">
                        <div className="flex items-center justify-between mb-2">
                            <p className="text-xs text-zinc-500">RMs · mejor marca por movimiento</p>
                            {rms.length > 0 && (
                                <span className="text-xs text-zinc-500" data-testid="ficha-rms-total">{rms.length}</span>
                            )}
                        </div>

                        {cargandoRms ? (
                            <div className="flex justify-center py-6">
                                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-orange-500"></div>
                            </div>
                        ) : errorRms ? (
                            <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300">
                                <p className="font-medium" data-testid="ficha-rms-error">⚠️ {errorRms}</p>
                                <button onClick={() => rmsQ.refetch()} className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">
                                    Reintentar
                                </button>
                            </div>
                        ) : rms.length > 0 ? (
                            <ul className="space-y-2" data-testid="ficha-lista-rms">
                                {rms.map((rm) => (
                                    <li
                                        key={rm.movimiento_id}
                                        data-testid="ficha-rm"
                                        className="flex items-center justify-between gap-3 border-b border-zinc-800 last:border-0 pb-2 last:pb-0"
                                    >
                                        <div className="min-w-0">
                                            <p className="text-zinc-100 text-sm font-medium truncate">
                                                {rm.movimiento_nombre}
                                            </p>
                                            <p className="text-xs text-zinc-500">
                                                {CATEGORIA_RM[inferirCategoriaRM(rm)] || 'RM'}
                                                {rm.fecha ? ` · ${fmtFechaCortaChile(rm.fecha)}` : ''}
                                            </p>
                                            {rm.notas && (
                                                <p className="text-xs text-zinc-500 italic truncate">{rm.notas}</p>
                                            )}
                                        </div>
                                        <p className="text-orange-400 font-bold whitespace-nowrap">
                                            {formatResultadoRM(rm)}
                                        </p>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <div className="text-center py-4" data-testid="ficha-sin-rms">
                                <p className="text-2xl mb-1">🏋️</p>
                                <p className="text-zinc-400 text-sm">Sin RMs registrados</p>
                                <p className="text-xs text-zinc-500 mt-0.5">Este alumno no ha registrado marcas personales</p>
                            </div>
                        )}
                    </div>
                </div>

                <div className="p-5 border-t border-zinc-800 flex justify-end">
                    <button onClick={onClose} className="px-4 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700">
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    );
};

export default AlumnoFichaCoach;

