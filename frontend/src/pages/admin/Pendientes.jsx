import React, { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import Layout from '../../components/Layout';
import { useResumenPendientes } from '../../hooks/queries';
import {
    TABS_PENDIENTES, normalizarResumen, resolverTab, textoBadge,
} from '../../utils/pendientes';
import PanelSolicitudes from '../../components/pendientes/PanelSolicitudes';
import PanelPedidos from '../../components/pendientes/PanelPedidos';
import PanelRegistros from '../../components/pendientes/PanelRegistros';
import PanelPremios from '../../components/pendientes/PanelPremios';

/**
 * Pantalla unificada "Pendientes" del admin (Tanda 4).
 *
 * Antes el trabajo diario del box estaba repartido en tres pantallas:
 *   · `/admin/alumnos-pendientes` → registros + solicitudes de plan
 *   · `/admin/pedidos`            → pedidos del Bazar sin validar
 *   · Configuración → Referidos   → premios por umbral de referidos
 * El admin tenía que acordarse de mirar las tres, y los badges de cada pantalla
 * contaban cosas distintas. Acá hay UNA pantalla con cuatro pestañas y UN endpoint
 * de contadores (`GET /admin/pendientes/resumen`).
 *
 * Decisiones que importan:
 *   · Cada pestaña monta SÓLO su panel y ese panel pide SÓLO su endpoint: entrar a
 *     "Pedidos" no descarga los registros de alumnos, y el `?tab=` es deep-linkable.
 *   · La pestaña vive en la URL (`?tab=pedidos`), no en estado local: la campana, el
 *     menú y el Dashboard pueden linkear a una pestaña concreta y el botón atrás
 *     funciona. `resolverTab` cae en la primera pestaña CON pendientes cuando la URL
 *     no trae tab (o trae una vieja), y `replace: true` no llena el historial.
 *   · Los badges salen del MISMO resumen que el menú lateral y la campana, así los
 *     números coinciden en toda la app.
 */
const Pendientes = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const qc = useQueryClient();
    const resumenQ = useResumenPendientes();

    // La URL manda: si trae un tab válido se respeta aunque tenga 0 pendientes (el
    // admin puede querer ver la lista vacía de una pestaña concreta).
    const tabActivo = resolverTab(searchParams.get('tab'), resumenQ.data);
    // Contadores del resumen (0 mientras carga): los usan los badges de las pestañas.
    const contadores = normalizarResumen(resumenQ.data);
    const tabInfo = TABS_PENDIENTES.find((t) => t.key === tabActivo) || TABS_PENDIENTES[0];

    const cambiarTab = useCallback((key) => {
        // `replace` para que "atrás" vuelva a la pantalla anterior y no recorra las
        // cuatro pestañas que el admin tocó.
        setSearchParams({ tab: key }, { replace: true });
    }, [setSearchParams]);

    // Refrescar = invalidar la familia de cada cola + volver a pedir el resumen. Se
    // invalida por PREFIJO porque cada panel tiene su propia queryKey (solicitudes,
    // pedidos, registros, referidos) y así se refresca también la que NO está montada:
    // al cambiar de pestaña se pinta al instante con datos frescos.
    const refrescar = () => {
        qc.invalidateQueries({ queryKey: ['solicitudes'] });
        qc.invalidateQueries({ queryKey: ['pedidos'] });
        qc.invalidateQueries({ queryKey: ['alumnos', 'pendientes-activacion'] });
        qc.invalidateQueries({ queryKey: ['referidos'] });
        qc.invalidateQueries({ queryKey: ['admin', 'pendientes'] });
    };


    return (
        <Layout>
            <div className="p-6">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
                    <div>
                        <h1 className="text-2xl font-bold text-white">Pendientes</h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            Todo lo que espera tu revisión, en un solo lugar
                        </p>
                    </div>
                    <button
                        onClick={refrescar}
                        disabled={resumenQ.isFetching}
                        className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 text-zinc-300 text-sm transition-colors"
                    >
                        {resumenQ.isFetching ? 'Actualizando…' : '⟳ Refrescar'}
                    </button>
                </div>

                {resumenQ.error && (
                    <div className="mb-4 bg-amber-500/15 border border-amber-500/40 text-amber-200 px-4 py-3 rounded-lg text-sm">
                        ⚠️ No se pudieron cargar los contadores. Las listas de cada pestaña
                        siguen funcionando; pulsa Refrescar para reintentar.
                    </div>
                )}

                {/* PESTAÑAS: badge con el contador de cada cola. El contador sale del
                    resumen (no de la lista montada), así los cuatro están al día aunque
                    sólo una lista esté visible. */}
                <div className="flex flex-wrap gap-2 mb-4 border-b border-zinc-800 pb-1" role="tablist">
                    {TABS_PENDIENTES.map((tab) => {
                        const activo = tab.key === tabActivo;
                        const cantidad = contadores[tab.cola] || 0;
                        const badge = textoBadge(cantidad);
                        return (
                            <button
                                key={tab.key}
                                role="tab"
                                aria-selected={activo}
                                title={tab.descripcion}
                                onClick={() => cambiarTab(tab.key)}
                                className={`flex items-center gap-2 px-4 py-2 rounded-t-lg text-sm font-semibold transition-colors border-b-2 ${
                                    activo
                                        ? 'border-orange-500 text-white bg-zinc-900'
                                        : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/60'
                                }`}
                            >
                                <span aria-hidden="true">{tab.icono}</span>
                                <span>{tab.label}</span>
                                {badge && (
                                    <span
                                        aria-label={`${cantidad} pendientes`}
                                        className={`min-w-[1.25rem] text-center rounded-full px-1.5 py-0.5 text-[11px] font-bold ${
                                            activo
                                                ? 'bg-orange-500 text-white'
                                                : cantidad > 0
                                                    ? 'bg-zinc-700 text-zinc-200'
                                                    : 'bg-zinc-800 text-zinc-500'
                                        }`}
                                    >
                                        {badge}
                                    </span>
                                )}
                            </button>
                        );
                    })}
                </div>

                <p className="text-zinc-500 text-xs mb-4">{tabInfo.descripcion}</p>


                {/* Se monta SÓLO el panel de la pestaña activa: cada uno pide su endpoint
                    y se desmonta al cambiar (así se apaga el auto-refresh de 30 s de las
                    solicitudes mientras el admin mira otra cosa). */}
                <div role="tabpanel">
                    {tabActivo === 'solicitudes' && <PanelSolicitudes />}
                    {tabActivo === 'pedidos' && <PanelPedidos />}
                    {tabActivo === 'registros' && <PanelRegistros />}
                    {tabActivo === 'premios' && <PanelPremios />}
                </div>
            </div>
        </Layout>
    );
};

export default Pendientes;
