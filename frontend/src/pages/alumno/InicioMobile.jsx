import React from 'react';
import { useNavigate } from 'react-router-dom';
// TZ Chile: "hoy" en el calendario chileno (no el del navegador), misma fuente
// que el Dashboard (utils/fecha.js): así la reserva de hoy coincide con las clases.
import { hoyChileStr } from '../../utils/fecha';
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

// Hora "HH:MM" desde el valor del backend ("HH:MM:SS" o "HH:MM").
const horaCorta = (h) => {
    if (!h) return '';
    const partes = String(h).split(':');
    return partes.length >= 2 ? `${partes[0]}:${partes[1]}` : String(h);
};

// Íconos del mockup (trazo, 24px). Se definen aquí y crecen bloque a bloque.
const ICONOS = {
    scan: <path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16" />,
    check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
};

const Icono = ({ nombre }) => (
    <svg className="i" viewBox="0 0 24 24" aria-hidden="true">{ICONOS[nombre]}</svg>
);

/**
 * Inicio del alumno para <768px. Recibe los datos ya consultados por el
 * Dashboard (nada de fetches duplicados) y pinta el diseño del mockup.
 *
 * Bloque 1: identidad (avatar + saludo + fecha + chips de plan/nivel).
 */
const InicioMobile = ({ usuario, membresia, nivelFuerza, reservas = [] }) => {
    const navigate = useNavigate();

    // "Hoy" en el calendario CHILENO (misma fuente que el Dashboard).
    const hoy = hoyChileStr();

    const nombre = (usuario || 'Atleta').trim();
    const primerNombre = nombre.split(/\s+/)[0] || 'Atleta';
    const inicial = (primerNombre[0] || 'A').toUpperCase();

    // Plan contratado (el mockup lo muestra SOLO aquí, en la identidad).
    const plan = membresia?.activa && membresia?.plan_nombre ? membresia.plan_nombre : null;

    // Nivel de fuerza ("Fuerza Elite"). Se omite si no hay datos.
    const nivel = nivelFuerza?.nivel && nivelFuerza.nivel.toLowerCase() !== 'sin datos'
        ? `Fuerza ${nivelFuerza.nivel}`
        : null;

    // Reserva de HOY: la primera del día por horario (el mockup muestra una sola).
    const reservaHoy = (Array.isArray(reservas) ? reservas : [])
        .filter((r) => (r.clase_fecha || r.fecha) === hoy)
        .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''))[0] || null;

    // Asistió: un único estado global para la pantalla (como el mockup), tomado
    // de la reserva de hoy. La barra inferior (bloque futuro) leerá el mismo.
    const asistioHoy = reservaHoy?.asistio === true;

    // "Reservar otra clase": baja al bloque "Clases disponibles" (la rejilla del
    // dashboard reutilizada). Si ese bloque aún no existe, abre Mis Reservas.
    const irAReservar = () => {
        const destino = document.getElementById('ub-clases');
        if (destino) destino.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else navigate('/alumno/mis-reservas');
    };

    return (
        <div className="ub-inicio" data-checked={asistioHoy ? '1' : '0'}>
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

                {/* ── Reserva de hoy: el único bloque naranja a pantalla completa ── */}
                <section className="hero" aria-label="Tu clase de hoy">
                    <div className="hr">
                        <span>Tu clase de hoy</span>
                        {reservaHoy && (
                            <span className="chip">
                                <span className="pend">Reserva confirmada</span>
                                <span className="done">Asististe</span>
                            </span>
                        )}
                    </div>
                    {reservaHoy ? (
                        <>
                            <div className="time">{horaCorta(reservaHoy.hora_inicio)}</div>
                            <div className="what">{reservaHoy.disciplina_nombre || 'Clase'}</div>
                            <div className="hint pend"><Icono nombre="scan" />Al llegar, escanea el QR de la entrada con la cámara de tu celular</div>
                            <div className="hint done"><Icono nombre="check" />Asistencia marcada</div>
                        </>
                    ) : (
                        <>
                            <div className="what empty">Sin clases hoy</div>
                            <div className="hint pend"><Icono nombre="scan" />Reserva tu próxima clase en “Clases disponibles”</div>
                        </>
                    )}
                </section>

                {/* ── Acciones rápidas de la reserva ── */}
                <div className="links">
                    <button type="button" onClick={() => navigate('/alumno/mis-reservas')}>Mis reservas</button>
                    <button type="button" onClick={irAReservar}>Reservar otra clase</button>
                </div>
            </div>
        </div>
    );
};

export default InicioMobile;
