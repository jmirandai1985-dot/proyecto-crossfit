import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

/**
 * Flecha "Volver" del header de las pantallas del alumno en MÓVIL (<768px).
 *
 * - Se muestra SÓLO en móvil (`md:hidden`): en ≥768px no existe (regla de oro:
 *   el escritorio se ve EXACTAMENTE igual que hoy).
 * - Tamaño táctil ≥44px (min-h-11/min-w-11) y a la izquierda del título.
 * - Navega hacia atrás en el historial; si no hay historial (p. ej. se abrió la
 *   URL directo), cae al `fallback` (Inicio del alumno).
 *
 * Reutilizado por: Mis Reservas, Mi Historial, Bazar, Mis Pedidos, Performance
 * Hub, RMs, Evolución, Mi Progreso, Ajustes y Solicitar Plan. Inicio NO lo usa
 * (es la raíz).
 */
const BotonVolver = ({ fallback = '/alumno/dashboard', className = '' }) => {
    const navigate = useNavigate();

    const volver = () => {
        if (typeof window !== 'undefined' && window.history.length > 1) {
            navigate(-1);
        } else {
            navigate(fallback);
        }
    };

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
