import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
// TZ Chile: "hoy" en el calendario chileno (no el del navegador), misma fuente
// que el Dashboard (utils/fecha.js): así la reserva de hoy coincide con las clases.
import { hoyChileStr, fechaSolaAInstante } from '../../utils/fecha';
import api from '../../services/api';
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

// Dedupe de filas repetidas del backend (varias sedes comparten disciplina y
// hora), mismo criterio que AGRUPAR_CLASES del Dashboard.
const agruparClases = (clases) => {
    const vistos = new Set();
    return (clases || []).filter((c) => {
        const clave = `${c.disciplina_nombre || ''}|${c.hora_inicio || ''}|${c.hora_fin || ''}`;
        if (vistos.has(clave)) return false;
        vistos.add(clave);
        return true;
    });
};

// ── Semana en curso (lunes a domingo) del calendario CHILENO ──
const LETRAS_SEMANA = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
const lunesDeLaSemanaChile = (hoyStr) => {
    const base = fechaSolaAInstante(hoyStr); // mediodía UTC
    const dow = base.getUTCDay();            // 0=DOM .. 6=SAB
    return new Date(base.getTime() - ((dow + 6) % 7) * 86400000);
};
const diasDeLaSemana = (hoyStr) => {
    const lunes = lunesDeLaSemanaChile(hoyStr);
    return LETRAS_SEMANA.map((letra, i) => {
        const d = new Date(lunes.getTime() + i * 86400000);
        return { letra, fechaStr: d.toISOString().slice(0, 10), diaNum: d.getUTCDate() };
    });
};

// 'YYYY-MM-DD' de un valor de fecha (a veces llega con hora ISO).
const soloFecha = (v) => (v ? String(v).slice(0, 10) : '');

// Íconos del mockup (trazo, 24px). Se definen aquí y crecen bloque a bloque.
const ICONOS = {
    scan: <path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16" />,
    check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
    flame: <path d="M12 22c4 0 7-2.8 7-7 0-3-1.8-5-3-6.5-.5 1.5-1.5 2.5-2.5 3 0-4-1.5-7-4.5-9.5C9 7 5 10.5 5 15c0 4.2 3 7 7 7Z" />,
};

const Icono = ({ nombre }) => (
    <svg className="i" viewBox="0 0 24 24" aria-hidden="true">{ICONOS[nombre]}</svg>
);

/**
 * Inicio del alumno para <768px. Recibe los datos ya consultados por el
 * Dashboard (nada de fetches duplicados) y pinta el diseño del mockup.
 *
 * Bloques: identidad (1), clase de hoy (2), clases disponibles (3)…
 */
