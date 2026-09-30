import React from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Barra de pestañas sincronizada con el query param `?tab=`.
 *
 * Los demás params se CONSERVAN al cambiar de pestaña (no se reemplazan): el panel de
 * Fidelización vive de `?filtro=`/`?arquetipo=` (los pone el link de KPIs y las tarjetas de la
 * pantalla) y cambiar de pestaña no puede tirar los filtros que el usuario ya eligió.
 *
 * @param {{id:string,label:string}[]} tabs
 */
export const TabBar = ({ tabs }) => {
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = searchParams.get('tab') || tabs[0].id;

    const irA = (id) => {
        const next = new URLSearchParams(searchParams);
        next.set('tab', id);
        setSearchParams(next);
    };

    return (
        <div className="flex border-b border-zinc-700 mb-6 gap-8">
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => irA(tab.id)}
                    className={`pb-3 text-sm font-semibold uppercase tracking-wide transition ${
                        activeTab === tab.id
                            ? 'text-white border-b-2 border-orange-500'
                            : 'text-gray-400 hover:text-gray-200'
                    }`}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );
};

export default TabBar;
