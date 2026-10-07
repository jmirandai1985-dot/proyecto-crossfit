import React, { useEffect } from 'react';
import { X } from 'lucide-react';

/**
 * Un bloque de texto del detalle. Se dibuja SÓLO si hay contenido, así el mismo modal sirve para
 * un gráfico (que sólo trae `explicacion`) y para una tarjeta de KPI (que trae las 4 preguntas).
 */
const Bloque = ({ etiqueta, borde, color, children }) => {
    if (!children) return null;
    return (
        <div className={`rounded-lg border-l-4 ${borde} bg-zinc-800/40 p-4`}>
            <p className={`text-[10px] font-semibold uppercase tracking-wide ${color}`}>{etiqueta}</p>
            <div className="mt-1 text-sm leading-relaxed text-zinc-300">{children}</div>
        </div>
    );
};

/**
 * Modal de DETALLE AMPLIADO para gráficos y tablas del BI (KPIs) y de Reportes.
 *
 * Por qué: varios bloques (pronóstico, bloques horarios, cohortes, gráficos de
 * Reportes) tienen un gráfico chico en la página y su explicación como texto
 * menudo. Este modal los abre a mayor escala y junta la explicación en un bloque
 * legible.
 *
 * Reusa el PATRÓN de modales del proyecto (ver `RecomendacionModal`): backdrop
 * oscuro, click afuera cierra, card `zinc-900` con borde, ✕ arriba a la derecha,
 * botón "Cerrar" abajo y cierre con Esc. Se extrajo como componente propio porque
 * ahora lo usan DOS pantallas (KPIs y Reportes) con contenido distinto, en vez de
 * duplicar el marcado del overlay en cada una.
 *
 * Props:
 *   - titulo:      título del bloque (obligatorio).
 *   - subtitulo:   aclaración corta bajo el título (opcional).
 *   - explicacion: texto (string o JSX) de qué mide la métrica y cómo se calcula.
 *   - calculo:     CÓMO se calcula, aparte de `explicacion` (opcional). Lo usan las tarjetas de KPI
 *                  (`KpiDetalleModal`), que separan las 4 preguntas: qué mide · cómo se calcula ·
 *                  cómo se lee · qué hacer. Sin `calculo` el rótulo del primer bloque queda como
 *                  siempre ("Qué mide y cómo se calcula"), así los gráficos y tablas que ya lo usan
 *                  no cambian.
 *   - lectura:     cómo se lee el número (qué valor es bueno y cuál malo) — opcional.
 *   - accion:      qué hacer con el dato — opcional.
 *   - onCerrar:    callback de cierre (obligatorio).
 *   - children:    el gráfico/tabla/cifra ampliada. El tamaño lo define quien lo usa
 *                  (acá no se fuerza altura, así funciona igual con una tabla).
 */
export const DetalleModal = ({ titulo, subtitulo, explicacion, calculo, lectura, accion, onCerrar, children }) => {
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onCerrar(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onCerrar]);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
            onClick={onCerrar}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label={`Detalle: ${titulo}`}
                className="w-full max-w-5xl max-h-[90dvh] overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-start justify-between gap-4 border-b border-zinc-700 p-5">
                    <div>
                        <h2 className="text-xl font-bold text-zinc-100">{titulo}</h2>
                        {subtitulo && <p className="mt-1 text-xs text-zinc-500">{subtitulo}</p>}
                    </div>
                    <button
                        type="button"
                        onClick={onCerrar}
                        aria-label="Cerrar detalle"
                        className="shrink-0 rounded-lg p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Contenido + explicación: hasta 4 bloques (qué mide · cómo se calcula · cómo se
                    lee · qué hacer). Los que no vienen no se dibujan. */}
                <div className="space-y-4 p-5">
                    <div>{children}</div>
                    <Bloque
                        etiqueta={calculo ? 'Qué mide' : 'Qué mide y cómo se calcula'}
                        borde="border-sky-500"
                        color="text-sky-400"
                    >
                        {explicacion}
                    </Bloque>
                    <Bloque etiqueta="Cómo se calcula" borde="border-indigo-500" color="text-indigo-400">
                        {calculo}
                    </Bloque>
                    <Bloque
                        etiqueta="Cómo se lee (qué es bueno y qué es malo)"
                        borde="border-emerald-500"
                        color="text-emerald-400"
                    >
                        {lectura}
                    </Bloque>
                    <Bloque etiqueta="Qué hacer con este dato" borde="border-amber-500" color="text-amber-400">
                        {accion}
                    </Bloque>
                </div>

                {/* Footer */}
                <div className="flex justify-end border-t border-zinc-700 p-4">
                    <button
                        type="button"
                        onClick={onCerrar}
                        className="rounded-lg bg-zinc-700 px-4 py-2 text-sm font-bold text-zinc-200 hover:bg-zinc-600"
                    >
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    );
};

export default DetalleModal;
