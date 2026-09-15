import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { RiskBadge } from './RiskBadge';
import { estiloReco } from './recoEstilo';

// Meses abreviados para la fecha exacta del último contacto (mismo formato que
// `fmtFechaCorta` de la tabla: "12 sep").
const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
    'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

// Etiquetas legibles del `tipo` del último correo automático (mismo mapa que
// usaba la tabla de KPIs: acá vive el único consumidor que queda, este modal).
const ETIQUETA_CONTACTO = {
    inactividad: 'Inactividad',
    renovacion_plan: 'Renovación de plan',
    vencimiento: 'Plan por vencer',
    vencimiento_inminente: 'Plan por vencer',
    ultimo_credito: 'Último crédito',
    sin_creditos: 'Sin créditos',
    reactivacion: 'Reactivación',
    cumplimiento: 'Cumplimiento',
    acompanamiento: 'Acompañamiento',
    bienvenida: 'Bienvenida',
    activacion: 'Activación',
    bienvenida_activacion: 'Bienvenida y activación',
    confirmacion_renovacion: 'Confirmación de renovación',
    confirmacion_plan: 'Confirmación de plan',
    confirmacion_pedido: 'Confirmación de pedido',
};

const etiquetaContacto = (tipo) => {
    const t = String(tipo || '');
    if (!t) return 'Contacto';
    if (ETIQUETA_CONTACTO[t]) return ETIQUETA_CONTACTO[t];
    if (t.startsWith('hito_racha')) return 'Hito de racha';
    return t.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
};

// "hoy" / "hace 1 día" / "hace 3 días"
const fmtHace = (dias) => {
    const n = Number(dias);
    if (!Number.isFinite(n) || n <= 0) return 'hoy';
    return `hace ${n} día${n === 1 ? '' : 's'}`;
};

/**
 * Modal con el detalle completo de la recomendación de un alumno (pestaña BI).
 *
 * Por qué propio y no uno existente: en `components/` los modales son de dominio
 * (`ModalProducto`, `ModalClase`, `AlumnoFichaModal` — este último se auto-carga
 * por API y no conoce motivo/recomendación). Acá sólo se muestran datos que la
 * fila de `predictions_churn` YA trae, así que es sincrónico y sin fetch.
 * Sigue el patrón de modales del proyecto: backdrop oscuro, click afuera cierra,
 * card zinc-900 y ✕ (más cierre con Esc).
 *
 * Props:
 *   - fila:           fila de GET /kpis/churn (incluye motivo y recomendación)
 *   - onClose:        callback al cerrar
 *   - contactoTxt:    texto ya formateado del último contacto automático. Si no
 *                     viene, se deriva de `fila.ultimo_contacto_automatico` (el
 *                     modal es autosuficiente: Fidelización lo usa sin props).
 *   - renovacionTxt:  fecha ya formateada de la próxima renovación. Si no
 *                     viene, se deriva de `fila.fecha_proxima_renovacion`.
 */
