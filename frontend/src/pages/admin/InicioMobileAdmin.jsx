import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
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

/**
 * Tarjeta KPI. Regla del panel: si el endpoint falló se muestra "s/d" + el motivo
 * (nunca un 0 falso, que en un panel de caja se lee como "no entró plata").
 */
const Kpi = ({ clase, icono, label, valor, sub, error, cargando, dinero, pulso, onClick }) => (
    <button type="button" className={`kpi ${clase}`} onClick={onClick}
        aria-label={label} data-testid={`kpi-${icono}`}>
        {pulso && <span className="pulse" />}
        <span className="kpi-top">
            <span className="chip"><Icono nombre={icono} /></span>
            <span className="kpi-label">{label}</span>
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

    const cargarKpis = useCallback(async () => {
        setCargando(true);
        const [rReportes, rVencen, rVouchers, rCaja] = await Promise.allSettled([
            // Alumnos activos + nuevos del mes: el MISMO /reportes/ del panel ≥768px
            // (definición única del BI: `metricas_service.alumnos_vigentes`).
            api.get('/api/v1/reportes/', { params: { tenant_id } }),
            // Vencen en los próximos 5 días: el endpoint que ya usa Fidelización.
            api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/vencimientos`),
            // Vouchers por aprobar: el MISMO listado de "Pendientes".
            api.get('/api/v1/solicitudes/pendientes'),
            // Caja del día (endpoint aditivo: suma la tabla de los KPIs).
            api.get('/api/v1/finanzas/resumen-hoy'),
        ]);

        const motivo = (r) => {
            const detalle = r.reason?.response?.data?.detail;
            if (detalle) return String(detalle);
            if (r.reason?.response?.status) return `HTTP ${r.reason.response.status}`;
            return r.reason?.message || 'No se pudo cargar';
        };

        const errs = { activos: '', vencen: '', vouchers: '', caja: '' };
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

        setKpis(nuevos);
        setErrores(errs);
        setCargando(false);
    }, [tenant_id]);

    useEffect(() => {
        cargarKpis();
    }, [cargarKpis]);

    const hayVouchers = vouchers.length > 0;

    // "En revisión": abre el listado de Pendientes que ya existe (bloque C lo traerá
    // como hoja inferior dentro de esta misma pantalla).
    const abrirRevision = () => navigate('/admin/alumnos-pendientes');
    // Buscador: abre la pantalla de Alumnos que ya existe (bloque E lo trae acá).
    const abrirBuscador = () => navigate('/admin/alumnos');

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
                    <button type="button" className="app a-baz" onClick={() => navigate('/admin/bazar')}>
                        <span className="ico"><Icono nombre="cart" /></span>Bazar
                    </button>
                </nav>
            </div>
        </div>
    );
};

export default InicioMobileAdmin;
