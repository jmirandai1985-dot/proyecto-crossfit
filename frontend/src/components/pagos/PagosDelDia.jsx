import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
    ArrowRight, Banknote, Clock, CreditCard, Landmark, RefreshCw,
} from 'lucide-react';
import { usePagosDelDia } from '../../hooks/queries';
import AvisoCarga from '../AvisoCarga';
import { resumenPagosDelDia } from '../../utils/pagosDelDia';

/**
 * "Pagos del día": TODOS los cobros aprobados y pendientes del día (membresías y
 * Bazar), cada uno en su propia TARJETA clicable.
 *
 * Lo montan la tarjeta del Dashboard admin (`maxFilas` + `mostrarEnlace`) y la
 * pantalla `/admin/pagos-del-dia` (lista completa). El destino de la campana
 * `plan_pagado_online` es esa pantalla.
 *
 * Todo lo que se pinta viene calculado del backend (`services/pagos_del_dia.py`):
 * acá no se decide si un pago "está activo" ni se adivina el medio de pago; sólo se
 * colorea y se elige el ícono de la clave que manda el backend (`tipo_cobro_clave`).
 */

const clp = (v) => `$${Number(v || 0).toLocaleString('es-CL')}`;

// Estado del COBRO: aprobado / pendiente / cancelado (texto de color).
// Sale de `estado_pago` = el estado REAL del pago (`pagos.estado`, traducido de
// Mercado Pago). `estado` (sin sufijo) es el estado del NEGOCIO —si el plan ya activó—.
const ESTADOS_PAGO = {
    aprobado: { label: 'Aprobado', clase: 'text-emerald-400' },
    pendiente: { label: 'Pendiente', clase: 'text-amber-300' },
    en_proceso: { label: 'En proceso', clase: 'text-amber-300' },
    cancelado: { label: 'Cancelado', clase: 'text-red-400' },
    rechazado: { label: 'Rechazado', clase: 'text-red-400' },
    reembolsado: { label: 'Reembolsado', clase: 'text-zinc-400' },
    expirado: { label: 'Expirado', clase: 'text-zinc-400' },
};

// Origen del cobro: "Membresía" (color de ACENTO; incluye planes y matrícula) o
// "Bazar" (color de WARNING; pedidos). El borde izquierdo de la tarjeta usa el mismo.
const ORIGENES = {
    membresia: { label: 'Membresía', etiqueta: 'text-indigo-300', borde: 'border-l-indigo-500' },
    bazar: { label: 'Bazar', etiqueta: 'text-amber-300', borde: 'border-l-amber-500' },
};
const ORIGEN_DEFAULT = ORIGENES.membresia;

// Ícono del medio de pago según la CLAVE que manda el backend
// (`tipo_cobro_clave`). El diseño pedía Tabler (`ti-credit-card`, `ti-building-bank`,
// `ti-cash`); este proyecto no tiene Tabler instalado, así que se usan los
// equivalentes de lucide-react que ya usa la app (no se agregan dependencias).
const ICONOS_TIPO = {
    tarjeta_credito: CreditCard,
    tarjeta_debito: CreditCard,
    cuenta_mp: CreditCard,
    transferencia: Landmark,
    efectivo: Banknote,
    canal: CreditCard,
};

const IconoTipo = ({ clave }) => {
    const Icono = ICONOS_TIPO[clave] || CreditCard;
    return <Icono className="h-3.5 w-3.5" aria-hidden="true" />;
};


