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
 *
 * `variante="oscura"`: mismo aviso y mismo Reintentar con los colores del tema oscuro
 * (pantallas como la pestaña Mensual de KPIs); el default `clara` es el de siempre.
 */
const AvisoCarga = ({ secciones = [], onReintentar, testid = 'aviso-carga', variante = 'clara' }) => {
    if (!secciones || secciones.length === 0) return null;
    const oscura = variante === 'oscura';
    return (
        <div
            data-testid={testid}
            role="alert"
            className={`mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${
                oscura
                    ? 'border-red-700 bg-red-900/30 text-red-200'
                    : 'border-red-300 bg-red-50 text-red-800'
            }`}
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
