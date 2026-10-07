import React from 'react';
// Estilos del "Inicio" móvil (mockup urban-box-inicio-pulido-1), acotados a
// `.ub-inicio`. Se construye por bloques; este archivo crece bloque a bloque.
import './inicioMobile.css';

// "miércoles 7 de octubre" en el calendario de CHILE (no el del navegador).
// Mismo criterio que utils/fecha.js (TZ America/Santiago). El mockup no lleva
// coma tras el día de la semana, así que la quitamos.
const fechaLargaChile = () =>
    new Intl.DateTimeFormat('es-CL', {
        timeZone: 'America/Santiago',
        weekday: 'long',
        day: 'numeric',
        month: 'long',
    }).format(new Date()).replace(/,/g, '');

const capitalizar = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');

/**
 * Inicio del alumno para <768px. Recibe los datos ya consultados por el
 * Dashboard (nada de fetches duplicados) y pinta el diseño del mockup.
 *
 * Bloque 1: identidad (avatar + saludo + fecha + chips de plan/nivel).
 */
const InicioMobile = ({ usuario, membresia, nivelFuerza }) => {
    const nombre = (usuario || 'Atleta').trim();
    const primerNombre = nombre.split(/\s+/)[0] || 'Atleta';
    const inicial = (primerNombre[0] || 'A').toUpperCase();

    // Plan contratado (el mockup lo muestra SOLO aquí, en la identidad).
    const plan = membresia?.activa && membresia?.plan_nombre ? membresia.plan_nombre : null;

    // Nivel de fuerza ("Fuerza Elite"). Se omite si no hay datos.
    const nivel = nivelFuerza?.nivel && nivelFuerza.nivel.toLowerCase() !== 'sin datos'
        ? `Fuerza ${nivelFuerza.nivel}`
        : null;

    return (
        <div className="ub-inicio" data-checked="0">
            <div className="ub-col">
                {/* ── Identidad: plan y nivel (el plan solo se muestra aquí) ── */}
                <section className="who">
                    <div className="avatar" aria-hidden="true">{inicial}</div>
                    <div>
                        <h1>Hola, {capitalizar(primerNombre)}</h1>
                        <p>{fechaLargaChile()}</p>
                        {(plan || nivel) && (
                            <div className="chips">
                                {plan && <span className="pill plan">{plan}</span>}
                                {nivel && <span className="pill lvl">{nivel}</span>}
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
};

export default InicioMobile;