export const RecomendacionModal = ({ fila, onClose, contactoTxt, renovacionTxt }) => {
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    if (!fila) return null;

    const nombre = fila.alumno_nombre || `Alumno #${fila.usuario_id}`;
    const estilo = estiloReco(fila.recomendacion_codigo);

    // Días hasta la próxima renovación (negativo = ya venció). null si no hay plan.
    const diasParaVencer = (() => {
        const [y, m, d] = String(fila.fecha_proxima_renovacion || '')
            .slice(0, 10).split('-').map(Number);
        if (!y || !m || !d) return null;
        const hoy = new Date();
        const ref = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate());
        return Math.round((new Date(y, m - 1, d) - ref) / 86400000);
    })();

    // Fecha exacta del último contacto ("12 sep"), si el backend la mandó.
    const fechaContacto = (() => {
        const [y, m, d] = String(fila.ultimo_contacto_automatico?.fecha || '')
            .slice(0, 10).split('-');
        return (y && m && d) ? `${Number(d)} ${MESES_CORTOS[Number(m) - 1]}` : null;
    })();

    // Textos de contexto: si el padre NO los formateó, se derivan de la fila. Así
    // el modal es AUTOSUFICIENTE (Fidelización lo usa sin props) y muestra los
    // datos reales en vez de los fallbacks cuando la fila los trae.
    const fechaCorta = (iso) => {
        const [y, m, d] = String(iso || '').slice(0, 10).split('-');
        return (y && m && d) ? `${Number(d)} ${MESES_CORTOS[Number(m) - 1]}` : null;
    };
    const renovacion = renovacionTxt ?? fechaCorta(fila.fecha_proxima_renovacion);
    const contacto = contactoTxt ?? (fila.ultimo_contacto_automatico
        ? `${etiquetaContacto(fila.ultimo_contacto_automatico.tipo)} · `
          + `${fmtHace(fila.ultimo_contacto_automatico.hace_dias)}`
        : null);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
            onClick={onClose}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label={`Recomendación para ${nombre}`}
                className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header: alumno */}
                <div className="flex items-start justify-between gap-3 border-b border-zinc-700 p-4">
                    <div>
                        <h3 className="font-bold text-zinc-100">{nombre}</h3>
                        <p className="text-xs text-zinc-500">
                            #{fila.usuario_id}{fila.alumno_correo ? ` · ${fila.alumno_correo}` : ''}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Cerrar"
                        className="shrink-0 rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                <div className="space-y-4 p-4">
                    {/* Riesgo */}
                    <div className="flex flex-wrap items-center gap-3">
                        <RiskBadge nivel={fila.riesgo_nivel} />
                        <span className="text-xs text-zinc-400">
                            {Number(fila.probabilidad_churn || 0).toFixed(1)}% de probabilidad de abandono
                        </span>
                    </div>

                    {/* Motivo completo */}
                    <div>
                        <p className="text-xs font-bold uppercase tracking-wide text-zinc-400">
                            Motivo detectado
                        </p>
                        <p className="mt-1 text-sm text-zinc-200">{fila.motivo || '—'}</p>
                    </div>

                    {/* Recomendación completa */}
                    <div className={`rounded-lg border-l-4 bg-zinc-800/40 p-3 ${estilo.borde}`}>
                        <p className={`text-[10px] font-semibold uppercase tracking-wide ${estilo.texto}`}>
                            {estilo.etiqueta}
                        </p>
                        <p className="mt-1 text-sm leading-relaxed text-zinc-200">
                            {fila.recomendacion || 'Sin recomendación calculada.'}
                        </p>
                    </div>

                    {/* Contexto de la fila: estos 2 datos YA NO están en la tabla
                        principal (así entra sin scroll horizontal), por eso el modal los
                        muestra SIEMPRE, con fallback y con el detalle extra que antes no
                        se veía (días para vencer / fecha exacta del envío). */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                        <div>
                            <p className="text-xs text-zinc-500">Próxima renovación</p>
                            <p className="text-zinc-200">{renovacion || 'Sin plan vigente'}</p>
                            {diasParaVencer !== null && (
                                <p className={`text-xs ${diasParaVencer <= 7 ? 'font-semibold text-orange-300' : 'text-zinc-500'}`}>
                                    {diasParaVencer < 0
                                        ? `venció hace ${Math.abs(diasParaVencer)} día${Math.abs(diasParaVencer) === 1 ? '' : 's'}`
                                        : `vence en ${diasParaVencer} día${diasParaVencer === 1 ? '' : 's'}`}
                                </p>
                            )}
                        </div>
                        <div>
                            <p className="text-xs text-zinc-500">Último contacto automático</p>
                            <p className="text-zinc-200">{contacto || 'Sin contacto previo'}</p>
                            {fechaContacto && (
                                <p className="text-xs text-zinc-500">enviado el {fechaContacto}</p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="flex justify-end border-t border-zinc-700 p-4">
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-lg bg-zinc-700 px-4 py-2 text-sm font-bold text-zinc-200 hover:bg-zinc-600"
                    >
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    );
};

export default RecomendacionModal;
