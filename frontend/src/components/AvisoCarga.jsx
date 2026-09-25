import React from 'react';

/**
 * Aviso de carga fallida para las pantallas del alumno.
 *
 * POR QUÉ EXISTE: varias pantallas (Bazar, Mis Pedidos, Evolución, Performance Hub,
 * Mi Progreso…) usaban `api.get(...).catch(console.error)` y dejaban la lista vacía:
 * si la API fallaba (backend caído, CORS, red), el usuario veía "no hay nada" en vez
 * de un error. Este banner hace VISIBLE el fallo y ofrece Reintentar.
 *
 * Uso: <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />
 * (secciones = [] => no renderiza nada)
 */
const AvisoCarga = ({ secciones = [], onReintentar, testid = 'aviso-carga' }) => {
    if (!secciones || secciones.length === 0) return null;
    return (
        <div
            data-testid={testid}
            role="alert"
            className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
            <span>
                ⚠️ No se pudieron cargar: <strong>{secciones.join(', ')}</strong>. Lo que ves puede estar incompleto.
            </span>
            {onReintentar && (
                <button
                    type="button"
                    data-testid={`${testid}-reintentar`}
                    onClick={onReintentar}
                    className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 transition-colors"
                >
                    Reintentar
                </button>
            )}
        </div>
    );
};

export default AvisoCarga;
