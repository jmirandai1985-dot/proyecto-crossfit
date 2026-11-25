import React from 'react';

/**
 * Gráfico de barras HORIZONTALES de las clases del día: una fila por clase.
 *
 * QUÉ MUESTRA (y de dónde sale cada número):
 *   · la HORA de inicio (`hora_inicio`, `HH:MM`);
 *   · la BARRA con el % que ocupa la clase;
 *   · a la derecha `reservas / cupo`.
 *
 * REGLAS (no se inventan valores):
 *   · El cupo es el de CADA clase (`cupo_maximo`, migración 066): nunca un tope fijo.
 *   · `cupo_maximo` NULL (Musculación / Open Box) ⇒ SIN barra y SIN porcentaje, sólo el
 *     número de reservas ("acceso libre").
 *   · El numerador es `reservas_count` de `/asistencia/clases-hoy` = reservas VIGENTES
 *     (las canceladas no entran). Hoy no existe un estado de "lista de espera" en
 *     `reservas.estado`, así que la espera no puede sumar acá.
 *
 * El contenedor tiene alto máximo y scroll: con 27 clases el gráfico se desplaza en vez
 * de empujar el resto del dashboard. Mismo componente en el Inicio móvil y en el
 * Dashboard de escritorio (misma lectura en las dos vistas).
 */
const hora = (clase) => String(clase?.hora_inicio || '').slice(0, 5);

const reservasDe = (clase) => {
    const n = Number(clase?.reservas_count);
    return Number.isFinite(n) && n > 0 ? n : 0;
};

/** `cupo_maximo` vacío / NULL / 0 = sin tope: no hay denominador. */
const sinCupo = (clase) => {
    const cupo = clase?.cupo_maximo;
    if (cupo === null || cupo === undefined || cupo === '') return true;
    const n = Number(cupo);
    return !Number.isFinite(n) || n <= 0;
};

const colorBarra = (pct) => (
    pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
);

const GraficoClasesHoy = ({
    clases = [], alto = '12rem', testid = 'grafico-clases-hoy',
}) => {
    // Por hora de inicio, sin mutar el arreglo que llega de la caché.
    const lista = [...(Array.isArray(clases) ? clases : [])].sort(
        (a, b) => hora(a).localeCompare(hora(b)),
    );

    if (lista.length === 0) {
        return (
            <p className="text-xs text-zinc-500" data-testid={`${testid}-vacio`}>
                No hay clases hoy.
            </p>
        );
    }

    return (
        <div
            className="min-h-0 overflow-y-auto pr-1"
            style={{ maxHeight: alto }}
            data-testid={testid}
        >
            <ul className="space-y-1.5">
                {lista.map((c) => {
                    const reservas = reservasDe(c);
                    const libre = sinCupo(c);
                    const cupo = libre ? null : Number(c.cupo_maximo);
                    const pct = libre ? null : Math.round((reservas / cupo) * 100);
                    const nombre = c.disciplina_nombre || 'Clase';
                    const etiqueta = libre
                        ? `${hora(c)} ${nombre}: ${reservas} reservas (sin cupo)`
                        : `${hora(c)} ${nombre}: ${reservas} reservas confirmadas de ${cupo} (${pct}%)`;
                    return (
                        <li key={c.id} aria-label={etiqueta} className="flex items-center gap-2">
                            <span className="w-11 shrink-0 text-[11px] font-semibold tabular-nums text-zinc-400">
                                {hora(c) || '--:--'}
                            </span>
                            {libre ? (
                                <span className="min-w-0 flex-1 truncate text-[11px] text-zinc-500">
                                    sin cupo · {nombre}
                                </span>
                            ) : (
                                <span
                                    className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-zinc-800"
                                    title={`${nombre} · ${pct}%`}
                                >
                                    <i
                                        className={`block h-full rounded-full ${colorBarra(pct)}`}
                                        style={{ width: `${Math.min(pct, 100)}%` }}
                                    />
                                </span>
                            )}
                            <span className="shrink-0 text-right text-[11px] font-semibold tabular-nums text-zinc-300">
                                {reservas}{libre ? '' : `/${cupo}`}
                            </span>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
};

export default GraficoClasesHoy;
