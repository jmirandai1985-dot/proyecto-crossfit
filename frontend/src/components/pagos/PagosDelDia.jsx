import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, RefreshCw } from 'lucide-react';
import { usePagosDelDia } from '../../hooks/queries';
import { iniciales } from '../../utils/iniciales';
import AvisoCarga from '../AvisoCarga';

/**
 * "Pagos del día": los cobros de PLANES de hoy del box, con la plata y si el
 * plan ya activó.
 *
 * Lo montan la tarjeta del Dashboard admin (`maxFilas` + `mostrarEnlace`) y la
 * pantalla `/admin/pagos-del-dia` (lista completa). El destino de la campana
 * `plan_pagado_online` es esa pantalla: antes ese aviso abría la pestaña de
 * solicitudes con voucher, donde un cobro de Mercado Pago no tiene nada que
 * revisar.
 *
 * Todo lo que se pinta viene calculado del backend (`services/pagos_del_dia.py`):
 * acá no se decide si un pago "está activo", sólo se colorea.
 */

const clp = (v) => `$${Number(v || 0).toLocaleString('es-CL')}`;

// Estado del NEGOCIO de cada fila (lo manda el backend).
const ESTADOS = {
    activo: { label: 'Activo', clase: 'bg-emerald-500/20 text-emerald-300' },
    pendiente: { label: 'Pendiente de activar', clase: 'bg-amber-500/20 text-amber-200' },
};

// `2026-11-21` -> `21-11-2026`. NO se usa `new Date(iso)`: un `YYYY-MM-DD` se
// parsea como medianoche UTC y en Chile cae el día anterior.
const fechaLegible = (iso) => {
    const partes = String(iso || '').split('-');
    return partes.length === 3 ? `${partes[2]}-${partes[1]}-${partes[0]}` : '';
};

const PagosDelDia = ({ maxFilas = null, mostrarEnlace = false }) => {
    const navigate = useNavigate();
    const { data, isPending, isFetching, isError, refetch } = usePagosDelDia();
    const pagos = Array.isArray(data?.pagos) ? data.pagos : [];
    const resumen = data?.resumen || {};
    const visibles = maxFilas === null ? pagos : pagos.slice(0, maxFilas);
    const ocultos = pagos.length - visibles.length;
    const fecha = fechaLegible(data?.fecha);

    return (
        <div
            className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-orange-600"
            data-testid="pagos-del-dia"
        >
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">
                        Pagos del día
                    </p>
                    <p className="text-[11.5px] text-zinc-500">
                        {fecha ? `Cobros de planes del ${fecha}` : 'Cobros de planes de hoy'}
                        {' · '}se actualiza solo
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => refetch()}
                    disabled={isFetching}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-3 py-1.5 text-[12px] font-semibold text-zinc-300 transition hover:border-orange-500 hover:text-orange-400 disabled:opacity-50"
                >
                    <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`}
                        aria-hidden="true" />
                    Actualizar
                </button>
            </div>

            <AvisoCarga
                secciones={isError ? ['los pagos del día'] : []}
                variante="oscura"
                testid="aviso-pagos-del-dia"
                onReintentar={() => refetch()}
            />

            <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div className="bg-zinc-800/60 border border-zinc-700 rounded-lg p-3">
                    <p className="text-[11px] text-zinc-500 uppercase tracking-wide">Pagos</p>
                    <p className="text-2xl font-bold text-white" data-testid="pagos-del-dia-cantidad">
                        {isPending ? '…' : (resumen.cantidad ?? 0)}
                    </p>
                </div>
                <div className="bg-zinc-800/60 border border-zinc-700 rounded-lg p-3">
                    <p className="text-[11px] text-zinc-500 uppercase tracking-wide">Total cobrado</p>
                    <p className="text-2xl font-bold text-orange-400" data-testid="pagos-del-dia-total">
                        {isPending ? '…' : clp(resumen.total_clp)}
                    </p>
                </div>
                {!isPending && resumen.pendientes_activar > 0 && (
                    <div className="bg-amber-500/10 border border-amber-500/40 rounded-lg p-3">
                        <p className="text-[11px] text-amber-300 uppercase tracking-wide">
                            Por activar
                        </p>
                        <p className="text-2xl font-bold text-amber-200"
                            data-testid="pagos-del-dia-pendientes">
                            {resumen.pendientes_activar}
                        </p>
                    </div>
                )}
            </div>

            {isPending && pagos.length === 0 ? (
                <div className="mt-4 space-y-2" aria-hidden="true">
                    {[0, 1, 2].map((i) => (
                        <div key={i} className="h-12 rounded-lg bg-zinc-800/60 animate-pulse" />
                    ))}
                </div>
            ) : pagos.length === 0 ? (
                <p className="mt-4 text-sm text-zinc-500" data-testid="pagos-del-dia-vacio">
                    Todavía no hay pagos de planes hoy.
                </p>
            ) : (
                <ul className="mt-4 divide-y divide-zinc-800">
                    {visibles.map((p) => {
                        const estado = ESTADOS[p.estado] || ESTADOS.pendiente;
                        return (
                            <li
                                key={p.pago_id}
                                data-testid={`pago-del-dia-${p.pago_id}`}
                                className="flex items-center gap-3 py-2.5"
                            >
                                <span
                                    aria-hidden="true"
                                    className="shrink-0 h-9 w-9 rounded-full bg-orange-500/20 text-orange-300 text-xs font-bold flex items-center justify-center"
                                >
                                    {iniciales(p.nombre)}
                                </span>
                                <div className="min-w-0 flex-1">
                                    <p className="text-sm font-semibold text-zinc-100 truncate">
                                        {p.nombre}
                                    </p>
                                    <p className="text-[11.5px] text-zinc-500 truncate">
                                        {p.plan}{p.hora ? ` · ${p.hora}` : ''}
                                    </p>
                                </div>
                                <div className="shrink-0 text-right">
                                    <p className="text-sm font-bold text-zinc-100">
                                        {clp(p.monto_clp)}
                                    </p>
                                    <span className={`inline-block mt-0.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold ${estado.clase}`}>
                                        {estado.label}
                                    </span>
                                </div>
                            </li>
                        );
                    })}
                </ul>
            )}

            {mostrarEnlace && pagos.length > 0 && (
                <button
                    type="button"
                    onClick={() => navigate('/admin/pagos-del-dia')}
                    className="mt-3 inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-orange-400 transition hover:text-orange-300"
                    data-testid="pagos-del-dia-ver-todos"
                >
                    {ocultos > 0
                        ? `Ver los ${pagos.length} pagos del día`
                        : 'Ver pantalla completa'}
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
            )}
        </div>
    );
};

export default PagosDelDia;
