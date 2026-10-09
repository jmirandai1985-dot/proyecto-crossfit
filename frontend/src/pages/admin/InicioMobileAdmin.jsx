import React, { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
// Voucher privado: el blob se pide CON token (el mismo hook que usan el Dashboard
// ≥768px y Pendientes). Sin él, la URL pública /static/uploads/... no sirve.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';
// Hora de CHILE (el navegador puede estar en otra zona) para el reloj y la franja actual.
import { horaChileStr, hoyChileStr } from '../../utils/fecha';
// Cupo de créditos del alumno: la MISMA regla que el resto del panel (ilimitado -> ∞,
// cupo sin cargar -> —, número -> el número).
import { rotuloCreditos } from '../../utils/rotuloCreditos';
// Texto "hace 12 min / ayer / hace 18 días": una sola definición para el voucher,
// el correo manual y los pedidos esperando retiro (util con test aislado propio).
import { textoHace } from '../../utils/hace';
// Rótulos de la tarjeta "Alumnos nuevos y en prueba" (estado, días y fecha de alta).
import {
    textoEstadoPrueba, tonoEstadoPrueba, textoAlta, textoEnPrueba,
} from '../../utils/pruebaAlumnos';
// Pedidos listos para entrega (Bazar): qué fila se lista y qué dice cada una.
import {
    esListoParaEntrega, codigoRetiro, textoProducto, textoEspera,
    textoInformado, mapaInformados,
} from '../../utils/pedidosEntrega';
// Vista previa del aviso de retiro: la petición viaja CON PLAZO. Sin esto, una petición
// que no responde dejaba el modal girando para siempre (bug de PROD: ver utils/avisoRetiro.js).
import { cargarPreviewAviso } from '../../utils/avisoRetiro';
// Enlace de contacto del alumno: wa.me armado desde el teléfono cargado (o nada).
import { enlaceWhatsapp } from '../../utils/whatsapp';
// Corte por franjas de "Asistencia de hoy" (cálculo puro, con test aislado propio).
import {
    FRANJAS, agruparPorFranja, franjaActual, resumenFranja,
    claseEnCurso, ocupacion, horaCorta, estaMarcada,
} from '../../utils/franjasAsistencia';
// Estilos del Dashboard móvil del admin (mockup admin-mobile-mockup.html), acotados a
// `.ub-admin`: NO alcanzan la versión ≥768px ni el tema del resto del panel.
import './inicioMobileAdmin.css';

// Íconos del mockup (trazo 24px). Se definen acá y crecen bloque a bloque.
const ICONOS = {
    users: <path d="M9 8a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5M17 5a3.5 3.5 0 0 1 0 6.5M21.5 20c-.3-2.4-1.5-4-3.5-4.8" />,
    clock: <path d="M12 5.5V13l2.5 1.5M12 20.5a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15ZM9 2.5h6" />,
    voucher: <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 14l2 2 3.5-4" />,
    caja: <path d="M3 6h18v12H3zM12 14a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />,
    search: <path d="M11 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM20 20l-4-4" />,
    heart: <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.4A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z" />,
    cart: <path d="M6 7h13l-1.5 8H8L6 4H3M9 19a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6M17 19a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6" />,
    check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
};

const Icono = ({ nombre }) => (
    <svg viewBox="0 0 24 24" aria-hidden="true">{ICONOS[nombre]}</svg>
);

/**
 * Capa de overlays del dashboard móvil, montada en <body> (portal).
 *
 * POR QUÉ EXISTE (bug 10/08/2026: "el buscador queda tapado por el header"):
 * este componente se pinta dentro de `<main>` → `<div className="relative z-10">`
 * del Layout, y ese `z-index:10` crea un CONTEXTO DE APILADO que queda por debajo
 * del header (`relative z-30`). Consecuencia: un `position:fixed; z-index:50>` de
 * acá adentro no puede tapar el header NUNCA (el z-index es relativo a su contexto),
 * así que la franja superior de la pantalla completa —la barra con la flecha y el
 * input de búsqueda— quedaba escondida detrás del header y no había scroll que la
 * salvara (la capa es `fixed`).
 *
 * El portal saca la capa de ese contexto (queda al nivel de `#root`, z-index 50 >
 * 30 del header) y `md:hidden` la borra en ≥768px: la regla de oro no se toca y,
 * de paso, un overlay abierto en <768px ya no puede "filtrarse" al escritorio al
 * agrandar la ventana.
 *
 * `top` (alto REAL del header, medido con el DOM) deja la pantalla completa JUSTO
 * debajo del header: el input queda siempre visible, sin scroll.
 */
const CapaMovil = ({ top = 0, children }) => createPortal(
    <div className="ub-admin ub-capa md:hidden"
        style={{ '--ub-capa-top': `${top}px` }}>
        {children}
    </div>,
    document.body,
);

/** "$186.000" (o "" si el valor no es un número: nunca "$NaN"). */
const precioCLP = (v) => {
    const n = Number(v);
    if (!isFinite(n)) return '';
    return new Intl.NumberFormat('es-CL', {
        style: 'currency', currency: 'CLP', maximumFractionDigits: 0,
    }).format(n);
};

/** "mié 7 oct" en el calendario de Chile (la fecha que se muestra arriba de los KPIs). */
const fechaCorta = () => {
    const s = new Intl.DateTimeFormat('es-CL', {
        timeZone: 'America/Santiago', weekday: 'short', day: 'numeric', month: 'short',
    }).format(new Date());
    return s.replace(/\./g, '').replace(',', '');
};

/** "hace 12 min" / "hace 2 h" / "ayer" — antigüedad (misma definición que el util). */
const haceCuanto = (valor) => textoHace(valor);

/**
 * Motivo legible de una promesa rechazada (una llamada que falló).
 * Regla del panel: el error va A LA VISTA con su motivo; nunca un 0 disfrazado de dato.
 */
const motivoError = (resultado) => resultado?.reason?.response?.data?.detail
    || (resultado?.reason?.response?.status
        ? `HTTP ${resultado.reason.response.status}` : resultado?.reason?.message)
    || 'No se pudo cargar';

/** "05" desde 5 (para el rango "05:00 a 12:00" del mockup). */
const dosDigitos = (n) => String(n).padStart(2, '0');

/** Iniciales del avatar ("Camila Soto" -> "CS"), máximo 2 letras. */
const iniciales = (nombre) => {
    const palabras = String(nombre || '').trim().split(/\s+/).filter(Boolean);
    if (!palabras.length) return '?';
    if (palabras.length === 1) return palabras[0].charAt(0).toUpperCase();
    return (palabras[0].charAt(0) + palabras[palabras.length - 1].charAt(0)).toUpperCase();
};

/** Píldora de estado del alumno en la ficha rápida (plan y días que le quedan). */
const estadoAlumno = (membresia) => {
    if (!membresia) return { clase: 'bad', texto: 'Sin plan' };
    const dias = membresia.dias_restantes;
    if (dias === null || dias === undefined) return { clase: 'warn', texto: 'Sin vencimiento' };
    if (dias <= 0) return { clase: 'bad', texto: 'Vence hoy' };
    if (dias <= 5) return { clase: 'warn', texto: `Vence en ${dias} d` };
    return { clase: 'ok', texto: 'Al día' };
};

/** "31 oct" del vencimiento (o "—" si no hay dato). */
const fechaVencimiento = (valor) => {
    if (!valor) return '—';
    const d = new Date(valor);
    if (isNaN(d.getTime())) return '—';
    return new Intl.DateTimeFormat('es-CL', {
        timeZone: 'America/Santiago', day: 'numeric', month: 'short',
    }).format(d).replace('.', '');
};

/** "hoy" / "ayer" / "hace 18 d" de la última asistencia (fecha del día chileno). */
const ultimaVisita = (fecha) => {
    const dia = fecha ? String(fecha).slice(0, 10) : '';
    if (!dia) return '—';
    const dias = Math.round((Date.parse(hoyChileStr()) - Date.parse(dia)) / 86400000);
    if (!isFinite(dias) || dias < 0) return '—';
    if (dias === 0) return 'hoy';
    if (dias === 1) return 'ayer';
    return `hace ${dias} d`;
};

/**
 * Tarjeta KPI. Regla del panel: si el endpoint falló se muestra "s/d" + el motivo
 * (nunca un 0 falso, que en un panel de caja se lee como "no entró plata").
 *
 * `chevron` marca las que ABREN una pantalla (en vez de navegar a otra sección) y
 * `testid` permite distinguir dos tarjetas que usan el mismo ícono.
 */
const Kpi = ({ clase, icono, label, valor, sub, error, cargando, dinero, pulso, onClick,
    chevron, testid }) => (
    <button type="button" className={`kpi ${clase}`} onClick={onClick}
        aria-label={label} data-testid={testid || `kpi-${icono}`}>
        {pulso && <span className="pulse" />}
        <span className="kpi-top">
            <span className="chip"><Icono nombre={icono} /></span>
            <span className="kpi-label">{label}</span>
            {chevron && <span className="kpi-go" aria-hidden="true">›</span>}
        </span>
        <span>
            <span className="kpi-val">
                <b className={`num${dinero ? ' money' : ''}`}>
                    {error ? 's/d' : cargando ? '·' : dinero ? precioCLP(valor) : (valor ?? '—')}
                </b>
            </span>
            {error
                ? <span className="kpi-error">{error}</span>
                : <span className="kpi-sub">{sub}</span>}
        </span>
    </button>
);

/**
 * Dashboard del admin para <768px (mockup admin-mobile-mockup.html) con datos REALES.
 *
 * No reemplaza ninguna pantalla: resume y enlaza a las que ya existen (Pendientes,
 * Asistencia, Supervisión, Alumnos, Bazar). Los datos salen de los MISMOS endpoints que
 * usa el panel de escritorio, más `GET /finanzas/resumen-hoy` (caja del día).
 *
 * Bloques: KPIs (A), accesos rápidos (B), "En revisión" (C), "Asistencia de hoy" (D) y
 * buscador de alumnos (E).
 */
const InicioMobileAdmin = () => {
    const navigate = useNavigate();
    const { tenant_id } = useAuth();

    // ── KPIs: un dato por tarjeta y error POR BLOQUE ─────────────────────────
    // Si un endpoint falla, ESA tarjeta dice "s/d" con el motivo y las demás siguen
    // mostrando su número real (mismo criterio que el panel ≥768px).
    const [kpis, setKpis] = useState({
        activos: null, nuevosMes: null, vencen: null, caja: null, pagos: null,
    });
    const [errores, setErrores] = useState({ activos: '', vencen: '', vouchers: '', caja: '' });
    const [cargando, setCargando] = useState(true);

    // Vouchers pendientes: el MISMO listado que alimenta la pantalla Pendientes.
    const [vouchers, setVouchers] = useState([]);

    // ── G. "Pedidos listos para entrega" (indicador del Bazar + pantalla) ────
    // El indicador y la pantalla usan el MISMO listado que la pantalla Pedidos del
    // admin (`GET /pedidos?estado=validado`): validados que aún nadie retiró.
    const [pedidos, setPedidos] = useState([]);
    const [pedidosError, setPedidosError] = useState('');
    const [listaPedidos, setListaPedidos] = useState(false);   // pantalla abierta
    const [pedidosCargando, setPedidosCargando] = useState(false);
    const [informados, setInformados] = useState({});          // {pedido_id: fecha}
    // Vista previa del aviso al comprador: { pedido, cargando, preview, error, enviando }.
    const [aviso, setAviso] = useState(null);

    const cargarKpis = useCallback(async () => {
        setCargando(true);
        const [rReportes, rVencen, rVouchers, rCaja, rPedidos] = await Promise.allSettled([
            // Alumnos activos + nuevos del mes: el MISMO /reportes/ del panel ≥768px
            // (definición única del BI: `metricas_service.alumnos_vigentes`).
            api.get('/api/v1/reportes/', { params: { tenant_id } }),
            // Vencen en los próximos 5 días: el endpoint que ya usa Fidelización.
            api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/vencimientos`),
            // Vouchers por aprobar: el MISMO listado de "Pendientes".
            api.get('/api/v1/solicitudes/pendientes'),
            // Caja del día (endpoint aditivo: suma la tabla de los KPIs).
            api.get('/api/v1/finanzas/resumen-hoy'),
            // Pedidos validados sin retirar: el indicador del Bazar (y su pantalla).
            api.get('/api/v1/pedidos', { params: { estado: 'validado' } }),
        ]);

        const motivo = motivoError;

        const errs = { activos: '', vencen: '', vouchers: '', caja: '', pedidos: '' };
        const nuevos = { activos: null, nuevosMes: null, vencen: null, caja: null, pagos: null };

        if (rReportes.status === 'fulfilled') {
            nuevos.activos = rReportes.value.data?.alumnosActivos ?? null;
            nuevos.nuevosMes = rReportes.value.data?.nuevosAlumnosMes ?? null;
        } else {
            errs.activos = motivo(rReportes);
        }

        if (rVencen.status === 'fulfilled') {
            nuevos.vencen = rVencen.value.data?.total_vencimientos ?? null;
        } else {
            errs.vencen = motivo(rVencen);
        }

        if (rVouchers.status === 'fulfilled') {
            setVouchers(Array.isArray(rVouchers.value.data) ? rVouchers.value.data : []);
        } else {
            errs.vouchers = motivo(rVouchers);
        }

        if (rCaja.status === 'fulfilled') {
            nuevos.caja = rCaja.value.data?.ingresos ?? null;
            nuevos.pagos = rCaja.value.data?.pagos ?? null;
        } else {
            errs.caja = motivo(rCaja);
        }

        if (rPedidos.status === 'fulfilled') {
            // Sólo los que de verdad esperan retiro (la misma regla que la pantalla).
            setPedidos((Array.isArray(rPedidos.value.data) ? rPedidos.value.data : [])
                .filter(esListoParaEntrega));
            setPedidosError('');
        } else {
            setPedidos([]);
            setPedidosError(motivo(rPedidos));
        }

        setKpis(nuevos);
        setErrores(errs);
        setCargando(false);
    }, [tenant_id]);

    useEffect(() => {
        cargarKpis();
    }, [cargarKpis]);

    const hayVouchers = vouchers.length > 0;

    // ── C. "En revisión": revisar el comprobante y aprobar/rechazar ──────────
    const [revision, setRevision] = useState(null);      // voucher abierto (objeto)
    const [motivoRechazo, setMotivoRechazo] = useState('');
    const [procesando, setProcesando] = useState(false);
    const [ampliado, setAmpliado] = useState(false);     // comprobante a pantalla completa
    const [toast, setToast] = useState(null);            // { texto, error }
    // El documento se pide CON token al endpoint de solicitudes (blob), nunca por su URL.
    const voucherDoc = useDocumentoAutenticado({
        previewUrl: revision ? `/api/v1/solicitudes/${revision.id}/voucher?inline=1` : '',
        nombreFallback: revision ? `voucher_${revision.id}` : 'voucher',
    });

    // ── D. "Asistencia de hoy" ──────────────────────────────────────────────
    const [clases, setClases] = useState([]);
    const [clasesCargando, setClasesCargando] = useState(true);
    const [clasesError, setClasesError] = useState('');
    const [franja, setFranja] = useState(null);          // franja elegida (default: la del reloj)
    const [ahora, setAhora] = useState(() => horaChileStr());
    const [roster, setRoster] = useState(null);          // { clase, reservas, marcada }
    const [marcados, setMarcados] = useState({});        // reserva_id -> asistió
    const [rosterCargando, setRosterCargando] = useState(false);
    const [guardando, setGuardando] = useState(false);

    const cargarClases = useCallback(async () => {
        setClasesCargando(true);
        try {
            // MISMO endpoint que usan Asistencia y Supervisión. El admin recibe el día
            // completo (el coach, solo lo que resta).
            const res = await api.get('/api/v1/asistencia/clases-hoy');
            setClases(Array.isArray(res.data) ? res.data : []);
            setClasesError('');
        } catch (err) {
            setClases([]);
            setClasesError(err.response?.data?.detail || 'No se pudieron cargar las clases de hoy');
        }
        setClasesCargando(false);
    }, []);

    useEffect(() => {
        cargarClases();
    }, [cargarClases]);

    // Reloj de la tarjeta ("Ahora · 14:05") + punto de la franja actual, cada 30s.
    useEffect(() => {
        const t = setInterval(() => setAhora(horaChileStr()), 30000);
        return () => clearInterval(t);
    }, []);

    // Auto-refresco de las clases: 45s, pausado con la pestaña oculta (no gastamos
    // cuota de la BD si el admin no está mirando), igual que el panel ≥768px.
    useEffect(() => {
        const t = setInterval(() => { if (!document.hidden) cargarClases(); }, 45000);
        const alVolver = () => { if (!document.hidden) cargarClases(); };
        document.addEventListener('visibilitychange', alVolver);
        return () => {
            clearInterval(t);
            document.removeEventListener('visibilitychange', alVolver);
        };
    }, [cargarClases]);

    // La franja por defecto es la del reloj; si el admin elige otra, se respeta.
    const franjaReloj = franjaActual(ahora);
    const franjaActiva = franja || franjaReloj;
    const grupos = agruparPorFranja(clases);
    const visibles = grupos[franjaActiva] || [];
    const resumen = resumenFranja(visibles);
    const indiceCursando = franjaActiva === franjaReloj ? claseEnCurso(visibles, ahora) : -1;

    // ── E. Buscador de alumnos (ficha rápida) ───────────────────────────────
    const [buscador, setBuscador] = useState(false);
    const [consulta, setConsulta] = useState('');
    const [resultados, setResultados] = useState([]);
    const [buscando, setBuscando] = useState(false);
    const [errorBusqueda, setErrorBusqueda] = useState('');
    // Alto REAL del header del Layout (incluye la safe-area del iPhone): la pantalla
    // completa se ancla debajo para que el input no quede nunca escondido.
    const [altoHeader, setAltoHeader] = useState(0);

    useEffect(() => {
        if (!buscador) return;
        const medir = () => {
            const header = document.querySelector('header');
            setAltoHeader(header ? Math.round(header.getBoundingClientRect().height) : 0);
        };
        medir();
        window.addEventListener('resize', medir);
        window.addEventListener('orientationchange', medir);
        return () => {
            window.removeEventListener('resize', medir);
            window.removeEventListener('orientationchange', medir);
        };
    }, [buscador]);

    // Búsqueda con retardo (350 ms): no se dispara una consulta por cada tecla. Se pide
    // `con_membresia=true` para que el MISMO listado de Alumnos traiga plan, vencimiento,
    // créditos y última visita (extras opt-in: el resto del panel no los paga).
    useEffect(() => {
        const texto = consulta.trim();
        if (!buscador || texto.length < 2) {
            setResultados([]);
            setBuscando(false);
            setErrorBusqueda('');
            return undefined;
        }
        setBuscando(true);
        const t = setTimeout(async () => {
            try {
                const res = await api.get('/api/v1/usuarios/', {
                    params: { rol: 'alumno', buscar: texto, limit: 20, con_membresia: true },
                });
                setResultados(Array.isArray(res.data) ? res.data : []);
                setErrorBusqueda('');
            } catch (err) {
                setResultados([]);
                setErrorBusqueda(err.response?.data?.detail || 'No se pudo buscar alumnos');
            }
            setBuscando(false);
        }, 350);
        return () => clearTimeout(t);
    }, [consulta, buscador]);

    const avisar = (texto, error = false) => {
        setToast({ texto, error });
        setTimeout(() => setToast(null), 2600);
    };

    // ── C. Revisión de vouchers ─────────────────────────────────────────────
    // Aprobar/rechazar van al MISMO endpoint que usa la pantalla Pendientes; el backend
    // resuelve la suscripción, los créditos y la caja del día por su cuenta.
    const aprobar = async () => {
        if (!revision || procesando) return;
        setProcesando(true);
        try {
            await api.put(`/api/v1/solicitudes/${revision.id}/aprobar`);
            avisar(`Plan activado para ${revision.alumno_nombre}`);
            setRevision(null);
            setMotivoRechazo('');
            // El voucher aprobado cambia la caja del día y los pendientes: se recargan.
            cargarKpis();
        } catch (err) {
            avisar(err.response?.data?.detail || 'No se pudo aprobar la solicitud', true);
        }
        setProcesando(false);
    };

    const rechazar = async () => {
        if (!revision || procesando) return;
        const motivo = motivoRechazo.trim();
        if (!motivo) {
            avisar('Escribe el motivo del rechazo', true);
            return;
        }
        setProcesando(true);
        try {
            await api.put(`/api/v1/solicitudes/${revision.id}/rechazar`,
                null, { params: { motivo } });
            avisar(`Comprobante de ${revision.alumno_nombre} rechazado`);
            setRevision(null);
            setMotivoRechazo('');
            cargarKpis();
        } catch (err) {
            avisar(err.response?.data?.detail || 'No se pudo rechazar la solicitud', true);
        }
        setProcesando(false);
    };

    // ── D. Marcar asistencia ────────────────────────────────────────────────
    const abrirRoster = async (clase) => {
        setRoster({ clase, reservas: [], marcada: false });
        setMarcados({});
        setRosterCargando(true);
        try {
            const res = await api.get(`/api/v1/asistencia/clases/${clase.id}/alumnos`);
            const reservas = res.data?.reservas || [];
            const marcada = Boolean(res.data?.marcada);
            setRoster({ clase, reservas, marcada });
            // Igual que el panel ≥768px: si la clase YA fue marcada se muestran los
            // valores guardados; si no, NINGUNO pre-marcado (evita confirmar todo por error).
            const inicial = {};
            reservas.forEach((r) => { inicial[r.reserva_id] = marcada ? Boolean(r.asistio) : false; });
            setMarcados(inicial);
        } catch (err) {
            avisar(err.response?.data?.detail || 'No se pudo abrir la clase', true);
            setRoster(null);
        }
        setRosterCargando(false);
    };

    const guardarAsistencia = async () => {
        if (!roster || guardando) return;
        const asistencias = roster.reservas.map((r) => ({
            reserva_id: r.reserva_id,
            asistio: Boolean(marcados[r.reserva_id]),
        }));
        if (!asistencias.length) {
            avisar('La clase no tiene reservas activas', true);
            return;
        }
        setGuardando(true);
        try {
            await api.post(`/api/v1/asistencia/clases/${roster.clase.id}/confirmar`, { asistencias });
            const cuantos = asistencias.filter((a) => a.asistio).length;
            avisar(`Asistencia guardada: ${cuantos} en ${roster.clase.disciplina_nombre} ${horaCorta(roster.clase.hora_inicio)}`);
            setRoster(null);
            cargarClases();
        } catch (err) {
            avisar(err.response?.data?.detail || 'No se pudo guardar la asistencia', true);
        }
        setGuardando(false);
    };

    const alternar = (reservaId) => {
        setMarcados((prev) => ({ ...prev, [reservaId]: !prev[reservaId] }));
    };

    // "En revisión": abre la hoja con el comprobante del voucher (sin salir del Inicio).
    const abrirRevision = (solicitud) => {
        setRevision(solicitud || vouchers[0] || null);
        setMotivoRechazo('');
    };
    const cerrarRevision = () => {
        setRevision(null);
        setAmpliado(false);
        setMotivoRechazo('');
    };
    // Buscador: pantalla completa con ficha rápida (sin salir del Inicio).
    const abrirBuscador = () => {
        setBuscador(true);
        setErrorBusqueda('');
    };
    const cerrarBuscador = () => {
        setBuscador(false);
        setConsulta('');
    };

    // ── F. "Alumnos nuevos y en prueba" (tarjeta + pantalla completa) ────────
    // Dos listados REALES: los que están EN PRUEBA (con su estado 🟡/🔵 y el correo
    // manual) y los dados de alta en el mes en curso. Se piden juntos para que la
    // tarjeta tenga su número y la pantalla abra con datos; al abrir se refrescan.
    const [tarjeta, setTarjeta] = useState(false);       // pantalla abierta
    const [enPrueba, setEnPrueba] = useState([]);
    const [nuevosMes, setNuevosMes] = useState([]);
    const [tarjetaCargando, setTarjetaCargando] = useState(true);
    const [errorPrueba, setErrorPrueba] = useState('');
    const [errorNuevos, setErrorNuevos] = useState('');
    // Vista previa del correo manual: { alumno, cargando, preview, error, enviando }.
    const [correo, setCorreo] = useState(null);

    const cargarTarjeta = useCallback(async () => {
        setTarjetaCargando(true);
        const [rPrueba, rNuevos] = await Promise.allSettled([
            api.get('/api/v1/admin/alumnos-prueba'),
            api.get('/api/v1/admin/alumnos-nuevos'),
        ]);
        // Error POR SECCIÓN: si una falla, la otra se muestra igual (y el motivo va
        // a la vista, nunca un 0 disfrazado de dato).
        const motivo = (r) => r.reason?.response?.data?.detail
            || (r.reason?.response?.status ? `HTTP ${r.reason.response.status}` : r.reason?.message)
            || 'No se pudo cargar';

        if (rPrueba.status === 'fulfilled') {
            setEnPrueba(Array.isArray(rPrueba.value.data?.alumnos) ? rPrueba.value.data.alumnos : []);
            setErrorPrueba('');
        } else {
            setEnPrueba([]);
            setErrorPrueba(motivo(rPrueba));
        }

        if (rNuevos.status === 'fulfilled') {
            setNuevosMes(Array.isArray(rNuevos.value.data?.alumnos) ? rNuevos.value.data.alumnos : []);
            setErrorNuevos('');
        } else {
            setNuevosMes([]);
            setErrorNuevos(motivo(rNuevos));
        }
        setTarjetaCargando(false);
    }, []);

    useEffect(() => {
        cargarTarjeta();
    }, [cargarTarjeta]);

    const abrirTarjeta = () => {
        setTarjeta(true);
        cargarTarjeta();
    };
    const cerrarTarjeta = () => {
        setTarjeta(false);
        setCorreo(null);
    };

    // Vista previa NO editable: el correo lo arma el backend con los datos reales
    // (la misma función que usa el envío, así lo que se ve es lo que sale).
    const abrirCorreo = async (alumno) => {
        setCorreo({ alumno, cargando: true, preview: null, error: '', enviando: false });
        try {
            const res = await api.get(
                `/api/v1/admin/alumnos-prueba/${alumno.id}/invitacion/preview`);
            setCorreo({ alumno, cargando: false, preview: res.data, error: '', enviando: false });
        } catch (err) {
            setCorreo({
                alumno, cargando: false, preview: null, enviando: false,
                error: err.response?.data?.detail || 'No se pudo armar el correo',
            });
        }
    };

    const enviarCorreo = async () => {
        if (!correo?.alumno || correo.enviando) return;
        setCorreo((c) => ({ ...c, enviando: true }));
        try {
            const { data } = await api.post(
                `/api/v1/admin/alumnos-prueba/${correo.alumno.id}/invitacion`);
            if (data?.exito) {
                // La fila pasa a "Correo enviado hace X" con la hora REAL del envío.
                setEnPrueba((prev) => prev.map((a) => (a.id === correo.alumno.id
                    ? { ...a, ultimo_envio: data.enviado_en || a.ultimo_envio } : a)));
                avisar(data.ya_enviado
                    ? 'Ese correo ya se había enviado hoy'
                    : `Correo enviado a ${correo.alumno.nombre}`);
            } else {
                avisar(data?.detalle_error || 'No se pudo enviar el correo', true);
            }
            setCorreo(null);
        } catch (err) {
            avisar(err.response?.data?.detail || 'No se pudo enviar el correo', true);
            setCorreo((c) => (c ? { ...c, enviando: false } : c));
        }
    };

    /** Tocar un nombre lleva a la FICHA del alumno (Historial), igual que el buscador. */
    const irAFicha = (alumnoId) => navigate(`/admin/alumnos/${alumnoId}/historial`);

    // ── G. "Pedidos listos para entrega": pantalla + aviso MANUAL al comprador ─
    const hayPedidos = pedidos.length > 0;

    const abrirPedidos = async () => {
        setListaPedidos(true);
        setPedidosCargando(true);
        const [rPedidos, rTraza] = await Promise.allSettled([
            api.get('/api/v1/pedidos', { params: { estado: 'validado' } }),
            // Traza de los avisos manuales (por PEDIDO): alimenta el "Informado hace X"
            // de todas las filas con UNA sola llamada.
            api.get('/api/v1/auditoria', {
                params: { accion: 'EMAIL_MANUAL', entidad: 'pedido', limit: 200 },
            }),
        ]);
        if (rPedidos.status === 'fulfilled') {
            setPedidos((Array.isArray(rPedidos.value.data) ? rPedidos.value.data : [])
                .filter(esListoParaEntrega));
            setPedidosError('');
        } else {
            setPedidos([]);
            setPedidosError(motivoError(rPedidos));
        }
        setInformados(rTraza.status === 'fulfilled' ? mapaInformados(rTraza.value.data) : {});
        setPedidosCargando(false);
    };

    const cerrarPedidos = () => {
        setListaPedidos(false);
        setAviso(null);
    };

    /** Tocar un pedido lleva a la pantalla de PEDIDOS (no a la ficha del alumno). */
    const irAPedido = () => navigate('/admin/pedidos');

    // Vista previa NO editable del aviso de retiro: el HTML lo arma el backend con los
    // datos reales del pedido (misma función que el envío). Es un correo ADICIONAL a la
    // campana automática `pedido_validado`, no la reemplaza ni la duplica.
    //
    // La petición va CON PLAZO y siempre termina en un desenlace: si el backend no
    // responde a tiempo, la hoja muestra el motivo + "Reintentar" (nunca se queda en
    // "Armando el correo…"). Es un GET sin efectos secundarios: reintentar es seguro.
    const abrirAviso = async (pedido) => {
        setAviso({ pedido, cargando: true, preview: null, error: '', enviando: false });
        const res = await cargarPreviewAviso(
            () => api.get(`/api/v1/pedidos/${pedido.id}/aviso-retiro/preview`));
        setAviso({
            pedido, cargando: false, enviando: false,
            preview: res.preview, error: res.error,
        });
    };

    const enviarAviso = async () => {
        if (!aviso?.pedido || aviso.enviando) return;
        setAviso((a) => ({ ...a, enviando: true }));
        try {
            const { data } = await api.post(`/api/v1/pedidos/${aviso.pedido.id}/aviso-retiro`);
            if (data?.exito) {
                if (data.informado_en) {
                    setInformados((prev) => ({ ...prev, [aviso.pedido.id]: data.informado_en }));
                }
                avisar(data.ya_enviado
                    ? 'Ese aviso ya se había enviado hoy'
                    : `Aviso enviado a ${aviso.pedido.alumno_nombre || 'el comprador'}`);
            } else {
                avisar(data?.detalle_error || 'No se pudo enviar el aviso', true);
            }
            setAviso(null);
        } catch (err) {
            avisar(err.response?.data?.detail || 'No se pudo enviar el aviso', true);
            setAviso((a) => (a ? { ...a, enviando: false } : a));
        }
    };

    return (
        <div className="ub-admin" data-testid="admin-inicio-movil">
            <div className="col">
                <p className="note" style={{ marginTop: 0, textAlign: 'left' }}>
                    {fechaCorta()} · resumen del día
                </p>

                {/* ── A. KPIs ─────────────────────────────────────────────── */}
                <section className="kpis" aria-label="Resumen del día">
                    <Kpi
                        clase="k-activos" icono="users" label="Alumnos activos"
                        valor={kpis.activos} error={errores.activos} cargando={cargando}
                        sub={kpis.nuevosMes != null
                            ? <><em>+{kpis.nuevosMes}</em> nuevos este mes</>
                            : 'con plan vigente'}
                        onClick={() => navigate('/admin/reportes')}
                    />
                    <Kpi
                        clase="k-venc" icono="clock" label="Vencen en 5 días"
                        valor={kpis.vencen} error={errores.vencen} cargando={cargando}
                        sub="membresías por vencer"
                        onClick={() => navigate('/admin/fidelizacion')}
                    />
                    <Kpi
                        clase={`k-vouch${hayVouchers ? ' alive' : ''}`}
                        icono="voucher" label="Vouchers por aprobar"
                        valor={errores.vouchers ? null : vouchers.length}
                        error={errores.vouchers} cargando={cargando}
                        sub={hayVouchers ? <em>Toca para revisar</em> : 'Todo al día'}
                        pulso={hayVouchers}
                        onClick={abrirRevision}
                    />
                    <Kpi
                        clase="k-caja" icono="caja" label="Ingresos de hoy" dinero
                        valor={kpis.caja} error={errores.caja} cargando={cargando}
                        sub={kpis.pagos != null
                            ? <><em>{kpis.pagos} {kpis.pagos === 1 ? 'pago' : 'pagos'}</em> registrados</>
                            : 'caja del día'}
                        onClick={() => navigate('/admin/reportes')}
                    />
                    {/* Quinta tarjeta (ancho completo): abre la pantalla con los dos
                        listados. El número es el de los que están EN PRUEBA; el pie
                        reusa el "+N nuevos este mes" que ya trae /reportes/. */}
                    <Kpi
                        clase="k-prueba wide" icono="users" label="Alumnos nuevos y en prueba"
                        valor={errorPrueba ? null : enPrueba.length}
                        error={errorPrueba} cargando={tarjetaCargando}
                        sub={kpis.nuevosMes != null
                            ? <><em>+{kpis.nuevosMes}</em> nuevos este mes</>
                            : 'toca para ver el detalle'}
                        chevron onClick={abrirTarjeta} testid="kpi-prueba"
                    />
                </section>

                {/* ── B. Accesos rápidos ──────────────────────────────────── */}
                <nav className="apps" aria-label="Accesos rápidos">
                    <button type="button" className="app a-search" onClick={abrirBuscador}>
                        <span className="ico"><Icono nombre="search" /></span>Alumnos
                    </button>
                    <button type="button" className="app a-fid"
                        onClick={() => navigate('/admin/fidelizacion')}>
                        <span className="ico"><Icono nombre="heart" /></span>Fidelización
                    </button>
                    <button type="button" className={`app a-baz${hayPedidos ? ' alive' : ''}`}
                        onClick={abrirPedidos} data-testid="app-bazar"
                        aria-label={hayPedidos
                            ? `Bazar: ${pedidos.length} ${pedidos.length === 1 ? 'pedido listo' : 'pedidos listos'} para entrega`
                            : 'Bazar'}>
                        {/* Mismo pulso que "Vouchers por aprobar" + la cantidad de
                            pedidos validados que aún nadie retiró. */}
                        {hayPedidos && <span className="pulse" />}
                        <span className="ico">
                            <Icono nombre="cart" />
                            {hayPedidos && <span className="tag">{pedidos.length}</span>}
                        </span>Bazar
                    </button>
                </nav>

                {/* ── C. "En revisión": vouchers por aprobar ───────────────── */}
                <section className="card" aria-labelledby="ub-revision" data-testid="admin-revision">
                    <div className="card-head">
                        <h2 id="ub-revision">
                            En revisión
                            <span className={`badge${hayVouchers ? '' : ' ok'}`}>
                                {errores.vouchers ? 's/d' : vouchers.length}
                            </span>
                        </h2>
                        {vouchers.length > 2 && (
                            <button type="button" className="link"
                                onClick={() => navigate('/admin/alumnos-pendientes')}>
                                Ver los {vouchers.length}
                            </button>
                        )}
                    </div>

                    {errores.vouchers ? (
                        <p className="empty-line" role="alert">⚠️ {errores.vouchers}</p>
                    ) : vouchers.length === 0 ? (
                        <p className="empty-line">
                            <Icono nombre="check" />
                            Todo al día. Los comprobantes nuevos aparecen acá.
                        </p>
                    ) : (
                        vouchers.slice(0, 2).map((v) => (
                            <button key={v.id} type="button" className="vrow"
                                onClick={() => abrirRevision(v)}
                                aria-label={`Revisar comprobante de ${v.alumno_nombre}`}>
                                <span className="mini" aria-hidden="true">
                                    <i /><i /><i /><i />
                                </span>
                                <span>
                                    <span className="n" style={{ display: 'block' }}>{v.alumno_nombre}</span>
                                    <span className="p" style={{ display: 'block' }}>
                                        {v.plan_nombre} · {haceCuanto(v.created_at)}
                                    </span>
                                </span>
                                <span className="m">
                                    <b className="num">{precioCLP(v.precio_final ?? v.plan_precio)}</b>
                                    <span>Revisar</span>
                                </span>
                            </button>
                        ))
                    )}
                </section>

                {/* ── D. "Asistencia de hoy" por franja ────────────────────── */}
                <section className="card att" aria-labelledby="ub-asistencia" data-testid="admin-asistencia">
                    <div className="card-head">
                        <h2 id="ub-asistencia">Asistencia de hoy</h2>
                        <span className="live">Ahora · {ahora || '--:--'}</span>
                    </div>

                    <div className="seg" role="tablist" aria-label="Franja del día">
                        {FRANJAS.map((f) => (
                            <button key={f.id} type="button" role="tab"
                                aria-selected={f.id === franjaActiva}
                                onClick={() => setFranja(f.id)}>
                                {f.label}
                                {f.id === franjaReloj && <span className="now-dot" title="Franja actual" />}
                            </button>
                        ))}
                    </div>

                    <div className="slot-sum">
                        <span>
                            {resumen.clases} {resumen.clases === 1 ? 'clase' : 'clases'}
                            {resumen.desde != null
                                ? ` · ${dosDigitos(resumen.desde)}:00 a ${dosDigitos(Math.min(resumen.hasta + 1, 24))}:00`
                                : ''}
                        </span>
                        <span>Ocupación {resumen.ocupacion}%</span>
                    </div>

                    {clasesError ? (
                        <p className="empty-line" role="alert">
                            ⚠️ {clasesError}{' '}
                            <button type="button" className="link" onClick={cargarClases}>Reintentar</button>
                        </p>
                    ) : (!clases.length && clasesCargando) ? (
                        <p className="empty-line">Cargando las clases de hoy…</p>
                    ) : visibles.length === 0 ? (
                        <p className="empty-line">No hay clases en esta franja.</p>
                    ) : (
                        visibles.map((c, i) => {
                            const oc = ocupacion(c.reservas_count, c.cupo_maximo);
                            const hecha = estaMarcada(c);
                            return (
                                <div key={c.id} className={`class${i === indiceCursando ? ' current' : ''}`}>
                                    <div className="hour">{horaCorta(c.hora_inicio)}</div>
                                    <div style={{ minWidth: 0 }}>
                                        <div className="name">
                                            {c.disciplina_nombre}{' '}
                                            <span className={c.coach ? '' : 'nocoach'}>
                                                · {c.coach || 'Sin coach'}
                                            </span>
                                        </div>
                                        <div className="sub">
                                            {c.reservas_count} de {c.cupo_maximo} cupos · {oc.pct}%
                                        </div>
                                        <div className="bar">
                                            <i className={oc.nivel}
                                                style={{ width: `${Math.min(oc.pct, 100)}%` }} />
                                        </div>
                                    </div>
                                    <button type="button" className={`att-btn${hecha ? ' done' : ''}`}
                                        onClick={() => abrirRoster(c)}
                                        aria-label={`Marcar asistencia de ${c.disciplina_nombre} ${horaCorta(c.hora_inicio)}`}>
                                        {hecha ? <><Icono nombre="check" />{c.reservas_count} ok</> : 'Marcar'}
                                    </button>
                                </div>
                            );
                        })
                    )}
                </section>
            </div>

            {/* ── Capas del móvil (hojas, comprobante, toast y pantallas) ──
                Van por PORTAL a <body>: dentro de `<main>` el contexto de apilado
                del Layout (`relative z-10`) queda por debajo del header (z-30) y el
                buscador aparecía detrás del header. Ver `CapaMovil`. */}
            <CapaMovil top={altoHeader}>
            {/* ── Hoja inferior: revisar el comprobante (C) ─────────────── */}
            {revision && (
                <>
                    <div className="scrim" onClick={cerrarRevision} />
                    <section className="sheet" aria-label="Revisar comprobante">
                        <div className="sheet-grab" />
                        <div className="sheet-head">
                            <div>
                                <h3>Revisar comprobante</h3>
                                <small>
                                    {revision.alumno_nombre} · {revision.plan_nombre}
                                    {revision.descuento_pct ? ` · -${revision.descuento_pct}%` : ''}
                                </small>
                            </div>
                            <button type="button" className="close-x" onClick={cerrarRevision}
                                aria-label="Cerrar">✕</button>
                        </div>
                        <div className="sheet-body">
                            {voucherDoc.preview.loading ? (
                                <p className="empty-line">Cargando el comprobante…</p>
                            ) : voucherDoc.preview.error ? (
                                <p className="empty-line" role="alert">⚠️ {voucherDoc.preview.error}</p>
                            ) : voucherDoc.preview.blobUrl ? (
                                <div className="doc" role="button" tabIndex={0}
                                    onClick={() => setAmpliado(true)}
                                    onKeyDown={(e) => { if (e.key === 'Enter') setAmpliado(true); }}>
                                    {voucherDoc.preview.mime.includes('pdf')
                                        ? <iframe src={voucherDoc.preview.blobUrl} title="Comprobante PDF" />
                                        : <img src={voucherDoc.preview.blobUrl} alt="Comprobante de pago" />}
                                </div>
                            ) : null}

                            {/* Resumen del cobro (lo que ya trae la solicitud pendiente). */}
                            <div className="receipt" role="button" tabIndex={0}
                                onClick={() => setAmpliado(true)}
                                onKeyDown={(e) => { if (e.key === 'Enter') setAmpliado(true); }}>
                                <span className="zoom">Ampliar</span>
                                <div className="r-top">
                                    <span className="tick"><Icono nombre="check" /></span>
                                    <div>
                                        <b>Comprobante de pago</b>
                                        <small>{revision.alumno_nombre} · {revision.plan_nombre}</small>
                                    </div>
                                </div>
                                <div className="r-amt">
                                    {precioCLP(revision.precio_final ?? revision.plan_precio)}
                                </div>
                                <dl>
                                    <dt>Plan</dt>
                                    <dd>{revision.plan_nombre}</dd>
                                    <dt>Precio de lista</dt>
                                    <dd>{precioCLP(revision.plan_precio)}</dd>
                                    {revision.descuento_pct
                                        ? (<><dt>Descuento</dt><dd>-{revision.descuento_pct}%</dd></>)
                                        : null}
                                    <dt>Solicitud</dt>
                                    <dd>{haceCuanto(revision.created_at)}</dd>
                                </dl>
                            </div>

                            <label className="search" style={{ height: 46, marginTop: 10 }}>
                                <input value={motivoRechazo}
                                    onChange={(e) => setMotivoRechazo(e.target.value)}
                                    placeholder="Motivo del rechazo (si rechazas)" />
                            </label>
                        </div>
                        <div className="sheet-foot">
                            <button type="button" className="btn ghost" onClick={rechazar}
                                disabled={procesando || !motivoRechazo.trim()}>
                                Rechazar
                            </button>
                            <button type="button" className="btn primary" onClick={aprobar}
                                disabled={procesando}>
                                {procesando ? 'Procesando…' : 'Activar plan'}
                            </button>
                        </div>
                    </section>
                </>
            )}

            {/* Comprobante a pantalla completa (tocar para cerrar). */}
            {ampliado && voucherDoc.preview.blobUrl && (
                <div className="light" onClick={() => setAmpliado(false)}>
                    {voucherDoc.preview.mime.includes('pdf') ? (
                        <iframe src={voucherDoc.preview.blobUrl} title="Comprobante PDF ampliado"
                            style={{ width: '100%', height: '80dvh', border: 0, background: '#fff' }} />
                    ) : (
                        <img src={voucherDoc.preview.blobUrl} alt="Comprobante ampliado"
                            style={{ width: '100%', borderRadius: 12 }} />
                    )}
                </div>
            )}

            {/* ── Hoja inferior: roster de la clase (D) ─────────────────── */}
            {roster && (
                <>
                    <div className="scrim" onClick={() => setRoster(null)} />
                    <section className="sheet" aria-label="Marcar asistencia">
                        <div className="sheet-grab" />
                        <div className="sheet-head">
                            <div>
                                <h3>
                                    {roster.clase.disciplina_nombre} {horaCorta(roster.clase.hora_inicio)}
                                </h3>
                                <small>
                                    {roster.clase.reservas_count}{' '}
                                    {roster.clase.reservas_count === 1 ? 'reserva' : 'reservas'}
                                    {roster.marcada ? ' · ya marcada' : ''}
                                    {' · '}{roster.clase.coach || 'sin coach'}
                                </small>
                            </div>
                            <button type="button" className="close-x" onClick={() => setRoster(null)}
                                aria-label="Cerrar">✕</button>
                        </div>
                        <div className="sheet-body roll">
                            {rosterCargando ? (
                                <p className="empty-line">Cargando el roster…</p>
                            ) : roster.reservas.length === 0 ? (
                                <p className="empty-line">Esta clase no tiene reservas activas.</p>
                            ) : (
                                roster.reservas.map((r) => (
                                    <label key={r.reserva_id}>
                                        <input type="checkbox"
                                            checked={Boolean(marcados[r.reserva_id])}
                                            onChange={() => alternar(r.reserva_id)} />
                                        {r.nombre}
                                    </label>
                                ))
                            )}
                        </div>
                        <div className="sheet-foot una">
                            <button type="button" className="btn primary" onClick={guardarAsistencia}
                                disabled={guardando || rosterCargando || roster.reservas.length === 0}>
                                {guardando ? 'Guardando…' : 'Guardar asistencia'}
                            </button>
                        </div>
                    </section>
                </>
            )}

            {toast && (
                <div className={`toast${toast.error ? ' error' : ''}`} role="status">{toast.texto}</div>
            )}

            {/* ── Pantalla completa: buscador de alumnos (E) ─────────────── */}
            {buscador && (
                <section className="screen" aria-label="Buscar alumno">
                    <div className="s-head">
                        <button type="button" className="icon-btn" onClick={cerrarBuscador}
                            aria-label="Volver">←</button>
                        <label className="search">
                            <Icono nombre="search" />
                            <input type="search" autoFocus value={consulta}
                                onChange={(e) => setConsulta(e.target.value)}
                                placeholder="Nombre o correo del alumno"
                                aria-label="Buscar alumno" />
                        </label>
                    </div>

                    <div className="results">
                        {errorBusqueda ? (
                            <p className="empty-line" role="alert">⚠️ {errorBusqueda}</p>
                        ) : consulta.trim().length < 2 ? (
                            <p className="hint">
                                Escribe al menos 2 letras del nombre o del correo.
                            </p>
                        ) : buscando ? (
                            <p className="hint">Buscando…</p>
                        ) : resultados.length === 0 ? (
                            <p className="hint">Sin resultados para «{consulta.trim()}».</p>
                        ) : (
                            resultados.map((a) => {
                                const m = a.membresia || null;
                                const est = estadoAlumno(m);
                                const wa = enlaceWhatsapp(
                                    a.telefono,
                                    `Hola ${String(a.nombre || '').split(' ')[0]}, te escribo de Urban Box.`,
                                );
                                return (
                                    <article className="student" key={a.id}>
                                        <div className="st-top">
                                            <span className="avatar">{iniciales(a.nombre)}</span>
                                            <div style={{ minWidth: 0 }}>
                                                <div className="st-name">{a.nombre}</div>
                                                <div className="st-plan">
                                                    {m?.plan_nombre || 'Sin plan activo'}
                                                </div>
                                            </div>
                                            <span className={`state ${est.clase}`}>{est.texto}</span>
                                        </div>
                                        <div className="st-grid">
                                            <div>
                                                <small>Vence</small>
                                                <b>{fechaVencimiento(m?.fecha_expiracion)}</b>
                                            </div>
                                            <div>
                                                <small>Créditos</small>
                                                <b>{rotuloCreditos(m?.es_ilimitado, m?.creditos_disponibles)}</b>
                                            </div>
                                            <div>
                                                <small>Última</small>
                                                <b>{ultimaVisita(a.ultima_asistencia)}</b>
                                            </div>
                                        </div>
                                        <div className={`st-actions${wa ? '' : ' una'}`}>
                                            {/* Sin teléfono cargado el botón NO se dibuja
                                                (no hay a dónde mandar el WhatsApp). */}
                                            {wa && (
                                                <a className="btn wa wa-link" href={wa}
                                                    target="_blank" rel="noreferrer">
                                                    WhatsApp
                                                </a>
                                            )}
                                            <button type="button" className="btn soft"
                                                onClick={() => navigate(`/admin/alumnos/${a.id}/historial`)}>
                                                Ver perfil
                                            </button>
                                        </div>
                                    </article>
                                );
                            })
                        )}
                    </div>
                </section>
            )}
            {/* ── Pantalla completa: alumnos nuevos y en prueba (F) ──────── */}
            {tarjeta && (
                <section className="screen" aria-label="Alumnos nuevos y en prueba">
                    <div className="s-head">
                        <button type="button" className="icon-btn" onClick={cerrarTarjeta}
                            aria-label="Volver">←</button>
                        <div className="s-title">
                            <h3>Alumnos nuevos y en prueba</h3>
                            <small>
                                {textoEnPrueba(enPrueba.length)}
                                {nuevosMes.length ? ` · ${nuevosMes.length} nuevos del mes` : ''}
                            </small>
                        </div>
                    </div>

                    <div className="results">
                        <h4 className="sec">En prueba</h4>
                        {errorPrueba ? (
                            <p className="empty-line" role="alert">⚠️ {errorPrueba}</p>
                        ) : tarjetaCargando ? (
                            <p className="hint">Cargando…</p>
                        ) : enPrueba.length === 0 ? (
                            <p className="hint">Nadie está en prueba ahora mismo.</p>
                        ) : enPrueba.map((a) => {
                            const tono = tonoEstadoPrueba(a.estado);
                            return (
                                <article className="prow" key={a.id}>
                                    <button type="button" className="pr-head"
                                        onClick={() => irAFicha(a.id)}>
                                        <span className="avatar">{iniciales(a.nombre)}</span>
                                        <span className="pr-name">{a.nombre}</span>
                                        <span className="pr-go" aria-hidden="true">›</span>
                                    </button>
                                    <p className={`pr-estado ${tono.clase}`}>
                                        <span aria-hidden="true">{tono.icono}</span>{' '}
                                        {textoEstadoPrueba(a.estado, a.dias_inscrito)}
                                    </p>
                                    <div className="pr-foot">
                                        <button type="button" className="btn soft small"
                                            onClick={() => abrirCorreo(a)}>
                                            Enviar correo
                                        </button>
                                        {/* Envío MANUAL registrado: la fila lo muestra. */}
                                        {a.ultimo_envio && (
                                            <span className="pr-note">
                                                Correo enviado {textoHace(a.ultimo_envio)}
                                            </span>
                                        )}
                                    </div>
                                </article>
                            );
                        })}

                        <h4 className="sec">Nuevos del mes</h4>
                        {errorNuevos ? (
                            <p className="empty-line" role="alert">⚠️ {errorNuevos}</p>
                        ) : tarjetaCargando ? (
                            <p className="hint">Cargando…</p>
                        ) : nuevosMes.length === 0 ? (
                            <p className="hint">Todavía no hay altas este mes.</p>
                        ) : nuevosMes.map((a) => (
                            <button type="button" className="nrow" key={a.id}
                                onClick={() => irAFicha(a.id)}>
                                <span className="avatar">{iniciales(a.nombre)}</span>
                                <span className="n-name">{a.nombre}</span>
                                <span className="n-fecha">{textoAlta(a.fecha_alta)}</span>
                            </button>
                        ))}
                    </div>
                </section>
            )}
            {/* ── Hoja inferior: vista previa del correo manual (F) ───────── */}
            {correo && (
                <>
                    <div className="scrim" onClick={() => setCorreo(null)} />
                    <section className="sheet" aria-label="Vista previa del correo">
                        <div className="sheet-grab" />
                        <div className="sheet-head">
                            <div>
                                <h3>Vista previa del correo</h3>
                                <small>
                                    {correo.alumno?.nombre}
                                    {correo.preview?.destinatario ? ` · ${correo.preview.destinatario}` : ''}
                                </small>
                            </div>
                            <button type="button" className="close-x"
                                onClick={() => setCorreo(null)} aria-label="Cerrar">✕</button>
                        </div>
                        <div className="sheet-body">
                            {correo.cargando ? (
                                <p className="empty-line">Armando el correo…</p>
                            ) : (correo.error || !correo.preview) ? (
                                <p className="empty-line" role="alert">
                                    ⚠️ {correo.error || 'No se pudo armar el correo'}
                                </p>
                            ) : (
                                <>
                                    <div className="mail-meta">
                                        <small>Asunto</small>
                                        <b>{correo.preview.asunto}</b>
                                    </div>
                                    {/* El HTML lo renderiza el backend: se muestra tal cual,
                                        sin poder editarlo y sin ejecutar nada (sandbox=""). */}
                                    <iframe className="mail-doc" title="Vista previa del correo"
                                        sandbox="" srcDoc={correo.preview.html} />
                                    <p className="note">
                                        El mensaje lo arma Urban Box con los datos del alumno:
                                        se envía tal cual.
                                    </p>
                                </>
                            )}
                        </div>
                        <div className="sheet-foot una">
                            <button type="button" className="btn primary" onClick={enviarCorreo}
                                disabled={correo.cargando || Boolean(correo.error)
                                    || !correo.preview || correo.enviando}>
                                {correo.enviando ? 'Enviando…' : 'Enviar'}
                            </button>
                        </div>
                    </section>
                </>
            )}
            {/* ── Pantalla completa: pedidos listos para entrega (G) ─────── */}
            {listaPedidos && (
                <section className="screen" aria-label="Pedidos listos para entrega">
                    <div className="s-head">
                        <button type="button" className="icon-btn" onClick={cerrarPedidos}
                            aria-label="Volver">←</button>
                        <div className="s-title">
                            <h3>Pedidos listos para entrega</h3>
                            <small>
                                {pedidos.length} {pedidos.length === 1
                                    ? 'pedido esperando retiro'
                                    : 'pedidos esperando retiro'}
                            </small>
                        </div>
                    </div>

                    <div className="results">
                        {pedidosError ? (
                            <p className="empty-line" role="alert">⚠️ {pedidosError}</p>
                        ) : pedidosCargando ? (
                            <p className="hint">Cargando…</p>
                        ) : pedidos.length === 0 ? (
                            <p className="hint">No hay pedidos esperando retiro.</p>
                        ) : pedidos.map((p) => (
                            <article className="orow" key={p.id}>
                                {/* Tocar el pedido abre la pantalla de Pedidos (donde se
                                    gestiona y se entrega), no la ficha del alumno. */}
                                <button type="button" className="or-head" onClick={irAPedido}>
                                    <span className="o-name">{p.alumno_nombre || 'Alumno'}</span>
                                    <span className="pr-go" aria-hidden="true">›</span>
                                </button>
                                <p className="o-prod">{textoProducto(p)}</p>
                                <div className="o-code">
                                    <small>Código de retiro</small>
                                    <b>{codigoRetiro(p)}</b>
                                </div>
                                <p className="o-espera">{textoEspera(p)}</p>
                                <div className="pr-foot">
                                    <button type="button" className="btn soft small"
                                        onClick={() => abrirAviso(p)}>
                                        Avisar al comprador
                                    </button>
                                    {informados[p.id] && (
                                        <span className="pr-note">
                                            {textoInformado(informados[p.id])}
                                        </span>
                                    )}
                                </div>
                            </article>
                        ))}
                    </div>
                </section>
            )}
            {/* ── Hoja inferior: vista previa del aviso de retiro (G) ─────── */}
            {aviso && (
                <>
                    <div className="scrim" onClick={() => setAviso(null)} />
                    <section className="sheet" aria-label="Vista previa del aviso">
                        <div className="sheet-grab" />
                        <div className="sheet-head">
                            <div>
                                <h3>Vista previa del aviso</h3>
                                <small>
                                    {aviso.pedido?.alumno_nombre}
                                    {aviso.preview?.destinatario ? ` · ${aviso.preview.destinatario}` : ''}
                                </small>
                            </div>
                            <button type="button" className="close-x"
                                onClick={() => setAviso(null)} aria-label="Cerrar">✕</button>
                        </div>
                        <div className="sheet-body">
                            {aviso.cargando ? (
                                <p className="empty-line">Armando el correo…</p>
                            ) : (aviso.error || !aviso.preview) ? (
                                /* Sin respuesta o con error: se ve el motivo y se puede
                                   reintentar (el GET no tiene efectos: es seguro). */
                                <div className="empty-line" role="alert">
                                    <span>⚠️ {aviso.error || 'No se pudo armar el correo'}</span>
                                    <button type="button" className="btn soft small"
                                        onClick={() => abrirAviso(aviso.pedido)}>
                                        Reintentar
                                    </button>
                                </div>
                            ) : (
                                <>
                                    <div className="mail-meta">
                                        <small>Asunto</small>
                                        <b>{aviso.preview.asunto}</b>
                                    </div>
                                    {/* HTML del backend: se muestra tal cual, sin editar
                                        y sin ejecutar nada (sandbox=""). */}
                                    <iframe className="mail-doc" title="Vista previa del aviso"
                                        sandbox="" srcDoc={aviso.preview.html} />
                                    <p className="note">
                                        Recordatorio manual de retiro: es ADICIONAL al aviso
                                        automático que el alumno ya recibió al validarse su pedido.
                                    </p>
                                </>
                            )}
                        </div>
                        <div className="sheet-foot una">
                            <button type="button" className="btn primary" onClick={enviarAviso}
                                disabled={aviso.cargando || Boolean(aviso.error)
                                    || !aviso.preview || aviso.enviando}>
                                {aviso.enviando ? 'Enviando…' : 'Enviar'}
                            </button>
                        </div>
                    </section>
                </>
            )}
            </CapaMovil>
        </div>
    );
};

export default InicioMobileAdmin;

