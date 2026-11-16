import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
// TZ Chile: "hoy" en el calendario chileno (no el del navegador), misma fuente
// que el Dashboard (utils/fecha.js): así la reserva de hoy coincide con las clases.
import { hoyChileStr, fechaSolaAInstante } from '../../utils/fecha';
// Hora "HH:MM" del backend: la MISMA función que usa la grilla móvil compartida.
import { horaCorta } from '../../utils/grillaReserva';
// "Buenos días / Buenas tardes / Buenas noches": el copy de la tarjeta "Tu clase
// de hoy" según el momento del día en Chile (no el del teléfono).
import { copyClaseHoy, momentoDelDia, saludoDelMomento } from '../../utils/momentoDia';
import { useMiResumenAsistencia, useProductos, usePublicIdBox, useReservasAlumno } from '../../hooks/queries';
import ImagenProducto from '../../components/ImagenProducto';
import { MENU_BY_ROL } from '../../config/menu';
import { MENU_ICONS } from '../../config/menuIcons';
import EscanerQR from '../../components/EscanerQR';
// Carrusel "Novedades del box": los avisos de marketing del box (Bloque 4). Se
// dibuja sólo si hay avisos vigentes hoy; si no, no ocupa lugar.
import CarruselMarketing from '../../components/CarruselMarketing';
// Grilla de reserva MÓVIL compartida con la pestaña "Agendar Reserva" (Bloque 3):
// selector de día + tarjetas + botón Reservar salen de este componente, igual
// que la versión de escritorio (`GrillaReservaClases`). Nada de lógica duplicada.
import GrillaReservaClasesMobile from '../../components/GrillaReservaClasesMobile';
// Rótulo del cupo de créditos ("∞"/"—"): la MISMA regla que la tarjeta del
// Dashboard (≥768px), para que las dos pantallas no puedan divergir.
import { rotuloCreditos } from '../../utils/rotuloCreditos';
// Banner de estado del plan: qué vence primero (fecha/clases) + plan en cola.
import { textoBannerPlan } from '../../utils/bannerPlan';
// Estilos del "Inicio" móvil (mockup urban-box-inicio-pulido-1), acotados a
// `.ub-inicio`. Se construye por bloques; este archivo crece bloque a bloque.
import './inicioMobile.css';
// Badges de producto ("Nuevo" / "-N%") del carrusel Tienda Urban Box (migración 072).
import { esNuevo, tieneDescuento } from '../../utils/badgesProducto';

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

// Texto de un campo del WOD del día: null si viene vacío, para no dibujar
// secciones en blanco (Calentamiento, Musculación, etc.).
const textoWod = (v) => (typeof v === 'string' && v.trim() ? v : null);

// Estado VISIBLE de una reserva: lo calcula el backend (`estado_visible`) con
// la MISMA regla del Historial. El fallback mantiene la pantalla usable si una
// respuesta antigua todavía no trae el campo.
const estadoDeReserva = (reserva) => {
    if (reserva?.estado_visible) return reserva.estado_visible;
    if (reserva?.asistio === true) return 'asistio';
    const crudo = String(reserva?.estado || '').toLowerCase();
    return ['cancelada', 'cancelada_tarde', 'cancelled', 'canceled'].includes(crudo)
        ? 'cancelada'
        : 'reservada';
};

// Reserva que representa "Tu clase de hoy": la PRÓXIMA `reservada` y, si el
// día ya terminó, la ÚLTIMA clase del día. Así una clase de la mañana a la que
// no se asistió no tapa la de la tarde (ni al revés).
const elegirReservaHoy = (reservasDelDia) => {
    const ordenadas = (reservasDelDia || [])
        .slice()
        .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));
    const vigentes = ordenadas.filter(
        (r) => !['cancelada', 'cancelada_tarde'].includes(estadoDeReserva(r))
    );
    return vigentes.find((r) => estadoDeReserva(r) === 'reservada')
        || vigentes[vigentes.length - 1]
        // Si SÓLO hubo clases canceladas, se muestra la última con su estado
        // ("Cancelada") en vez de un "Sin clases hoy" que oculta lo que pasó.
        || ordenadas[ordenadas.length - 1]
        || null;
};

