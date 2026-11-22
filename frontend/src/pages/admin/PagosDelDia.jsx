import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Layout from '../../components/Layout';
import PagosDelDia from '../../components/pagos/PagosDelDia';

/**
 * Pantalla `/admin/pagos-del-dia`: la lista COMPLETA de los cobros de planes de
 * hoy (la tarjeta del Dashboard muestra sólo los primeros).
 *
 * Es el destino de la campana `plan_pagado_online` y del enlace "Ver todos" de
 * la tarjeta: el aviso tiene que abrir la pantalla donde el cobro se mira (antes
 * ese aviso abría la pestaña de solicitudes con voucher, que para un pago online
 * está vacía).
 */
const AdminPagosDelDia = () => {
    const navigate = useNavigate();

    return (
        <Layout>
            <div className="p-6 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h1 className="text-2xl font-bold text-zinc-100">Pagos del día</h1>
                        <p className="text-sm text-zinc-400">
                            Cobros de planes de hoy por Mercado Pago: alumno, plan, monto y
                            si el plan ya está activo.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => navigate('/admin/dashboard')}
                        data-testid="pagos-del-dia-volver"
                        className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-4 py-2 text-sm font-semibold text-zinc-300 transition hover:border-orange-500 hover:text-orange-400"
                    >
                        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                        Volver al dashboard
                    </button>
                </div>

                <PagosDelDia />
            </div>
        </Layout>
    );
};

export default AdminPagosDelDia;
