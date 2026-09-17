import React from 'react';

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
const AsistenciaGrupoDisciplina = ({ grupo, osc, abierta, onToggle, onAbrir, formatearHora }) => {
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
                                    👥 {clase.reservas_count || 0} reservas · 🎟️ {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || '—'} confirmados
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
