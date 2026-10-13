import React from 'react';
import { tipoDe } from '../utils/avisosMarketing';

// Los íconos de los tipos de aviso: los MISMOS dibujos del mockup
// (`mockup/carrusel-marketing.html`), inline para no depender de nada nuevo.
// Los comparten el botón del formulario del admin, la tabla del panel y la
// tarjeta del alumno: si el ícono de "Promoción" cambiara en un lado solo, el
// otro estaría mostrando otra cosa.
const DIBUJOS = {
    // Promoción: un disco.
    disco: (
        <>
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="3.2" />
        </>
    ),
    // Colaboración: mancuernas.
    mancuernas: (
        <>
            <path d="M4 7h4l2.5 7L8 19H4z" />
            <path d="M20 7h-4l-2.5 7L16 19h4z" />
            <path d="M10.5 14h3" />
        </>
    ),
    // Aviso del box: megáfono.
    megafono: (
        <>
            <path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z" />
            <path d="M15 9a3 3 0 0 1 0 6M18 6a7 7 0 0 1 0 12" />
        </>
    ),
    // Evento: barra olímpica.
    barra: (
        <>
            <circle cx="5" cy="7" r="2.3" />
            <circle cx="19" cy="7" r="2.3" />
            <path d="M7.3 7h9.4M3 14h18M7 14v6M17 14v6M10 20h4" />
        </>
    ),
    // Producto del Bazar: carrito.
    carrito: (
        <>
            <path d="M6 7h13l-1.5 8H8L6 4H3" />
            <circle cx="9" cy="19" r="1.3" />
            <circle cx="17" cy="19" r="1.3" />
        </>
    ),
};

const IconoTipoAviso = ({ tipo, className = 'w-3.5 h-3.5' }) => (
    <svg
        className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    >
        {DIBUJOS[tipoDe(tipo).icono] || DIBUJOS.disco}
    </svg>
);

export default IconoTipoAviso;
