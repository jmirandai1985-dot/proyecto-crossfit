import React from 'react';
import { DetalleModal } from './DetalleModal';
import { detalleKpi } from './detallesKpi';

/** El valor como se muestra: "1.250", "3,6 %" o "—" cuando no hay dato (mismo criterio que la
 *  tarjeta: un null NO es un 0). */
const fmtValor = (valor) => (valor === null || valor === undefined || Number.isNaN(Number(valor))
    ? '—'
    : Number(valor).toLocaleString('es-CL'));

/**
 * Detalle de UNA tarjeta de KPI: el número que se está viendo + las cuatro preguntas.
 *
 * Cuál es el texto no se decide acá: sale del catálogo `detallesKpi` por `id`
 * (`<pestaña>:<dato>`). Si el id no está en el catálogo no se dibuja nada: un dato sin explicación
 * no tiene que abrir un modal vacío.
 *
 * Props:
 *   - id:      clave del catálogo (ej. "diario:alumnos_activos").
 *   - valor:   el número que muestra la tarjeta (se repite acá para no perder el contexto).
 *   - unidad:  sufijo del valor ("CLP", "%", "meses", …).
 *   - nota:    aclaración del período que se está mirando (ej. "Mes cerrado", "Día 12 sep").
 *   - onCerrar: callback de cierre.
 */
export const KpiDetalleModal = ({ id, valor, unidad = '', nota, onCerrar }) => {
    const detalle = detalleKpi(id);
    if (!detalle) return null;

    return (
        <DetalleModal
            titulo={detalle.label}
            subtitulo={nota}
            explicacion={detalle.que}
            calculo={detalle.calculo}
            lectura={detalle.lectura}
            accion={detalle.accion}
            onCerrar={onCerrar}
        >
            <div className="rounded-lg border border-zinc-700 bg-zinc-800/40 p-4">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                    {detalle.valorTitulo}
                </p>
                <p className="mt-1 text-3xl font-bold text-zinc-100">
                    {fmtValor(valor)}
                    {unidad && <span className="ml-2 text-lg text-zinc-400">{unidad}</span>}
                </p>
            </div>
        </DetalleModal>
    );
};

export default KpiDetalleModal;
