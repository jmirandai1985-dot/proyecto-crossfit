import React, { useState } from 'react';

/**
 * Fila de UNA clase puntual del dia para el panel de Supervision (admin, dark).
 * Muestra la hora, la asistencia sobre el cupo actual y el control
 * "Ampliar cupo (admin)" (hasta +10 sobre el cupo_original de esa clase).
 * El estado del control es local y no persistido: se pierde al recargar.
 *
 * Props:
 *   clase        -> item de GET /api/v1/clases/ (cupo_maximo, cupo_original,
 *                   asistentes_confirmados, cancelada, coach_nombre...)
 *   onAmpliarCupo -> async (clase, extra) => { cupo_maximo, cupo_original, tope, extra_disponible }
 */
const cupoOriginal = (c) => (c.cupo_original ?? c.cupo_maximo);
const cupoTope = (c) => cupoOriginal(c) + 10;
const fmtHora = (h) => (h ? String(h).slice(0, 5) : '');

const SupervisionClaseRow = ({ clase, onAmpliarCupo }) => {
    const [abierto, setAbierto] = useState(false);
    const [extra, setExtra] = useState(2);
    const [enviando, setEnviando] = useState(false);
    const [cupos, setCupos] = useState({});
    const [msg, setMsg] = useState(null);

    const cupoActual = cupos[clase.id] ?? clase.cupo_maximo;
    const libre = cupoTope(clase) - cupoActual;
    const enTope = libre === 0;

    const abrir = () => {
        setMsg(null);
        setAbierto(!abierto);
        setExtra(Math.max(1, Math.min(2, libre)));
    };

    const confirmar = async () => {
        setEnviando(true);
        setMsg(null);
        try {
            const r = await onAmpliarCupo(clase, extra);
            setCupos((prev) => ({ ...prev, [clase.id]: r.cupo_maximo }));
            setMsg({ tipo: 'exito', texto: `Cupo ampliado a ${r.cupo_maximo} (quedan ${r.extra_disponible} extra)` });
            setAbierto(false);
        } catch (e) {
            const s = e.response?.status;
            setMsg({
                tipo: 'error',
                texto: s === 409 ? 'Tope alcanzado (+10 sobre el original)'
                    : s === 403 ? 'Sin permiso para ampliar el cupo de esta clase'
                        : s === 422 ? 'Cupos extra debe estar entre 1 y 10'
                            : (e.response?.data?.detail || 'No se pudo ampliar el cupo'),
            });
        }
        setEnviando(false);
    };

    return (
        <div className="px-3 py-2 mb-2 rounded border border-zinc-800 bg-zinc-900/60">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-bold text-zinc-200">
                    {fmtHora(clase.hora_inicio)}-{fmtHora(clase.hora_fin)}
                </span>
                <span className="text-xs text-zinc-400">
                    {clase.asistentes_confirmados || 0}/{cupoActual} confirmados
                </span>
                {clase.cancelada && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-300">Cancelada</span>
                )}
                <span className="text-xs text-zinc-500">
                    {clase.coach_nombre ? clase.coach_nombre : 'Sin coach'}
                </span>
                <button
                    onClick={abrir}
                    disabled={enTope}
                    title={enTope
                        ? `En el tope: +10 sobre el original (${cupoTope(clase)})`
                        : `Quedan ${libre} cupos extra (original ${cupoOriginal(clase)})`}
                    className={`ml-auto px-2.5 py-1 rounded text-xs font-medium transition-colors ${enTope
                        ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                        : 'bg-blue-900 text-blue-100 hover:bg-blue-800'}`}
                >
                    Ampliar cupo (admin)
                </button>
            </div>

            {abierto && (
                <div className="mt-2 p-2 rounded border border-zinc-700 bg-zinc-800/60 flex flex-wrap items-center gap-2">
                    <span className="text-xs text-zinc-300">
                        Original {cupoOriginal(clase)} / tope +10 = {cupoTope(clase)} / quedan <b>{libre}</b>
                    </span>
                    {[1, 2, 3].map((n) => (
                        <button
                            key={n}
                            onClick={() => setExtra(n)}
                            disabled={libre < n}
                            className={`px-2 py-0.5 rounded text-xs font-bold ${extra === n ? 'bg-orange-500 text-white' : 'bg-zinc-700 text-zinc-200'} ${libre < n ? 'opacity-40 cursor-not-allowed' : ''}`}
                        >
                            +{n}
                        </button>
                    ))}
                    <input
                        type="number"
                        min="1"
                        max={Math.min(10, libre)}
                        value={extra}
                        onChange={(e) => setExtra(Math.max(1, Math.min(Math.min(10, libre), parseInt(e.target.value || '1', 10))))}
                        className="w-14 px-2 py-0.5 rounded text-xs border bg-zinc-900 border-zinc-700 text-zinc-100"
                    />
                    <button
                        onClick={confirmar}
                        disabled={enviando || extra < 1 || extra > libre}
                        className="px-2.5 py-1 bg-orange-500 text-white rounded text-xs font-bold hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {enviando ? 'Guardando...' : 'Confirmar'}
                    </button>
                    <button
                        onClick={() => { setAbierto(false); setMsg(null); }}
                        className="px-2.5 py-1 rounded text-xs font-medium text-zinc-300 hover:bg-zinc-700"
                    >
                        Cancelar
                    </button>
                </div>
            )}

            {msg && (
                <div className={`mt-2 px-2.5 py-1.5 rounded text-xs border-l-4 ${msg.tipo === 'exito'
                    ? 'bg-green-500/10 border-green-500 text-green-300'
                    : 'bg-red-500/10 border-red-500 text-red-300'}`}>
                    {msg.texto}
                </div>
            )}
        </div>
    );
};

export default SupervisionClaseRow;