const InicioMobile = ({
    usuario,
    membresia,
    nivelFuerza,
    reservas = [],
    clasesPorDia = {},
    proximosDias = [],
    onReservar,
}) => {
    const navigate = useNavigate();

    // Datos complementarios del bloque "Tu semana": la lista de reservas
    // (incluye asistencias pasadas, que el hero no necesita) y el resumen de
    // asistencia (racha). Vive dentro de InicioMobile (solo móvil <768px); el
    // escritorio ≥768px no cambia.
    const [reservasSemana, setReservasSemana] = useState([]);
    const [resumenAsistencia, setResumenAsistencia] = useState(null);
    useEffect(() => {
        let cancelado = false;
        Promise.allSettled([
            api.get('/api/v1/reservas'),
            api.get('/api/v1/asistencia/mi-resumen'),
        ]).then(([rReservas, rResumen]) => {
            if (cancelado) return;
            if (rReservas.status === 'fulfilled' && Array.isArray(rReservas.value.data)) {
                setReservasSemana(rReservas.value.data);
            }
            if (rResumen.status === 'fulfilled') {
                setResumenAsistencia(rResumen.value.data);
            }
        });
        return () => { cancelado = true; };
    }, []);

    // "Hoy" en el calendario CHILENO (misma fuente que el Dashboard).
    const hoy = hoyChileStr();

    // Día elegido en "Clases disponibles". Arranca en el primer día con clases
    // (igual que el acordeón del Dashboard); se fija cuando llegan los datos.
    const [diaSeleccionado, setDiaSeleccionado] = useState(null);
    useEffect(() => {
        if (diaSeleccionado) return;
        const primero = proximosDias.find((d) => (clasesPorDia[d.fecha] || []).length > 0);
        if (primero) setDiaSeleccionado(primero.fecha);
    }, [proximosDias, clasesPorDia, diaSeleccionado]);

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

    // ── Plan y créditos (los usa "Tu semana" para el ritmo ideal y, además,
    //    el bloque "Plan y créditos") ──
    const activa = Boolean(membresia?.activa);
    const ilimitado = Boolean(membresia?.es_ilimitado);
    const creditos = activa ? (Number(membresia?.clases_disponibles) || 0) : 0;
    const diasRestantes = activa ? (Number(membresia?.dias_restantes) || 0) : 0;
    // Ritmo ideal: clases/semana para consumir los créditos antes del
    // vencimiento (tope 7), mismo cálculo que el mockup.
    const porSemana = !activa ? 0
        : ilimitado ? 7
            : creditos > 0 ? Math.min(7, Math.ceil(creditos / (Math.max(diasRestantes, 1) / 7)))
                : 0;
    const segN = Math.max(porSemana, 1);

    // ── Bloque "Tu semana": círculos L-D desde /api/v1/reservas ──
    const diasSemana = diasDeLaSemana(hoy);
    const fechasSemana = new Set(diasSemana.map((d) => d.fechaStr));
    const diasConAsistencia = new Set(
        reservasSemana
            .filter((r) => r.asistio === true)
            .map((r) => soloFecha(r.clase_fecha || r.fecha))
    );
    const semanaRender = diasSemana.map((d) => ({
        ...d,
        esHoy: d.fechaStr === hoy,
        asistio: diasConAsistencia.has(d.fechaStr),
    }));
    // Clases con asistencia=true dentro de la semana L-D en curso.
    const asistidasSemana = reservasSemana.filter(
        (r) => r.asistio === true && fechasSemana.has(soloFecha(r.clase_fecha || r.fecha))
    ).length;

    // Racha real (meses consecutivos al 100%) desde /api/v1/asistencia/mi-resumen.
    const racha = Number(resumenAsistencia?.racha_actual) || 0;
    const rachaTexto = racha > 0
        ? `Racha de ${racha} ${racha === 1 ? 'mes' : 'meses'} consecutivos al 100%`
        : 'Completa un mes al 100% para iniciar tu racha';

    // Clases del día elegido: deduplicadas (varias sedes comparten disciplina y
    // hora) y ordenadas por horario, como la rejilla del Dashboard.
    const clasesDelDia = agruparClases(clasesPorDia[diaSeleccionado] || [])
        .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));

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

                {/* -- Tu semana: circulos L-D derivados de /api/v1/reservas + racha -- */}
                <section className="card sec" aria-label="Tu semana">
                    <div className="head"><h2>Tu semana</h2></div>
                    <div className="wk">
                        {semanaRender.map((d) => (
                            <div className={`day${d.asistio ? ' att' : ''}${d.esHoy ? ' today' : ''}`} key={d.fechaStr}>
                                <span className="dl">{d.letra}</span>
                                <div className="circ">{d.asistio ? <Icono nombre="check" /> : d.diaNum}</div>
                            </div>
                        ))}
                    </div>
                    <div className="goal">
                        <div className="gl">
                            <b>{asistidasSemana} de {porSemana} clases esta semana</b>
                            <span>Tu ritmo ideal</span>
                        </div>
                        <div className="segs" style={{ gridTemplateColumns: `repeat(${segN}, 1fr)` }}>
                            {Array.from({ length: segN }).map((_, i) => (
                                <i key={i} className={i < asistidasSemana ? 'f' : i === asistidasSemana ? 'n' : ''} />
                            ))}
                        </div>
                    </div>
                    <div className="streak">
                        <Icono nombre="flame" />
                        <span>{rachaTexto}</span>
                    </div>
                </section>

                {/* ── Clases disponibles: rejilla del Dashboard adaptada a móvil.
                    Es el ancla de "Reservar otra clase" (#ub-clases). ── */}
                <section className="card sec" id="ub-clases" aria-label="Clases disponibles">
                    <div className="head">
                        <h2>Clases disponibles</h2>
                    </div>

                    {proximosDias.length > 0 && (
                        <div className="days" role="tablist" aria-label="Elige el día">
                            {proximosDias.map((d) => {
                                const n = (clasesPorDia[d.fecha] || []).length;
                                const activo = d.fecha === diaSeleccionado;
                                return (
                                    <button
                                        key={d.fecha}
                                        type="button"
                                        role="tab"
                                        aria-selected={activo}
                                        className={`day${activo ? ' on' : ''}`}
                                        onClick={() => setDiaSeleccionado(d.fecha)}
                                    >
                                        <span className="dn">{d.nombreDia.substring(0, 3)}</span>
                                        <span className="dd">{d.diaNum}</span>
                                        <span className={`dc${n ? ' has' : ''}`}>{n || '–'}</span>
                                    </button>
                                );
                            })}
                        </div>
                    )}

                    <div className="clases">
                        {clasesDelDia.length === 0 ? (
                            <p className="vacio">Sin clases programadas este día.</p>
                        ) : (
                            clasesDelDia.map((clase) => {
                                const cupos = (clase.cupo_maximo || 0) - (clase.asistentes_confirmados || 0);
                                const libre = cupos > 0;
                                return (
                                    <div className="clase" key={clase.id}>
                                        <div className="ci">
                                            <span className="ch">{horaCorta(clase.hora_inicio)}</span>
                                            <span className="cd">{clase.disciplina_nombre || 'Clase'}</span>
                                            <span className="cc">{clase.coach_nombre ? `Con ${clase.coach_nombre}` : 'Coach por confirmar'}</span>
                                        </div>
                                        <div className="cq">
                                            <span className={`cupos${libre ? ' ok' : ' no'}`}>
                                                {libre ? `${cupos} cupos` : 'Lleno'}
                                            </span>
                                            <button
                                                type="button"
                                                className="res"
                                                disabled={!libre}
                                                onClick={() => onReservar && onReservar(clase)}
                                            >
                                                {libre ? 'Reservar' : 'Lleno'}
                                            </button>
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
};

export default InicioMobile;