const PagosDelDia = ({ maxFilas = null, mostrarEnlace = false }) => {
    const navigate = useNavigate();
    const { data, isPending, isFetching, isError, refetch } = usePagosDelDia();
    // Encabezado: cantidad y total del DÍA (los manda el backend en `resumen`) y la
    // lista completa. La MISMA función alimenta la tarjeta "Ingresos de hoy", así
    // que ambas cifras no pueden discrepar (`utils/pagosDelDia`).
    const { pagos, cantidad, totalClp } = resumenPagosDelDia(data);
    const visibles = maxFilas === null ? pagos : pagos.slice(0, maxFilas);
    const ocultos = pagos.length - visibles.length;

    // Ficha/historial del alumno: se abre EN EL PADRÓN con deep-link. NO existe
    // `/admin/alumnos/:id`; `?alumno_id=` es lo que lee `Alumnos.jsx` para abrir
    // la ficha unificada (mismo patrón que PanelAlumnosPrueba y la campana).
    const irAFicha = (alumnoId) => {
        if (!alumnoId) return;
        navigate(`/admin/alumnos?alumno_id=${alumnoId}`);
    };

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
                    <p className="text-[11.5px] text-zinc-500" data-testid="pagos-del-dia-resumen">
                        {cantidad} {cantidad === 1 ? 'cobro' : 'cobros'} · total {clp(totalClp)}
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

            {/* La lista NO lleva cajas de resumen: la cantidad y el total viven en el
                encabezado ("N cobros · total $X") y en la tarjeta "Ingresos de hoy". */}

            {isPending && pagos.length === 0 ? (
                <div className="mt-4 space-y-2" aria-hidden="true">
                    {[0, 1, 2].map((i) => (
                        <div key={i} className="h-12 rounded-lg bg-zinc-800/60 animate-pulse" />
                    ))}
                </div>
            ) : pagos.length === 0 ? (
                <p className="mt-4 text-sm text-zinc-500" data-testid="pagos-del-dia-vacio">
                    Todavía no hay pagos hoy.
                </p>
            ) : (
                <div className="mt-4 space-y-4" data-testid="pagos-del-dia-lista">
                    {visibles.map((p) => {
                        const estado = ESTADOS_PAGO[p.estado_pago] || {
                            label: p.estado_pago || '—',
                            clase: 'text-zinc-400',
                        };
                        const origen = ORIGENES[p.origen] || ORIGEN_DEFAULT;
                        const producto = p.producto || p.origen_detalle || p.plan || 'Sin detalle';
                        // Sin `alumno_id` no hay ficha a la que ir: la tarjeta NO es clicable.
                        const clicable = Boolean(p.alumno_id);
                        const abrirFicha = () => irAFicha(p.alumno_id);
                        return (
                            <div
                                key={p.pago_id}
                                data-testid={`pago-del-dia-${p.pago_id}`}
                                {...(clicable ? {
                                    role: 'button',
                                    tabIndex: 0,
                                    onClick: abrirFicha,
                                    onKeyDown: (e) => {
                                        if (e.key === 'Enter' || e.key === ' ') {
                                            e.preventDefault();
                                            abrirFicha();
                                        }
                                    },
                                    'aria-label': `Abrir la ficha de ${p.nombre}`,
                                    title: `Abrir la ficha de ${p.nombre}`,
                                } : {})}
                                className={`rounded-xl border-y-[0.5px] border-r-[0.5px] border-l-[3px] border-zinc-700 ${origen.borde} bg-zinc-900 px-[22px] py-[20px]${clicable
                                    ? ' cursor-pointer transition hover:border-zinc-500 hover:bg-zinc-800/60 focus:outline-none focus:ring-2 focus:ring-sky-500'
                                    : ''}`}
                            >
                                <p className={`text-[10.5px] font-bold uppercase tracking-wide ${origen.etiqueta}`}>
                                    {origen.label}
                                </p>
                                <p className="mt-1 text-sm font-bold text-zinc-100">
                                    {producto}
                                </p>
                                <p className="mt-0.5 text-xs text-zinc-400">
                                    {p.nombre}
                                </p>
                                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                                    <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-300">
                                        <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                                        {p.hora || '—'}
                                    </span>
                                    <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-300">
                                        <IconoTipo clave={p.tipo_cobro_clave} />
                                        {p.tipo_cobro || '—'}
                                    </span>
                                </div>
                                <div className="mt-3 flex items-center justify-between border-t border-zinc-800 pt-2.5">
                                    <span className={`text-[11.5px] font-semibold ${estado.clase}`}>
                                        {estado.label}
                                    </span>
                                    <span className="text-sm font-bold text-zinc-100">
                                        {clp(p.monto_clp)}
                                    </span>
                                </div>
                            </div>
                        );
                    })}
                </div>
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
