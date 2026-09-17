import React, { useState } from 'react';

/**
 * Grupo de clases de una disciplina (Fase 2 de Asistencia).
 * Encabezado con acordeon + badge de estado, y filas compactas por clase.
 *
 * Regla del badge (acordada): SOLO las clases con reservas definen el estado.
 *   - sin clases con reservas -> "Sin reservas hoy"
 *   - ninguna pendiente       -> "Completo"
 *   - alguna pendiente        -> "Pendiente (N)"
 * Las clases sin reservas cuentan como "no aplica".
 *
 * Props: grupo {disciplina, clases[]}, osc, abierta, onToggle, onAbrir, formatearHora.
 */
const cupoOriginal = (c) => (c.cupo_original ?? c.cupo_maximo);
const cupoTope = (c) => cupoOriginal(c) + 10;

const AsistenciaGrupoDisciplina = ({ grupo, osc, abierta, onToggle, onAbrir, formatearHora, onAmpliarCupo }) => {
    const conReservas = grupo.clases.filter((c) => (c.reservas_count || 0) > 0);
    const pendientes = conReservas.filter((c) => !c.marcada).length;
    const tonoBadge = conReservas.length === 0
        ? (osc ? 'bg-zinc-800 text-zinc-400' : 'bg-gray-100 text-gray-600')
        : pendientes === 0
            ? (osc ? 'bg-green-500/20 text-green-400' : 'bg-green-100 text-green-700')
            : (osc ? 'bg-orange-500/20 text-orange-400' : 'bg-orange-100 text-orange-700');
    const textoBadge = conReservas.length === 0
        ? 'Sin reservas hoy'
        : pendientes === 0
            ? 'Completo'
            : `Pendiente (${pendientes})`;

    // Ampliar cupo de UNA clase puntual (max +10 sobre cupo_original). Estado local, no persistido.
    const [abierto, setAbierto] = useState(null);
    const [extra, setExtra] = useState(2);
    const [enviando, setEnviando] = useState(false);
    const [cupos, setCupos] = useState({});
    const [msg, setMsg] = useState(null);

    const abrirCupo = (clase, libre) => {
        setMsg(null);
        setAbierto(abierto === clase.id ? null : clase.id);
        setExtra(Math.max(1, Math.min(2, libre)));
    };

    const confirmarCupo = async (clase, libre) => {
        setEnviando(true);
        setMsg(null);
        try {
            const r = await onAmpliarCupo(clase, extra);
            setCupos((prev) => ({ ...prev, [clase.id]: r.cupo_maximo }));
            setMsg({ claseId: clase.id, tipo: 'exito', texto: `Cupo ampliado a ${r.cupo_maximo} (quedan ${r.extra_disponible} extra)` });
            setAbierto(null);
        } catch (e) {
            const s = e.response?.status;
            setMsg({
                claseId: clase.id,
                tipo: 'error',
                texto: s === 409 ? 'Tope alcanzado (+10 sobre el original)'
                    : s === 403 ? 'Solo podes ampliar el cupo de tus clases o disciplinas'
                        : s === 422 ? 'Cupos extra debe estar entre 1 y 10'
                            : (e.response?.data?.detail || 'No se pudo ampliar el cupo'),
            });
        }
        setEnviando(false);
    };

    return (
        <div className={`rounded-xl shadow-sm border overflow-hidden ${osc ? 'bg-zinc-900 border-zinc-800' : 'bg-white border-gray-100'}`}>
            <button
                onClick={onToggle}
                className={`w-full flex items-center justify-between gap-3 px-5 py-4 text-left transition-colors ${osc ? 'hover:bg-zinc-800/60' : 'hover:bg-gray-50'}`}
            >
                <span className="flex items-center gap-2 min-w-0">
                    <span className={`text-xs ${osc ? 'text-zinc-500' : 'text-gray-400'}`}>{abierta ? '[-]' : '[+]'}</span>
                    <span className={`font-semibold truncate ${osc ? 'text-zinc-100' : 'text-gray-900'}`}>{grupo.disciplina}</span>
                    <span className={`text-xs shrink-0 ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>
                        {grupo.clases.length} clase{grupo.clases.length === 1 ? '' : 's'}
                    </span>
                </span>
                <span className={`inline-flex items-center px-2 py-1 text-xs font-medium rounded-full shrink-0 ${tonoBadge}`}>
                    {textoBadge}
                </span>
            </button>

            {abierta && (
                <div className={`border-t divide-y ${osc ? 'border-zinc-800 divide-zinc-800' : 'border-gray-100 divide-gray-100'}`}>
                    {grupo.clases.map((clase) => (
                        <div key={clase.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                            <div className="min-w-0 flex-1">
                                <p className={`text-sm font-medium ${osc ? 'text-zinc-200' : 'text-gray-800'}`}>
                                    🕐 {formatearHora(clase.hora_inicio)} - {formatearHora(clase.hora_fin)}
                                </p>
                                <p className={`text-xs ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>
                                    👥 {clase.reservas_count || 0} reservas · 🎟️ {clase.asistentes_confirmados || 0}/{cupos[clase.id] ?? clase.cupo_maximo} confirmados
                                </p>
                            </div>
                            {(clase.reservas_count || 0) > 0 && (
                                <span
                                    className={`inline-flex items-center px-2 py-1 text-xs font-medium rounded-full shrink-0 ${
                                        clase.marcada
                                            ? (osc ? 'bg-green-500/20 text-green-400' : 'bg-green-100 text-green-700')
                                            : (osc ? 'bg-orange-500/20 text-orange-400' : 'bg-orange-100 text-orange-700')
                                    }`}
                                >
                                    {clase.marcada ? '✓ Completada' : 'Pendiente'}
                                </span>
                            )}
                                            <button
                                                onClick={() => abrirCupo(clase, cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo))}
                                                disabled={cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo) === 0}
                                                title={cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo) === 0
                                                    ? `En el tope: +10 sobre el original (${cupoTope(clase)})`
                                                    : `Quedan ${cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo)} cupos extra`}
                                                className={`px-3 py-2 rounded-lg text-xs font-medium shrink-0 transition-colors ${
                                                    cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo) === 0
                                                        ? (osc ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed' : 'bg-gray-100 text-gray-400 cursor-not-allowed')
                                                        : (osc ? 'bg-blue-900 text-blue-100 hover:bg-blue-800' : 'bg-blue-100 text-blue-800 hover:bg-blue-200')
                                                }`}
                                            >
                                                + cupo
                                            </button>

                                            {abierto === clase.id && (
                                                <div className={`w-full mt-2 p-3 rounded-lg border flex flex-wrap items-center gap-3 ${osc ? 'bg-zinc-800/60 border-zinc-700' : 'bg-gray-50 border-gray-200'}`}>
                                                    <span className={`text-xs ${osc ? 'text-zinc-300' : 'text-gray-600'}`}>
                                                        Original {cupoOriginal(clase)} / tope +10 = {cupoTope(clase)} / quedan <b>{cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo)}</b>
                                                    </span>
                                                    {[1, 2, 3].map((n) => (
                                                        <button
                                                            key={n}
                                                            onClick={() => setExtra(n)}
                                                            disabled={cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo) < n}
                                                            className={`px-2.5 py-1 rounded text-xs font-bold ${
                                                                extra === n ? 'bg-orange-500 text-white' : (osc ? 'bg-zinc-700 text-zinc-200' : 'bg-white text-gray-700 border border-gray-300')
                                                            }`}
                                                        >
                                                            +{n}
                                                        </button>
                                                    ))}
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max={Math.min(10, cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo))}
                                                        value={extra}
                                                        onChange={(e) => setExtra(Math.max(1, Math.min(Math.min(10, cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo)), parseInt(e.target.value || '1', 10))))}
                                                        className={`w-16 px-2 py-1 rounded text-xs border ${osc ? 'bg-zinc-900 border-zinc-700 text-zinc-100' : 'bg-white border-gray-300'}`}
                                                    />
                                                    <button
                                                        onClick={() => confirmarCupo(clase)}
                                                        disabled={enviando || extra < 1 || extra > (cupoTope(clase) - (cupos[clase.id] ?? clase.cupo_maximo))}
                                                        className="px-3 py-1.5 bg-orange-500 text-white rounded text-xs font-bold hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
                                                    >
                                                        {enviando ? 'Guardando...' : 'Confirmar'}
                                                    </button>
                                                    <button
                                                        onClick={() => { setAbierto(null); setMsg(null); }}
                                                        className={`px-3 py-1.5 rounded text-xs font-medium ${osc ? 'text-zinc-300 hover:bg-zinc-700' : 'text-gray-600 hover:bg-gray-200'}`}
                                                    >
                                                        Cancelar
                                                    </button>
                                                </div>
                                            )}

                                            {msg && msg.claseId === clase.id && (
                                                <div className={`w-full mt-2 px-3 py-2 rounded-lg text-xs border-l-4 ${msg.tipo === 'exito'
                                                    ? (osc ? 'bg-green-500/10 border-green-500 text-green-300' : 'bg-green-50 border-green-500 text-green-700')
                                                    : (osc ? 'bg-red-500/10 border-red-500 text-red-300' : 'bg-red-50 border-red-500 text-red-700')}`}>
                                                    {msg.texto}
                                                </div>
                                            )}
                            <button
                                onClick={() => onAbrir(clase)}
                                className="px-4 py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors shrink-0"
                            >
                                Marcar Asistencia
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default AsistenciaGrupoDisciplina;