// Rótulo del hero para cada estado visible. "falto" es el no-show: la clase ya
// empezó y el alumno no marcó asistencia.
const ETIQUETA_ESTADO_HOY = {
    reservada: 'Reserva confirmada',
    asistio: 'Asististe',
    falto: 'No asististe',
    cancelada: 'Cancelada',
    cancelada_tarde: 'Cancelada',
};

// "31 de diciembre" en el calendario de Chile (para "Vence el ...").
const fechaLargaCortaChile = (valor) => {
    if (!valor) return '';
    const s = String(valor);
    const d = s.length === 10 ? new Date(`${s}T12:00:00Z`) : new Date(s);
    if (isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('es-CL', {
        timeZone: 'America/Santiago', day: 'numeric', month: 'long',
    }).format(d);
};

// Precio en CLP ("$100.000") desde el `precio` (numérico) del producto.
const precioCLP = (v) => {
    const n = Number(v);
    if (!isFinite(n)) return '';
    return new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP', maximumFractionDigits: 0 }).format(n);
};

// Íconos del mockup (trazo, 24px). Se definen aquí y crecen bloque a bloque.
const ICONOS = {
    scan: <path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16" />,
    check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
    lock: <g><path d="M7 11V7a5 5 0 0 1 10 0v4" /><rect x="4" y="11" width="16" height="9" rx="2" /></g>,
    x: <path d="M6 6l12 12M18 6 6 18" />,
    flame: <path d="M12 22c4 0 7-2.8 7-7 0-3-1.8-5-3-6.5-.5 1.5-1.5 2.5-2.5 3 0-4-1.5-7-4.5-9.5C9 7 5 10.5 5 15c0 4.2 3 7 7 7Z" />,
    tee: <path d="M8 3 3 6l2 4 3-1v11h8V9l3 1 2-4-5-3a4 4 0 0 1-8 0Z" />,
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
    nivelGimnastico,
    reservas = [],
    clasesPorDia = {},
    proximosDias = [],
    onReservar,
    wodHoy = null,
}) => {
    const navigate = useNavigate();
    const location = useLocation();

    // Datos complementarios del Inicio móvil (solo <768px): reservas de la
    // semana, resumen de asistencia (racha), productos del Bazar y public_id
    // del box (para el FAB de asistencia). El escritorio ≥768px no cambia.
    //
    // Fase 2 (React Query): las MISMAS queryKey que usan Bazar, Mis pedidos,
    // Mis reservas y Mi progreso, así que navegar entre esas pantallas ya no
    // vuelve a pedir ni el catálogo ni la racha. Claves y frescura por dato
    // viven en `hooks/queries.js` (una sola fuente).
    const { data: reservasSemana = [] } = useReservasAlumno();
    const { data: resumenAsistencia = null } = useMiResumenAsistencia();
    const { data: productos = [] } = useProductos({ activo: true });
    const { data: boxPublicId = null } = usePublicIdBox();
    // Overlay del lector QR (abre la cámara de inmediato al tocar "Marcar").
    const [escanerAbierto, setEscanerAbierto] = useState(false);
    // Tarjeta "WOD del día": colapsada por defecto para no ocupar espacio de
    // entrada; se despliega al tocar la fila.
    const [wodAbierto, setWodAbierto] = useState(false);

    // Momento del día (Chile) para el copy de "Tu clase de hoy". Se recalcula
    // cada minuto: si la pantalla queda abierta, a las 12:00 el saludo cambia
    // solo ("Buenos días" -> "Buenas tardes") sin recargar.
    const [momento, setMomento] = useState(() => momentoDelDia());
    useEffect(() => {
        const reloj = setInterval(() => setMomento(momentoDelDia()), 60000);
        return () => clearInterval(reloj);
    }, []);

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

    // Reservas de HOY en el calendario chileno y la que representa el hero.
    const reservasDeHoy = (Array.isArray(reservas) ? reservas : [])
        .filter((r) => soloFecha(r.clase_fecha || r.fecha) === hoy);
    const reservaHoy = elegirReservaHoy(reservasDeHoy);
    const estadoHoy = reservaHoy ? estadoDeReserva(reservaHoy) : null;

    // Asistió: la barra inferior y "Tu semana" se pintan verdes si el alumno
    // asistió a ALGUNA clase de hoy, aunque el hero muestre la próxima.
    const asistioHoy = reservasDeHoy.some(
        (r) => r.asistio === true || estadoDeReserva(r) === 'asistio'
    );

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

    // ── Bloque "Plan y créditos" ──
    // El rótulo del cupo es FUENTE ÚNICA (utils/rotuloCreditos.js): "∞" con plan
    // ilimitado y "—" si el cupo no está cargado (la fila puede venir en NULL: así
    // están las suscripciones ilimitadas de PROD). Nunca un 0 inventado, porque
    // NULL no significa "sin créditos". Sin plan activo el cupo vigente es 0 REAL
    // (el endpoint devuelve 0, no NULL, cuando no hay suscripción vigente).
    const creditosTxt = rotuloCreditos(ilimitado, activa ? membresia?.clases_disponibles : 0);
    const venceFmt = fechaLargaCortaChile(membresia?.fecha_vencimiento);
    const expTexto = !activa ? 'Sin plan activo'
        : diasRestantes > 0 ? (venceFmt ? `Vence el ${venceFmt}` : 'Plan activo')
            : 'Vence hoy';
    const exp2Texto = !activa ? 'Renuévalo para reservar'
        : diasRestantes > 1 ? `Quedan ${diasRestantes} días`
            : diasRestantes === 1 ? 'Queda 1 día'
                : 'Vence hoy';
    // Puntos = créditos restantes (tope 20, como el mockup). Ilimitado no lleva.
    const dotsN = (!ilimitado && creditos > 0) ? Math.min(creditos, 20) : 0;
    // Banner de estado del plan: qué vence primero (fecha o clases) y si el
    // próximo plan ya está pagado y en cola. `null` = sin plan activo.
    const banner = textoBannerPlan(membresia);

    // ── Bloque "Mis marcas" ──
    const marcaFuerza = (nivelFuerza?.top_rms || [])[0] || null;
    const [marcaNum, marcaUnit = 'kg'] = String(marcaFuerza?.valor || '').split(/\s+/);
    const nivelF = nivelFuerza?.nivel && nivelFuerza.nivel.toLowerCase() !== 'sin datos'
        ? capitalizar(nivelFuerza.nivel.toLowerCase()) : null;
    const nivelG = nivelGimnastico?.nivel && nivelGimnastico.nivel.toLowerCase() !== 'sin datos'
        ? capitalizar(nivelGimnastico.nivel.toLowerCase()) : null;

    // ── Bloque "Barra inferior": items desde config/menu.js ──
    const itemMenu = (label) => MENU_BY_ROL.alumno.find((i) => i.label === label);
    const navInicio = itemMenu('Inicio');
    // La pestaña se llama "Historial de Reservas" en config/menu.js; buscar el
    // nombre viejo ("Mis Reservas") devolvía undefined y el botón no se pintaba
    // (los 5 elementos del `.ub-nav` quedaban corridos una columna).
    const navReservas = itemMenu('Historial de Reservas');
    const navMarcas = itemMenu('Pizarra de RMs');
    const navBazar = itemMenu('Bazar');

    // ── Bloque "WOD del día" (afiche para toda la comunidad) ──
    // El backend ya devuelve el primer WOD publicado hoy del tenant cuando se
    // llama sin `alumno_id`: no depende de reserva ni asistencia. Sólo se
    // dibujan las secciones que traen contenido.
    const wodTitulo = textoWod(wodHoy?.titulo);
    const wodTipo = textoWod(wodHoy?.tipo_metcon);
    const wodCalentamiento = textoWod(wodHoy?.calentamiento);
    const wodFuerza = textoWod(wodHoy?.fuerza_habilidad);
    const wodPrincipal = textoWod(wodHoy?.wod_principal);
    const wodBloques = Array.isArray(wodHoy?.bloques) ? wodHoy.bloques : [];
    // FAB: escanea el QR del box (public_id); si no está, va a Mis Reservas.
    const irAAsistencia = () => setEscanerAbierto(true);

    // "Reservar otra clase": baja al bloque "Clases disponibles" (la rejilla del
    // dashboard reutilizada). Si ese bloque aún no existe, abre "Agendar Reserva"
    // (la pestaña para TOMAR una clase; antes este respaldo caía en el historial).
    const irAReservar = () => {
        const destino = document.getElementById('ub-clases');
        if (destino) destino.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else navigate('/alumno/agendar-reserva');
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
                <section className="hero" data-estado={estadoHoy || 'sin-clase'}
                    data-momento={momento} aria-label="Tu clase de hoy">
                    {/* Saludo del momento (hora de Chile): la misma tarjeta se
                        lee distinto a las 7 de la mañana y a las 10 de la noche. */}
                    <span className="momento" data-testid="momento-dia">
                        {saludoDelMomento(momento)}
                    </span>
                    <div className="hr">
                        <span>Tu clase de hoy</span>
                        {reservaHoy && (
                            <span className={`chip estado-${estadoHoy}`}>
                                {ETIQUETA_ESTADO_HOY[estadoHoy] || 'Reserva confirmada'}
                            </span>
                        )}
                    </div>
                    {reservaHoy ? (
                        <>
                            <div className="time">{horaCorta(reservaHoy.hora_inicio)}</div>
                            <div className="what">{reservaHoy.disciplina_nombre || 'Clase'}</div>
                            {estadoHoy === 'reservada' && (
                                <div className="hint pend"><Icono nombre="scan" />{copyClaseHoy('reservada', momento)}</div>
                            )}
                            {estadoHoy === 'asistio' && (
                                <div className="hint done"><Icono nombre="check" />{copyClaseHoy('asistio', momento)}</div>
                            )}
                            {estadoHoy === 'falto' && (
                                <div className="hint falto"><Icono nombre="x" />{copyClaseHoy('falto', momento)}</div>
                            )}
                            {(estadoHoy === 'cancelada' || estadoHoy === 'cancelada_tarde') && (
                                <div className="hint cancelada"><Icono nombre="x" />{copyClaseHoy('cancelada', momento)}</div>
                            )}
                        </>
                    ) : (
                        <>
                            <div className="what empty">Sin clases hoy</div>
                            <div className="hint pend"><Icono nombre="scan" />{copyClaseHoy(null, momento)}</div>
                        </>
                    )}
                </section>

                {/* ── WOD del día: afiche del entrenamiento para TODA la comunidad.
                    Colapsado por defecto (una fila angosta); al tocarlo se
                    despliega lo que publicó el coach, sin exigir reserva ni
                    asistencia. No es la pantalla de registro (MisWods). ── */}
                {wodHoy && (
                    <section className="card wod" aria-label="WOD del día">
                        <button
                            type="button"
                            className="wod-toggle"
                            aria-expanded={wodAbierto}
                            aria-controls="ub-wod-dia"
                            onClick={() => setWodAbierto((abierto) => !abierto)}
                        >
                            <span className="wod-title">WOD del día</span>
                            {wodTitulo && <span className="wod-nombre">{wodTitulo}</span>}
                            {wodTipo && <span className="pill lvl">{wodTipo}</span>}
                            <span className={`wod-arrow${wodAbierto ? ' up' : ''}`} aria-hidden="true">
                                ▾
                            </span>
                        </button>

                        {wodAbierto && (
                            <div className="wod-body" id="ub-wod-dia">
                                {wodCalentamiento && (
                                    <div className="wod-sec">
                                        <h3>Calentamiento</h3>
                                        <p>{wodCalentamiento}</p>
                                    </div>
                                )}
                                {wodFuerza && (
                                    <div className="wod-sec">
                                        <h3>Musculación</h3>
                                        <p>{wodFuerza}</p>
                                    </div>
                                )}
                                {wodPrincipal && (
                                    <div className="wod-sec principal">
                                        <h3>WOD principal</h3>
                                        <p>{wodPrincipal}</p>
                                    </div>
                                )}
                                {wodBloques.length > 0 && (
                                    <div className="wod-bloques">
                                        {wodBloques.map((bloque, indice) => {
                                            const tipoBloque = textoWod(bloque?.tipo_metcon);
                                            return (
                                                <div className="wod-bloque" key={bloque?.id || indice}>
                                                    <div className="wod-bloque-head">
                                                        <div className="wod-bloque-info">
                                                            <span className="wod-bloque-n">Bloque {indice + 1}</span>
                                                            <b>{bloque?.titulo || `Bloque ${indice + 1}`}</b>
                                                        </div>
                                                        {tipoBloque && <span className="pill lvl">{tipoBloque}</span>}
                                                    </div>
                                                    {textoWod(bloque?.descripcion) && (
                                                        <p>{bloque.descripcion}</p>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        )}
                    </section>
                )}

                {/* ── Acciones rápidas de la reserva ── */}
                <div className="links">
                    <button type="button" onClick={() => navigate('/alumno/mis-reservas')}>Historial</button>
                    <button type="button" onClick={irAReservar}>Reservar otra clase</button>
                </div>

                {/* ── Novedades del box: el carrusel de avisos de marketing ──
                    Va entre las acciones de la reserva y "Tu semana": es lo primero
                    que el alumno ve después de su clase y no empuja la reserva de hoy.
                    Si no hay avisos vigentes, el componente no dibuja nada. */}
                <CarruselMarketing />

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

                {/* -- Plan y creditos -- */}
                <section className="card sec" aria-label="Plan y créditos">
                    <div className="ph">
                        <div>
                            <small>Clases restantes</small>
                            <div className="cnum">{creditosTxt}</div>
                        </div>
                        <div className="pr">
                            {plan && <span className="pill plan">{plan}</span>}
                            <span className="exp">{expTexto}</span>
                            <span className="exp2">{exp2Texto}</span>
                        </div>
                    </div>
                    {dotsN > 0 && (
                        <div className="dots" aria-hidden="true">
                            {Array.from({ length: dotsN }).map((_, i) => <i key={i} />)}
                        </div>
                    )}
                    <p className="pace">
                        {!activa
                            ? 'Sin plan activo: activa uno para volver a reservar.'
                            : ilimitado
                                ? 'Plan ilimitado: reserva las clases que quieras.'
                                : creditos <= 0
                                    ? 'Sin clases. Renueva tu plan para reservar.'
                                    : diasRestantes < 7
                                        ? 'Quedan pocos días: usa las clases que puedas.'
                                        : <>Para usarlos todos, necesitas unas <b>{porSemana} clases por semana</b>.</>}
                    </p>
                    {banner && (
                        <div className={`ctx${banner.asegurado ? ' asegurado' : ''}`}>
                            <div>
                                <b>{banner.titulo}</b>
                                <span>{banner.detalle}</span>
                            </div>
                            {banner.asegurado ? (
                                <span className="ctx-seguro"
                                    title="Tu siguiente plan está asegurado"
                                    aria-label="Tu siguiente plan está asegurado">
                                    <Icono nombre="lock" />
                                </span>
                            ) : (
                                <button type="button" onClick={() => navigate('/alumno/solicitar-plan')}>Renovar</button>
                            )}
                        </div>
                    )}
                </section>

                {/* -- Mis marcas (fuerza/gimnastico). Sin calculadora de discos -- */}
                <section className="card sec" aria-label="Mis marcas">
                    <div className="head">
                        <h2>Mis marcas</h2>
                        <button type="button" className="link" onClick={() => navigate('/alumno/performance-hub')}>Ver Performance Hub</button>
                    </div>
                    <div className="m1">
                        <div>
                            <small>Fuerza</small>
                            <b>{marcaFuerza ? marcaFuerza.movimiento : 'Sin registros'}</b>
                            {nivelF && <span className="pill lvl">{nivelF}</span>}
                        </div>
                        {marcaFuerza && <div className="goldnum">{marcaNum}<em>{marcaUnit}</em></div>}
                    </div>
                    <div className="m2">
                        <span>Gimnástico: {nivelG ? nivelG.toLowerCase() : 'sin datos'}</span>
                        <button type="button" className="addbtn" onClick={() => navigate('/alumno/rms')}>Registrar RMs</button>
                    </div>
                </section>

                {/* ── Clases disponibles: la MISMA grilla móvil que la pestaña
                    "Agendar Reserva" (componente compartido, Bloque 3). Es el
                    ancla de "Reservar otra clase" (#ub-clases). ── */}
                <GrillaReservaClasesMobile
                    proximosDias={proximosDias}
                    clasesPorDia={clasesPorDia}
                    onReservar={onReservar}
                />

                {/* -- Tienda Urban Box (vista rapida): productos reales del Bazar -- */}
                <section className="sec" aria-label="Tienda Urban Box">
                    <div className="head">
                        <h2>Tienda Urban Box</h2>
                        <button type="button" className="link" onClick={() => navigate('/alumno/bazar')}>Ver todo</button>
                    </div>
                    {productos.length > 0 ? (
                        <div className="shop">
                            {productos.slice(0, 5).map((p) => (
                                // La tarjeta lleva DIRECTO al flujo de compra de ESE producto:
                                // el Bazar lee `?producto=<id>` y abre el paso 2 (pago). Antes
                                // era un <div> decorativo y tocar no hacía nada.
                                <button
                                    type="button"
                                    className="prod"
                                    key={p.id}
                                    onClick={() => navigate(`/alumno/bazar?producto=${p.id}`)}
                                    aria-label={`Comprar ${p.nombre || 'producto'}`}
                                >
                                    {esNuevo(p.created_at) && (
                                        <span className="badge-nuevo">Nuevo</span>
                                    )}
                                    {tieneDescuento(p.descuento_pct) && (
                                        <span className="badge-descuento">-{p.descuento_pct}%</span>
                                    )}
                                    {/* Marco industrial: 4 remaches + panel metal/carbono
                                        (mismos que la tarjeta del Bazar, escalados). */}
                                    <span className="prod-remache prod-remache--tl" aria-hidden="true" />
                                    <span className="prod-remache prod-remache--tr" aria-hidden="true" />
                                    <span className="prod-remache prod-remache--bl" aria-hidden="true" />
                                    <span className="prod-remache prod-remache--br" aria-hidden="true" />
                                    <div className="prod-panel">
                                        <div className="img">
                                            <ImagenProducto
                                                url={p.imagen_url}
                                                alt={p.nombre || 'Producto'}
                                                respaldo={<Icono nombre="tee" />}
                                            />
                                        </div>
                                        <b>{p.nombre}</b>
                                        <span className="prod-precio">{precioCLP(p.precio)}</span>
                                    </div>
                                </button>
                            ))}
                        </div>
                    ) : (
                        <p className="vacio">El box aún no publicó productos.</p>
                    )}
                </section>
            </div>

            {/* -- Barra inferior: Inicio - Reservas - FAB - Marcas - Bazar -- */}
            <nav className="ub-nav" aria-label="Navegación del alumno">
                {navInicio && (
                    <button type="button" className={`t${location.pathname === navInicio.path ? ' on' : ''}`} onClick={() => navigate(navInicio.path)}>
                        {MENU_ICONS[navInicio.icon]}<span>Inicio</span>
                    </button>
                )}
                {navReservas && (
                    <button type="button" className={`t${location.pathname === navReservas.path ? ' on' : ''}`} onClick={() => navigate(navReservas.path)}>
                        {MENU_ICONS[navReservas.icon]}<span>Reservas</span>
                    </button>
                )}
                <div className="mid">
                    <button type="button" className="fab" aria-label="Marcar asistencia" onClick={irAAsistencia}>
                        <span className="pend"><Icono nombre="scan" /></span>
                        <span className="done"><Icono nombre="check" /></span>
                    </button>
                    <span className="pend">Marcar</span><span className="done">Asististe</span>
                </div>
                {navMarcas && (
                    <button type="button" className={`t${location.pathname === navMarcas.path ? ' on' : ''}`} onClick={() => navigate(navMarcas.path)}>
                        {MENU_ICONS[navMarcas.icon]}<span>Marcas</span>
                    </button>
                )}
                {navBazar && (
                    <button type="button" className={`t${location.pathname === navBazar.path ? ' on' : ''}`} onClick={() => navigate(navBazar.path)}>
                        {MENU_ICONS[navBazar.icon]}<span>Bazar</span>
                    </button>
                )}
            </nav>

            {/* Lector QR: overlay con la cámara (abre al tocar el FAB "Marcar"). */}
            {escanerAbierto && (
                <EscanerQR
                    onCerrar={() => setEscanerAbierto(false)}
                    publicIdFallback={boxPublicId}
                />
            )}
        </div>
    );
};

export default InicioMobile;
