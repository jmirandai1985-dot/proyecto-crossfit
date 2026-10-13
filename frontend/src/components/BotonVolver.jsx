import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { destinoVolver } from '../utils/navegacion';

/**
 * Flecha "Volver" del header de las pantallas móviles (<768px): las del alumno
 * (Mi Reservas, Mi Historial, Bazar, Mis Pedidos…) y el Historial de un alumno
 * del panel del admin.
 *
 * - Se muestra SÓLO en móvil (`md:hidden`): en ≥768px no existe (regla de oro:
 *   el escritorio se ve EXACTAMENTE igual que hoy).
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
 * del coach que no son su Inicio —Pizarra de WOD, Generar Clases, Gestión de
 * Clases y Entregar pedido— con `fallback="/coach/dashboard"`.
 * NO lo usan las raíces de cada panel (el Inicio del alumno, el del admin y el
 * Dashboard del coach): ahí no hay "atrás" y la flecha no iría a ningún lado.
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
            className={`md:hidden inline-flex items-center justify-center min-h-11 min-w-11 shrink-0 -ml-1 rounded-lg text-zinc-300 hover:bg-zinc-800 transition-colors ${className}`}
        >
            <ArrowLeft size={24} />
        </button>
    );
};

export default BotonVolver;
