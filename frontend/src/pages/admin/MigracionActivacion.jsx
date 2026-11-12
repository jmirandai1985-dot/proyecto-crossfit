import React from 'react';
import Layout from '../../components/Layout';

/**
 * Panel de ACTIVACIÓN de la migración BoxMagic — PLACEHOLDER (Fase 3).
 *
 * ⚠️ TEMPORAL: el contenido real se construye en la Fase 4 sobre el endpoint que ya
 * existe (`GET /api/v1/migracion-boxmagic/activacion`). Cuando termine la migración
 * de los ~712 alumnos desde BoxMagic se borran, de una sola vez, la sección del
 * menú (`config/menu.js`), las rutas de `App.jsx` y este archivo.
 *
 * No tiene lógica ni fetch a propósito: deja lista la navegación y el layout
 * (header + container, el mismo de las otras pantallas del panel admin).
 */
const MigracionActivacion = () => {
    return (
        <Layout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                <div className="mb-6">
                    <h1 className="text-2xl font-extrabold text-zinc-100">
                        Panel de Activación — Migración BoxMagic
                    </h1>
                    <p className="text-zinc-400 text-sm mt-1">
                        En qué etapa del alta quedó cada alumno que viene de BoxMagic.
                    </p>
                </div>

                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-10 text-center">
                    <p className="text-3xl mb-3">🚧</p>
                    <p className="text-zinc-200 font-bold">En construcción (Fase 4)</p>
                    <p className="text-zinc-500 text-sm mt-2">
                        Todavía no hay datos ni acciones en esta pantalla.
                    </p>
                </div>
            </div>
        </Layout>
    );
};

export default MigracionActivacion;
