import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import api from '../../services/api';

const API_BASE = '/api/v1';

// Límites del cupo por disciplina: los mismos que valida el backend (Query ge=1, le=200).
const CUPO_MIN = 1;
const CUPO_MAX = 200;

/**
 * Gestión de Cupos (admin) — antigua "Supervisión de Clases".
 * Único contenido: el cupo máximo por disciplina que aplica a las clases que se
 * generen de ahora en adelante (`PATCH /supervision/cupo-disciplina`, sin cambios).
 */
const SupervisionClases = () => {
    const [cuposData, setCuposData] = useState([]);
    const [cuposLoading, setCuposLoading] = useState(false);
    const [cuposMsg, setCuposMsg] = useState(null); // { tipo, texto }
    const [errorCupos, setErrorCupos] = useState('');

    const fetchCupos = useCallback(async () => {
        setCuposLoading(true);
        setErrorCupos('');
        try {
            const r = await api.get(`${API_BASE}/supervision/cupos-disciplinas`);
            setCuposData(r.data || []);
        } catch (e) {
            console.error('Error cupos', e);
            setErrorCupos(e.response?.data?.detail || 'No se pudieron cargar los cupos.');
        }
        setCuposLoading(false);
    }, []);

    useEffect(() => { fetchCupos(); }, [fetchCupos]);

    const cupoBloqueado = (d) => !d.activo || (d.horarios_count ?? 0) === 0;

    const ajustarCupo = async (d, delta) => {
        const nuevo = Math.min(CUPO_MAX, Math.max(CUPO_MIN, d.cupo_actual + delta));
        if (nuevo === d.cupo_actual) return;
        setCuposMsg(null);
        try {
            const r = await api.patch(`${API_BASE}/supervision/cupo-disciplina`, null,
                { params: { disciplina_id: d.id, cupo_maximo: nuevo } });
            if (r.data?.ok && (r.data?.horarios_actualizados ?? 0) > 0) {
                setCuposData((prev) => prev.map((x) => (x.id === d.id ? { ...x, cupo_actual: nuevo } : x)));
                setCuposMsg({ tipo: 'exito', texto: `Cupo de ${d.nombre}: ${nuevo}. Aplica a las próximas clases generadas.` });
            } else {
                setCuposMsg({ tipo: 'error', texto: 'Esta disciplina no tiene horarios configurados: el cambio no se guardó.' });
            }
        } catch (e) {
            console.error('Error actualizando cupo', e);
            setCuposMsg({ tipo: 'error', texto: e.response?.data?.detail || 'No se pudo actualizar el cupo. Reintenta.' });
        }
    };

    return (
        <Layout>
            <div className="space-y-4">
                <div>
                    <h1 className="text-3xl font-bold text-zinc-100">Gestión de Cupos</h1>
                    <p className="text-zinc-400 mt-1">
                        Cupo máximo por disciplina: aplica a las clases que se generen de ahora en adelante.
                    </p>
                </div>

                <div className="bg-zinc-900 rounded-xl border border-zinc-800 p-4">
                    <h3 className="font-bold text-lg text-zinc-100 mb-1">Cupo máximo por disciplina</h3>
                    <p className="text-xs text-zinc-400 mb-3">
                        Cambia el cupo de los horarios de la disciplina: aplica a las clases que se generen de ahora en adelante.
                    </p>
                    {cuposMsg && (
                        <div className={`mb-3 px-3 py-2 rounded text-xs border-l-4 ${cuposMsg.tipo === 'error'
                            ? 'bg-red-500/10 border-red-500 text-red-300'
                            : 'bg-emerald-500/10 border-emerald-500 text-emerald-300'}`}>
                            {cuposMsg.texto}
                        </div>
                    )}
                    {errorCupos && (
                        <div className="border-l-4 rounded-lg p-3 mb-3 text-xs bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-3">
                            <span>{errorCupos}</span>
                            <button onClick={fetchCupos} className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                        </div>
                    )}
                    {cuposLoading ? (
                        <div className="text-zinc-500 text-center py-8">Cargando cupos…</div>
                    ) : cuposData.length === 0 ? (
                        <div className="text-zinc-500 text-center py-8">Sin datos de cupos</div>
                    ) : (
                        <div className="divide-y divide-zinc-800">
                            {cuposData.map((d) => (
                                <div key={d.id} className="flex items-center justify-between py-3">
                                    <div className="flex items-center gap-2">
                                        <span className="font-medium text-zinc-100">{d.nombre}</span>
                                        {!d.activo && <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400">Inactiva</span>}
                                        {cupoBloqueado(d) && (
                                            <span className="text-xs text-amber-400">
                                                {!d.activo ? '· sin cambios posibles' : '· sin horarios configurados'}
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-2">
                                        {d.sin_tope || d.cupo_actual === null ? (
                                            <span className="text-xs px-2 py-1 rounded bg-sky-500/15 text-sky-300 font-semibold">
                                                Acceso libre · sin cupo
                                            </span>
                                        ) : (
                                            <>
                                                <button
                                                    onClick={() => ajustarCupo(d, -1)}
                                                    disabled={d.cupo_actual <= CUPO_MIN || cupoBloqueado(d)}
                                                    title={cupoBloqueado(d) ? (!d.activo ? 'Disciplina inactiva' : 'Sin horarios configurados') : 'Bajar el cupo máximo'}
                                                    aria-label={`Bajar el cupo de ${d.nombre}`}
                                                    className={`w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold ${(d.cupo_actual <= CUPO_MIN || cupoBloqueado(d))
                                                        ? 'bg-zinc-800 text-zinc-600 cursor-not-allowed'
                                                        : 'bg-red-500/20 text-red-300 hover:bg-red-500/30'}`}
                                                >
                                                    −
                                                </button>
                                                <span className="w-12 text-center text-xl font-bold text-zinc-100">{d.cupo_actual}</span>
                                                <button
                                                    onClick={() => ajustarCupo(d, 1)}
                                                    disabled={d.cupo_actual >= CUPO_MAX || cupoBloqueado(d)}
                                                    title={cupoBloqueado(d) ? (!d.activo ? 'Disciplina inactiva' : 'Sin horarios configurados') : 'Subir el cupo máximo'}
                                                    aria-label={`Subir el cupo de ${d.nombre}`}
                                                    className={`w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold ${(d.cupo_actual >= CUPO_MAX || cupoBloqueado(d))
                                                        ? 'bg-zinc-800 text-zinc-600 cursor-not-allowed'
                                                        : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'}`}
                                                >
                                                    +
                                                </button>
                                            </>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </Layout>
    );
};

export default SupervisionClases;