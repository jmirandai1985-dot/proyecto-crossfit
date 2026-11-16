import React from 'react';
import { etiquetaTipoFormulario } from '../../utils/formulariosWod';

/**
 * Disciplinas como TARJETAS apilables (móvil <768px).
 *
 * La tabla de escritorio tiene 5 columnas y no entra en un teléfono. Esta
 * vista muestra la MISMA información (nombre, familia de formulario, coach /
 * open-box, activo/inactivo y acciones) sin scroll horizontal.
 *
 * No tiene estado ni llamadas propias: recibe los mismos datos y callbacks que
 * la tabla de `Disciplinas.jsx`, así editar/eliminar sigue usando el mismo
 * modal y la misma mutación.
 */
const DisciplinasMobile = ({ items, onEditar, onEliminar }) => {
    if (!items?.length) {
        return (
            <p className="px-4 py-8 text-center text-sm text-zinc-400"
                data-testid="disciplinas-movil-vacio">
                No hay disciplinas
            </p>
        );
    }

    return (
        <ul className="space-y-3 p-4" data-testid="lista-disciplinas-movil">
            {items.map((disciplina) => (
                <li key={disciplina.id}
                    className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-4"
                    data-testid={`disciplina-movil-${disciplina.id}`}>
                    <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                            <p className="truncate font-bold text-zinc-100">
                                {disciplina.nombre}
                            </p>
                            <p className="mt-0.5 text-xs text-zinc-400">
                                {etiquetaTipoFormulario(disciplina.tipo_formulario)}
                            </p>
                        </div>
                        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${disciplina.activo
                            ? 'bg-emerald-500/15 text-emerald-300'
                            : 'bg-red-500/15 text-red-300'}`}>
                            {disciplina.activo ? 'Activo' : 'Inactivo'}
                        </span>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-1.5">
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${disciplina.requiere_coach
                            ? 'bg-blue-500/15 text-blue-300'
                            : 'bg-zinc-800 text-zinc-400'}`}>
                            {disciplina.requiere_coach ? 'Requiere coach' : 'Acceso libre'}
                        </span>
                        {disciplina.es_open_box && (
                            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-300">
                                Open box
                            </span>
                        )}
                    </div>

                    <div className="mt-3 flex gap-2">
                        <button type="button" onClick={() => onEditar(disciplina)}
                            aria-label={`Editar ${disciplina.nombre}`}
                            data-testid={`editar-disciplina-movil-${disciplina.id}`}
                            className="rounded-lg bg-zinc-800 px-3 py-2 text-xs font-semibold text-zinc-200 hover:bg-zinc-700">
                            Editar
                        </button>
                        <button type="button" onClick={() => onEliminar(disciplina.id)}
                            aria-label={`Eliminar ${disciplina.nombre}`}
                            data-testid={`eliminar-disciplina-movil-${disciplina.id}`}
                            className="rounded-lg bg-red-500/15 px-3 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/25">
                            Eliminar
                        </button>
                    </div>
                </li>
            ))}
        </ul>
    );
};

export default DisciplinasMobile;
