import React, { useState } from 'react';
import { ChevronRight, Eye, Gift, Mail, UserRound } from 'lucide-react';
import { RiskBadge } from '../../components/kpis/RiskBadge';
import { ArquetipoBadge } from '../../components/kpis/ArquetipoBadge';
import {
    alternarTarjeta, estaAbierta, resumenCerrado, detalleAbierto,
} from '../../utils/fidelizacionMovil';

/**
 * Lista de alumnos de Fidelización como TARJETAS COMPACTAS con acordeón (móvil <768px).
 *
 * POR QUÉ EXISTE: la tabla de 7 columnas no entra en un teléfono (scroll horizontal) y
 * cada alumno ocupaba media pantalla; con cientos de alumnos en riesgo, el admin no
 * llegaba a ver a quién tenía que contactar. Acá la fila cerrada muestra sólo lo que
 * decide: nombre, riesgo (color + %) y una línea del motivo. Al tocar la fila se abre EN
 * EL LUGAR (sin navegar) el arquetipo, el motivo completo, la recomendación y los dos
 * botones de siempre.
 *
 * Sólo UNA tarjeta abierta a la vez: el id vive acá (no en cada tarjeta), así que abrir
 * otra cierra la anterior por construcción (`utils/fidelizacionMovil.alternarTarjeta`).
 *
 * Los modales NO se montan acá: se avisa por callback y los sigue abriendo
 * `pages/admin/Fidelizacion.jsx`, que es donde ya viven y donde está el único manejador
 * de cada acción (enviar correo, dar beneficio, ver recomendación, ver ficha). Así el
 * rediseño móvil no agrega una segunda copia de ninguna llamada al backend.
 *
 * La pantalla de ESCRITORIO (>=768px) no monta este componente: sigue con su tabla.
 */
const FidelizacionMovil = ({
    alumnos, sugerencias, onVerFicha, onVerRecomendacion, onEnviarCorreo, onDarBeneficio,
}) => {
    const [abierta, setAbierta] = useState(null);

    if (!alumnos?.length) {
        return (
            <p className="px-4 py-8 text-center text-sm text-zinc-500"
                data-testid="fidelizacion-movil-vacia">
                No hay alumnos que cumplan este filtro.
            </p>
        );
    }

    return (
        <ul className="divide-y divide-zinc-800" data-testid="lista-fidelizacion-movil">
            {alumnos.map((p) => {
                const cerrado = resumenCerrado(p);
                const abierto = estaAbierta(abierta, p.usuario_id);
                const detalle = detalleAbierto(p, sugerencias?.[String(p.usuario_id)]);
                return (
                    <li key={p.usuario_id} className="fila-alumno bg-zinc-900"
                        data-testid={`fila-alumno-${p.usuario_id}`}>
                        {/* Fila CERRADA. Es un <button> (no un div con onClick) para que
                            el teclado y los lectores de pantalla vean el acordeón: el
                            panel de abajo queda FUERA del botón (no se anidan botones). */}
                        <button
                            type="button"
                            onClick={() => setAbierta((prev) => alternarTarjeta(prev, p.usuario_id))}
                            aria-expanded={abierto}
                            aria-controls={`ficha-movil-${p.usuario_id}`}
                            data-testid={`tarjeta-movil-${p.usuario_id}`}
                            className="flex w-full items-center gap-3 px-4 py-3 text-left"
                        >
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                    <span className="truncate text-sm font-bold text-zinc-100">
                                        {cerrado.nombre}
                                    </span>
                                    <RiskBadge nivel={cerrado.riesgo_nivel} />
                                    <span className="shrink-0 text-xs font-semibold text-zinc-400">
                                        {cerrado.probabilidad}
                                    </span>
                                </div>
                                <p className="mt-1 truncate text-xs text-zinc-400"
                                    data-testid={`motivo-cerrado-${p.usuario_id}`}>
                                    {cerrado.motivoCorto}
                                </p>
                            </div>
                            <ChevronRight
                                className={`h-4 w-4 shrink-0 text-zinc-500 transition-transform ${abierto ? 'rotate-90' : ''}`}
                            />
                        </button>
                        {/* PANEL (abierto). Va FUERA del <button>: adentro no se
                            pueden anidar los botones de acción. */}
                        {abierto && (
                            <div
                                id={`ficha-movil-${p.usuario_id}`}
                                data-testid={`detalle-movil-${p.usuario_id}`}
                                className="space-y-3 border-t border-zinc-800 bg-zinc-800/40 px-4 py-3"
                            >
                                <div className="flex flex-wrap items-center gap-2">
                                    <ArquetipoBadge arquetipo={detalle.arquetipo} />
                                    <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-300">
                                        {detalle.gestion}
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() => onVerFicha(p.usuario_id)}
                                        data-testid={`ver-ficha-movil-${p.usuario_id}`}
                                        className="inline-flex items-center gap-1 text-[11px] text-zinc-300 underline decoration-dotted hover:text-orange-300"
                                    >
                                        <UserRound className="h-3 w-3" /> Ver ficha
                                    </button>
                                </div>
                                <div>
                                    <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Motivo</p>
                                    <p className="text-xs leading-snug text-zinc-300"
                                        data-testid={`motivo-abierto-${p.usuario_id}`}>
                                        {detalle.motivo}
                                    </p>
                                </div>
                                <div className="border-l-2 border-orange-500 pl-2">
                                    <div className="flex items-start justify-between gap-2">
                                        <span className="text-[10px] font-semibold uppercase tracking-wide text-orange-300">
                                            {detalle.recomendacion.encabezado}
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => onVerRecomendacion(p)}
                                            aria-label={`Ver el detalle para ${cerrado.nombre}`}
                                            data-testid={`ver-recomendacion-movil-${p.usuario_id}`}
                                            className="shrink-0 rounded p-0.5 text-zinc-400 hover:bg-zinc-700/60 hover:text-orange-400"
                                        >
                                            <Eye className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                    <p className="text-xs leading-snug text-zinc-300"
                                        data-testid={`recomendacion-movil-${p.usuario_id}`}>
                                        {detalle.recomendacion.principal}
                                    </p>
                                    {detalle.recomendacion.motivo && (
                                        <p className="text-[11px] leading-snug text-zinc-500">
                                            {detalle.recomendacion.motivo}
                                        </p>
                                    )}
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    <button
                                        type="button"
                                        onClick={() => onEnviarCorreo(p)}
                                        title="Elegir plantilla y ver el correo exacto antes de mandarlo"
                                        data-testid={`enviar-correo-movil-${p.usuario_id}`}
                                        className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-blue-700"
                                    >
                                        <Mail className="h-3.5 w-3.5" /> Enviar correo
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => onDarBeneficio(p)}
                                        title="Regalar clases o un descuento (y avisarle por correo si quieres)"
                                        data-testid={`dar-beneficio-movil-${p.usuario_id}`}
                                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-emerald-700"
                                    >
                                        <Gift className="h-3.5 w-3.5" /> Dar beneficio
                                    </button>
                                </div>
                            </div>
                        )}
                    </li>
                );
            })}
        </ul>
    );
};

export default FidelizacionMovil;
