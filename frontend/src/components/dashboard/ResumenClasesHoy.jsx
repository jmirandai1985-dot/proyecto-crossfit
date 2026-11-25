/**
 * Resumen COMPACTO de las clases de hoy para la tarjeta del Dashboard.
 *
 * Reemplaza al gráfico metido en una caja con scroll: muestra unas pocas filas
 * legibles (hora + reservas/cupo) y las clases SIN cupo como texto, sin barra.
 * El detalle completo (con todas las clases) se abre en el panel de la tarjeta.
 *
 * Datos: `GET /asistencia/clases-hoy` (`estado`, `hora_inicio`,
 * `reservas_count`, `cupo_maximo`, `disciplina_nombre`). No calcula nada que no
 * venga del backend: sólo ordena y dibuja.
 */
import React from 'react';

const ORDEN_ESTADO = { realizada: 0, en_curso: 1, proxima: 2, cancelada: 3 };

const hora = (clase) => String(clase?.hora_inicio || '').slice(0, 5);

const reservasDe = (clase) => {
    const n = Number(clase?.reservas_count);
    return Number.isFinite(n) && n > 0 ? n : 0;
};

const sinCupo = (clase) => {
    const cupo = clase?.cupo_maximo;
    if (cupo === null || cupo === undefined || cupo === '') return true;
    const n = Number(cupo);
    return !Number.isFinite(n) || n <= 0;
};

const colorBarra = (pct) => (
    pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
);

const colorEstado = (estado) => (
    estado === 'realizada' ? 'bg-emerald-400'
        : estado === 'en_curso' ? 'bg-sky-400'
            : estado === 'cancelada' ? 'bg-red-400' : 'bg-zinc-600'
);

export default function ResumenClasesHoy({ clases = [], max = 6 }) {
    const lista = [...(Array.isArray(clases) ? clases : [])].sort((a, b) => {
        const orden = (ORDEN_ESTADO[a?.estado] ?? 9) - (ORDEN_ESTADO[b?.estado] ?? 9);
        return orden !== 0 ? orden : hora(a).localeCompare(hora(b));
    });
    const visibles = lista.slice(0, max);
    const restantes = Math.max(0, lista.length - visibles.length);

    if (lista.length === 0) {
        return <p className="mt-2 text-xs text-zinc-500">No hay clases hoy.</p>;
    }

    return (
        <div className="mt-2 space-y-1" data-testid="resumen-clases-hoy">
            {visibles.map((clase) => {
                const libre = sinCupo(clase);
                const reservas = reservasDe(clase);
                const cupo = libre ? null : Number(clase.cupo_maximo);
                const pct = libre ? null : Math.round((reservas / cupo) * 100);
                const nombre = clase.disciplina_nombre || 'Clase';
                return (
                    <div key={clase.id} className="flex items-center gap-2"
                        aria-label={libre
                            ? `${hora(clase)} ${nombre}: ${reservas} reservas, sin cupo`
                            : `${hora(clase)} ${nombre}: ${reservas} de ${cupo} (${pct}%)`}>
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${colorEstado(clase.estado)}`}
                            title={clase.estado || ''} />
                        <span className="w-10 shrink-0 text-[11px] font-semibold tabular-nums text-zinc-400">
                            {hora(clase) || '--:--'}
                        </span>
                        {libre ? (
                            <span className="min-w-0 flex-1 truncate text-[11px] text-sky-300">
                                {nombre} · sin cupo · {reservas} reservas
                            </span>
                        ) : (
                            <>
                                <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-zinc-800"
                                    title={`${nombre} · ${pct}%`}>
                                    <i className={`block h-full rounded-full ${colorBarra(pct)}`}
                                        style={{ width: `${Math.min(pct, 100)}%` }} />
                                </span>
                                <span className="shrink-0 text-[11px] font-semibold tabular-nums text-zinc-300">
                                    {reservas}/{cupo}
                                </span>
                            </>
                        )}
                    </div>
                );
            })}
            {restantes > 0 && (
                <p className="text-[11px] text-zinc-500">
                    +{restantes} clases · clic para ver el detalle
                </p>
            )}
        </div>
    );
}
