/**
 * Ficha del alumno para el panel COACH (P2).
 *
 * Por qué no se reusa el AlumnoFichaModal de Admin: ese modal pega a
 * GET /usuarios/{id} y GET /suscripciones, que son admin-only (un coach
 * recibiría 403). Acá se usa un único endpoint coach-scoped que devuelve
 * EXACTAMENTE los 4 datos que el coach necesita: teléfono, antigüedad
 * (fecha de alta), plan actual y créditos/vencimiento reales.
 * Sin datos financieros.
 */
import React, { useEffect, useState } from 'react';
import api from '../services/api';
import { fmtFechaChile } from '../utils/fecha';

const fmtFecha = (f) => (f ? fmtFechaChile(f) : '—');

const AlumnoFichaCoach = ({ alumnoId, coachId, onClose }) => {
    const [ficha, setFicha] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const cargar = async () => {
        setLoading(true);
        setError('');
        try {
            const r = await api.get(`/api/v1/fidelizacion/coach/${coachId}/alumno/${alumnoId}/ficha`);
            setFicha(r.data);
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo cargar la ficha del alumno.');
            setFicha(null);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (alumnoId) cargar();
    }, [alumnoId, coachId]);

    if (!alumnoId) return null;

    const plan = ficha?.plan;
    const creditos = plan?.creditos_disponibles;

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" data-testid="ficha-coach-modal">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-lg">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div>
                        <h3 className="text-lg font-bold text-zinc-100">
                            {ficha?.nombre || 'Ficha del alumno'}
                        </h3>
                        <p className="text-sm text-zinc-400">{ficha?.correo || '—'}</p>
                    </div>
                    <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100 text-xl leading-none" aria-label="Cerrar">×</button>
                </div>

                <div className="p-5 space-y-4">
                    {loading && (
                        <div className="flex justify-center py-8">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                        </div>
                    )}

                    {!loading && error && (
                        <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300">
                            <p className="font-medium">⚠️ {error}</p>
                            <button onClick={cargar} className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">
                                Reintentar
                            </button>
                        </div>
                    )}

                    {!loading && !error && ficha && (
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
                        </>
                    )}
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

