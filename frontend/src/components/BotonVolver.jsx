import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { destinoVolver } from '../utils/navegacion';

/**
 * Flecha "Volver" del header de las pantallas que NO son la raíz de su panel: las del alumno
 * (Mi Reservas, Mi Historial, Bazar, Mis Pedidos…), el Historial de un alumno del panel del
 * admin y las del coach —Gestión de Clases y Entregar pedido—.
 *
 * - Se muestra en TODOS los anchos: el rediseño móvil la estrenó con `md:hidden` y en
 *   escritorio no quedaba ninguna forma de volver con un clic (había que usar el menú o el
 *   botón del navegador). Ahora la misma flecha acompaña al título también en ≥768px.
 * - Tamaño táctil ≥44px (min-h-11/min-w-11) y a la izquierda del título.
 * - Vuelve ATRÁS en el historial (`history.back()`), que es lo que espera quien
 *   llegó desde otra pantalla de la app (p. ej. la ficha del Inicio móvil). Si
 *   esta pantalla es la PRIMERA de la aplicación —se abrió el enlace directo,
 *   se recargó la página o se pegó la URL— volver atrás sacaría al usuario de
 *   la app, así que se cae al `fallback` que pase la pantalla.
 *
 * La decisión vive en `utils/navegacion.js` (`destinoVolver`), probada sin
 * navegador en `scripts/test-boton-volver.mjs`.
 *
 * Reutilizado por: Mis Reservas, Mi Historial, Bazar, Mis Pedidos, Performance
 * Hub, RMs, Evolución, Mi Progreso, Ajustes y Solicitar Plan (alumno), el
 * Historial del alumno (admin, `fallback="/admin/dashboard"`) y las pantallas
 * del coach que no son su Inicio —Gestión de Clases y Entregar pedido— con
 * `fallback="/coach/dashboard"`. (La Pizarra de WOD y Generar Clases también
 * la llevaban hasta el Bloque 5; hoy no están ruteadas, así que no se navegan.)
 * NO lo usan las raíces de cada panel (el Inicio del alumno y el del admin): ahí no
 * hay "atrás" que dar y la flecha no iría a ningún lado.
 *
 * EXCEPCIÓN (Bloque 6, decisión del usuario 2026-10-15): el Dashboard del COACH sí la
 * monta, con `fallback="/coach/dashboard"`. Su escritorio se había quedado sin ninguna
 * forma de volver con un clic y el coach entra ahí desde el cajón lateral; con el
 * respaldo en su PROPIA ruta, el peor caso es quedarse donde ya está (sin historial
 * dentro de la app la flecha no lo saca de la app).
 */
const BotonVolver = ({ fallback = '/alumno/dashboard', className = '' }) => {
    const navigate = useNavigate();
    const { key } = useLocation();

    // `-1` = un paso atrás; cualquier otro valor es la ruta de respaldo.
    const volver = () => navigate(destinoVolver(key, fallback));

    return (
        <button
            type="button"
            onClick={volver}
            aria-label="Volver"
            data-testid="btn-volver"
            className={`inline-flex items-center justify-center min-h-11 min-w-11 shrink-0 -ml-1 rounded-lg text-zinc-300 hover:bg-zinc-800 transition-colors ${className}`}
        >
            <ArrowLeft size={24} />
        </button>
    );
};

export default BotonVolver;
