import React from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Barra de pestañas sincronizada con el query param `?tab=`.
 * @param {{id:string,label:string}[]} tabs
 */
export const TabBar = ({ tabs }) => {
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = searchParams.get('tab') || tabs[0].id;

    return (
        <div className="flex border-b border-zinc-700 mb-6 gap-8">
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => setSearchParams({ tab: tab.id })}
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
