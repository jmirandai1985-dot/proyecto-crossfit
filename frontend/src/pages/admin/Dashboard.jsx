import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Activity, Banknote, CalendarDays, DollarSign, ShoppingCart,
    Target, TrendingUp, TriangleAlert, UserPlus, Users,
} from 'lucide-react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
// Dashboard MÓVIL (<768px) del admin: réplica del mockup admin-mobile-mockup.html
// conectada a datos reales. Conviven por CSS (`md:hidden` / `hidden md:block`), igual
// que el Inicio del alumno: en ≥768px esta pantalla queda EXACTAMENTE como hoy.
import InicioMobileAdmin from './InicioMobileAdmin';
import api from '../../services/api';
import { horaChileStr, hoyChileStr } from '../../utils/fecha';
// Filtros del modal "Membresías del Mes": buscador por alumno, tipo de plan (con la
// opción de sacar las pruebas) y orden por fecha. Lógica en JS puro y testeable.
import {
    FILTRO_PLAN_SIN_PRUEBA, FILTRO_PLAN_TODOS, filtrarMembresias, planesDe,
} from '../../utils/membresiasMes';
import AdminTarjetaAlumnosPrueba from '../../components/AdminTarjetaAlumnosPrueba';
// Tarjeta "Pagos del día": los cobros de planes de hoy (misma fuente que la
// pantalla /admin/pagos-del-dia y que la campana `plan_pagado_online`).
import PagosDelDia from '../../components/pagos/PagosDelDia';
// Gráfico de barras horizontales de las clases del día (una fila por clase: hora,
// barra y "reservas / cupo"). MISMO componente que el Inicio móvil.
import GraficoClasesHoy from '../../components/dashboard/GraficoClasesHoy';
// Paneles de las tarjetas de NEGOCIO y de OCUPACIÓN: se abren anclados a su
// tarjeta (TarjetaConPanel), no debajo de la fila. Los datos los trae `useResumenAdmin`.
import {
    PanelAlumnosActivos, PanelAsistenciaHoy, PanelDetalle, PanelIngresoMes,
    PanelMembresiasMes, PanelMrr, PanelOcupacionConDatos, PanelVentasBazar,
} from '../../components/dashboard/PanelesNegocio';
// Resumen compacto de clases (sin caja con scroll) para la tarjeta de Hoy.
import ResumenClasesHoy from '../../components/dashboard/ResumenClasesHoy';
// Aviso REUTILIZABLE (secciones + Reintentar) para las tarjetas que pueden fallar.
import AvisoCarga from '../../components/AvisoCarga';
import { KpiCard } from '../../components/kpis/KpiCard';
import { useResumenAdmin } from '../../components/dashboard/useResumenAdmin';
// Vista previa/descarga del voucher: la lógica del blob autenticado (y su
// descarga forzada) vive en el hook compartido, no en cada pantalla.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';
// Datos compartidos con otras pantallas, en la caché de React Query (misma queryKey:
// lo que una pantalla ya trajo, la otra lo pinta sin volver a pedirlo).
import { mensajeError } from '../../services/queryClient';
import {
    useAprobarSolicitud, useAlumnosNuevosMes, useClasesAsistenciaHoy, useClasesHoy,
    useCountPendientesActivacion, useRechazarSolicitud, useResumenPendientes,
    useSolicitudesPendientes, useStatsDashboard,
} from '../../hooks/queries';
// Contadores de la pantalla unificada "Pendientes" (Tanda 4): la tarjeta del
// Dashboard, el badge del menú, la campana y la pantalla leen el MISMO resumen.
import { normalizarResumen, rutaPendientes } from '../../utils/pendientes';

// Estilo de una clase del día (ocupación, color de barra, cupo ampliado y badge de estado).
// Lo comparten la tarjeta y la sección "Clases de hoy": misma lectura para todas las filas.
// El estado viene del backend (`clases_service.estado_clase`): realizada / en_curso / proxima.
const ESTADO_CLASE_LABEL = {
    realizada: 'Terminada',
    en_curso: 'En curso',
    proxima: 'Próxima',
    cancelada: 'Cancelada',
};

const visualClaseHoy = (c) => {
    // Migración 066: `cupo_maximo` NULL = sin tope (Musculación / Open Box).
    // No hay % de ocupación: la fila muestra el conteo de reservas y "libre".
    const sinTope = c.cupo_maximo === null || c.cupo_maximo === undefined;
    const pct = sinTope ? null : Math.round((c.reservas_count || 0) / c.cupo_maximo * 100);
    const color = sinTope ? 'sky' : pct >= 100 ? 'red' : pct >= 80 ? 'amber' : 'green';
    const ampliado = (c.cupo_original && c.cupo_maximo > c.cupo_original)
        ? c.cupo_maximo - c.cupo_original : 0;
    const badge = c.estado === 'realizada' ? 'bg-green-100 text-green-800'
        : c.estado === 'en_curso' ? 'bg-blue-100 text-blue-800'
            : c.estado === 'cancelada' ? 'bg-red-100 text-red-800'
                : 'bg-zinc-700 text-zinc-300';
    return { pct, color, ampliado, estado: ESTADO_CLASE_LABEL[c.estado] || '', badge, sinTope };
};

/**
 * Tarjeta + su panel ANCLADO. El panel se posiciona absoluto justo debajo de
 * ESA tarjeta (no después de toda la fila), así abrir uno no empuja ni mueve
 * las demás tarjetas. El ancho se limita al viewport y el alto a 75vh con
 * scroll propio para paneles largos (Ingreso del mes, Ocupación).
 */
const TarjetaConPanel = ({ abierto, panel, children, align = 'left' }) => (
    <div className="relative">
        {children}
        {abierto && panel ? (
            <div className={`absolute top-full z-50 mt-2 max-h-[75vh] w-[min(44rem,calc(100vw-2rem))] overflow-auto rounded-lg bg-zinc-900 shadow-2xl ring-1 ring-zinc-700 ${align === 'right' ? 'right-0' : 'left-0'}`}>
                {panel}
            </div>
        ) : null}
    </div>
);

const AdminDashboard = () => {
    const navigate = useNavigate();
    const { tenant_id } = useAuth();
    // ── Datos del dashboard en la caché compartida (React Query) ──────────────
    // `solicitudes` y el conteo de registros usan las MISMAS queryKey que la pantalla
    // "Pendientes de revisión": si el admin ya pasó por allá, acá se pintan al instante
    // y no se vuelven a pedir (antes cada pantalla los pedía por su cuenta en un
    // useEffect, así que navegar entre las dos costaba 4 requests).
    const solicitudesQ = useSolicitudesPendientes();
    const registrosQ = useCountPendientesActivacion();
    // Los CUATRO contadores (solicitudes, pedidos, registros, premios) en un solo
    // request. La tarjeta usa este resumen para el total y el desglose; las listas
    // de abajo siguen con sus hooks propios (traen las filas, no sólo el número).
    const resumenQ = useResumenPendientes();
    const statsQ = useStatsDashboard(tenant_id);
    // "Alumnos nuevos de este mes": MISMA fuente que la pantalla de detalle
    // (`GET /admin/alumnos-nuevos`), así el número de la tarjeta y la lista no
    // pueden discrepar. Antes la tarjeta mostraba el KPI DIARIO del BI y el
    // detalle abría el acumulado del mes.
    const nuevosMesQ = useAlumnosNuevosMes();
    // "Clases de hoy": se refresca sola cada 45 s y NO con la pestaña oculta (React
    // Query pausa el intervalo solo), igual que el setInterval + visibility de antes.
    const clasesHoyQ = useClasesHoy();
    const aprobarSolicitud = useAprobarSolicitud();
    const rechazarSolicitud = useRechazarSolicitud();
    // ── Pendientes: DOS colas distintas, cada una con su propio error ──────────
    // `countPendientes` = REGISTROS de alumnos nuevos (pendientes-activacion/count)
    // `solicitudes`     = SOLICITUDES DE PLAN con comprobante (/solicitudes/pendientes)
    // Antes la tarjeta del dashboard mostraba SOLO la primera: con 1 comprobante de
    // plan esperando revisión, el contador decía "0". Y si un endpoint fallaba, se
    // pintaba un 0 falso; ahora se muestra "s/d" + el motivo.
    // Derivados de las consultas de arriba: MISMOS nombres y MISMOS textos de error que
    // antes, así el JSX de la pantalla no cambia.
    const solicitudes = solicitudesQ.data || [];
    const countPendientes = registrosQ.data || 0;
    const stats = statsQ.data ?? null;
    const resumenAdmin = useResumenAdmin();
    const registrosError = registrosQ.error
        ? mensajeError(registrosQ.error, 'No se pudo cargar el dato') : '';
    const solicitudesError = solicitudesQ.error
        ? mensajeError(solicitudesQ.error, 'No se pudieron cargar las solicitudes de plan') : '';
    const loading = solicitudesQ.isLoading || registrosQ.isLoading || statsQ.isLoading;
    const [processingId, setProcessingId] = useState(null);
    const [msg, setMsg] = useState('');
    const [voucherModal, setVoucherModal] = useState({ open: false, solicitud_id: null, tipo: 'voucher' });
    // Voucher AUTENTICADO: la vista previa y la descarga van por el endpoint
    // protegido GET /solicitudes/{id}/voucher (con Bearer) y se materializan como
    // blob (hook `useDocumentoAutenticado` más abajo). Así no se depende de la URL
    // pública /static/uploads/... (que se sirve sin autenticación por StaticFiles).
    const [rechazoModal, setRechazoModal] = useState({ open: false, solicitud_id: null, motivo: '' });
    // Fidelización state
    const [vencimientos, setVencimientos] = useState([]);
    const [fidelizacionLoading, setFidelizacionLoading] = useState(true);
    const [fidelizacionError, setFidelizacionError] = useState({ vencimientos: '' });
    // ── "Clases de hoy" (tarjeta + sección) ────────────────────────────────────
    // Reutiliza GET /asistencia/clases-hoy (ya trae coach, estado y reservas) y filtra
    // en el front las disciplinas que EXIGEN coach (`requiere_coach`), sin hardcodear
    // CrossFit/Levantamiento. Se refresca solo cada 45s (pausado si la pestaña está oculta).
    // Derivados de la consulta de clases de hoy (los mismos nombres que el estado local
    // de antes: el error se sigue mostrando como "s/d" con el motivo en el title).
    const clasesHoy = clasesHoyQ.data || [];
    const clasesHoyLoading = clasesHoyQ.isLoading;
    const clasesHoyError = clasesHoyQ.error
        ? mensajeError(clasesHoyQ.error, 'No se pudieron cargar las clases de hoy') : '';
    // El GRÁFICO de la tarjeta muestra TODAS las clases del día (incluidas las de cupo
    // libre: Musculación / Open Box), no sólo las que exigen coach. `useClasesHoy` sí
    // filtra por `requiere_coach` y sigue alimentando la sección "Clases de hoy".
    const clasesDiaQ = useClasesAsistenciaHoy();
    const clasesDia = clasesDiaQ.data || [];
    const clasesDiaLoading = clasesDiaQ.isLoading;
    const clasesDiaError = clasesDiaQ.error
        ? mensajeError(clasesDiaQ.error, 'No se pudieron cargar las clases de hoy') : '';
    // "Asistencia de hoy" = asistencias REGISTRADAS hoy (suma de
    // `asistentes_confirmados` de las clases del día). Sin retroceso de días ni
    // snapshot del BI: si la consulta no llegó, la tarjeta dice "n/d".
    const asistenciaHoy = clasesDiaQ.data
        ? clasesDia.reduce((total, c) => total + (Number(c.asistentes_confirmados) || 0), 0)
        : null;
    // Año/mes del calendario de Chile para el panel de Ocupación.
    const [anioActual, mesActual] = String(hoyChileStr()).split('-').map(Number);
    const ultimaActualizacion = clasesHoyQ.dataUpdatedAt
        ? new Date(clasesHoyQ.dataUpdatedAt) : null;
    // Detalle de una clase (modal): reservas de la clase desde /asistencia/clases/{id}/alumnos.
    const [claseDetalle, setClaseDetalle] = useState(null);
    const [detalleReservas, setDetalleReservas] = useState([]);
    const [detalleLoading, setDetalleLoading] = useState(false);
    // ── Paneles anclados: UNO SOLO abierto a la vez ─────────────────────────
    // 'clases' | 'asistencia' | 'pagos' | 'ingreso' | 'mrr' | 'bazar'
    // | 'membresias' | 'alumnos' | 'ocupacion' | null.
    // Abrir otro cierra el anterior (no se superponen) y un segundo clic cierra.
    const [panelActivo, setPanelActivo] = useState(null);
    const alternarPanel = (clave) => setPanelActivo(
        (actual) => (actual === clave ? null : clave));
    const cerrarPanel = () => setPanelActivo(null);
    // Fidelización — modal membresías del mes
    const [fidelizacionModal, setFidelizacionModal] = useState(null); // 'membresias'
    // Filtros del listado de membresías: un mes normal trae 263 filas y sin buscador
    // no había forma de encontrar a un alumno; las cuentas de "Prueba" tampoco son
    // ventas. Se resuelven sobre los datos que el Dashboard ya tiene (sin endpoint).
    const [busquedaMembresias, setBusquedaMembresias] = useState('');
    const [planMembresias, setPlanMembresias] = useState(FILTRO_PLAN_TODOS);
    const [ordenMembresias, setOrdenMembresias] = useState('reciente');
    const suscripcionesMes = stats?.suscripcionesMes || [];
    // La dependencia es el dato de React Query (referencia estable), no el `|| []`
    // de arriba, que crearía un arreglo nuevo en cada render.
    const planesMembresias = useMemo(() => planesDe(stats?.suscripcionesMes), [stats?.suscripcionesMes]);
    const membresiasVisibles = useMemo(() => filtrarMembresias(stats?.suscripcionesMes, {
        busqueda: busquedaMembresias, plan: planMembresias, orden: ordenMembresias,
    }), [stats?.suscripcionesMes, busquedaMembresias, planMembresias, ordenMembresias]);
    useEffect(() => {
        // Las consultas migradas a React Query (solicitudes, conteo de registros, stats,
        // clases y tarjetas del mes) se disparan solas al declarar sus hooks; acá queda
        // sólo la fidelización, que sigue con estado local. El auto-refresco de
        // "Clases de hoy" cada 45 s lo hace `refetchInterval` del hook (y NO corre con
        // la pestaña oculta).
        cargarFidelizacion();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tenant_id]);

    const abrirDetalleClase = async (clase) => {
        setClaseDetalle(clase);
        setDetalleReservas([]);
        setDetalleLoading(true);
        try {
            const r = await api.get(`/api/v1/asistencia/clases/${clase.id}/alumnos`);
            setDetalleReservas(r.data?.reservas || []);
        } catch {
            setDetalleReservas([]);
        }
        setDetalleLoading(false);
    };

    // Botón "Actualizar" del dashboard: refresca TODO. Lo que vive en React Query se
    // re-pide con `refetch()` (y comparte caché con las otras pantallas); la
    // fidelización sigue con su carga local.
    const recargarDatos = () => {
        solicitudesQ.refetch();
        registrosQ.refetch();
        statsQ.refetch();
        clasesHoyQ.refetch();
        clasesDiaQ.refetch();
        nuevosMesQ.refetch();
        resumenAdmin.recargar();
        cargarFidelizacion();
    };

    const cargarFidelizacion = async () => {
        // El riesgo ahora sale del snapshot de churn (`useResumenAdmin`); acá
        // sólo queda la tarjeta de vencimientos. Sin catch mudo: si falla, se
        // muestra el motivo y no un 0 falso.
        setFidelizacionLoading(true);
        try {
            const res = await api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/vencimientos`);
            setVencimientos(res.data?.alumnos || []);
            setFidelizacionError((prev) => ({ ...prev, vencimientos: '' }));
        } catch (error) {
            setVencimientos([]);
            setFidelizacionError((prev) => ({
                ...prev,
                vencimientos: error?.response?.data?.detail
                    || error?.message
                    || 'No se pudo cargar el dato',
            }));
        }
        setFidelizacionLoading(false);
    };

    const handleAprobar = async (id) => {
        setProcessingId(id);
        setMsg('');
        try {
            await aprobarSolicitud.mutateAsync(id);
            setMsg(`✅ Solicitud #${id} aprobada. Tokens asignados.`);
            setTimeout(() => setMsg(''), 4000);
            // Sin `cargarSolicitudes()`: la mutación invalida las colas y React Query
            // las refresca (acá y en Pendientes). La fidelización sigue con estado local.
            cargarFidelizacion();
        } catch (err) {
            setMsg('❌ ' + (err.response?.data?.detail || err.message));
            setTimeout(() => setMsg(''), 4000);
        }
        setProcessingId(null);
    };

    const handleRechazar = async (id, motivo) => {
        setProcessingId(id);
        setMsg('');
        try {
            await rechazarSolicitud.mutateAsync({ id, motivo });
            setMsg(`✅ Solicitud #${id} rechazada.`);
            setTimeout(() => setMsg(''), 4000);
        } catch (err) {
            setMsg('❌ ' + (err.response?.data?.detail || err.message));
            setTimeout(() => setMsg(''), 4000);
        }
        setProcessingId(null);
    };

    // Vista previa del documento (voucher o CERTIFICADO) por su endpoint
    // AUTENTICADO: la lógica vive en el hook compartido, que además revoca el
    // object URL al cerrar el modal. La URL pública /static/uploads/... ya no se
    // usa para el certificado (ver GET /solicitudes/{id}/certificado).
    const esCertificado = voucherModal.tipo === 'certificado';
    const {
        preview: voucherPreview,
        descargando: descargandoVoucher,
        descargar: descargarDocumento,
        reintentar: reintentarVoucher,
    } = useDocumentoAutenticado({
        previewUrl: (voucherModal.open && voucherModal.solicitud_id)
            ? `/api/v1/solicitudes/${voucherModal.solicitud_id}/${esCertificado ? 'certificado' : 'voucher'}?inline=1`
            : '',
        nombreFallback: `${esCertificado ? 'certificado' : 'voucher'}_${voucherModal.solicitud_id || ''}`,
    });

    const handleDescargarDocumento = async (solicitud_id, tipo) => {
        if (!solicitud_id) return;
        const certificado = tipo === 'certificado';
        setMsg('');
        // Descarga AUTENTICADA (axios con Bearer -> blob -> URL objeto): nunca se
        // navega a la URL del backend, porque esa navegación no lleva el token.
        const res = await descargarDocumento(
            `/api/v1/solicitudes/${solicitud_id}/${certificado ? 'certificado' : 'voucher'}`);
        setMsg(res.ok
            ? (certificado ? '✅ Certificado descargado.' : '✅ Voucher descargado.')
            : '❌ ' + res.error);
        setTimeout(() => setMsg(''), 4000);
    };

    // Pendientes por revisar = los CUATRO contadores del resumen (solicitudes de plan
    // con comprobante, pedidos del Bazar sin validar, registros de alumno nuevo y
    // premios de referidos). Si falló el resumen se cae al cálculo viejo (las dos
    // colas que la pantalla ya tenía cargadas) y, si también falló alguna de esas,
    // se devuelve null y la tarjeta muestra "s/d" en vez de un total incompleto.
    const resumen = normalizarResumen(resumenQ.data);
    const resumenError = resumenQ.error
        ? mensajeError(resumenQ.error, 'No se pudieron contar los pendientes') : '';
    const hayResumen = !!resumenQ.data && !resumenError;
    const totalPendientes = hayResumen
        ? resumen.total
        : (registrosError || solicitudesError)
            ? null
            : (countPendientes || 0) + solicitudes.length;
    // Desglose de la tarjeta: se muestra sólo lo que tiene algo (o el resumen completo
    // cuando está en cero, para que la tarjeta no quede muda).
    const desglosePendientes = [
        { clave: 'registros', label: 'registro', plural: 'registros' },
        { clave: 'solicitudes', label: 'solicitud de plan', plural: 'solicitudes de plan' },
        { clave: 'pedidos', label: 'pedido', plural: 'pedidos' },
        { clave: 'premios', label: 'premio', plural: 'premios' },
    ].map(({ clave, label, plural }) => ({
        clave,
        texto: `${resumen[clave]} ${resumen[clave] === 1 ? label : plural}`,
    }));

    // "Alumnos nuevos de este mes": número y listado salen del MISMO endpoint que
    // abre la tarjeta (`/admin/alumnos-nuevos`). `convertidos` viene resuelto por
    // el backend (plan comercial vigente), no se recalcula en el cliente.
    const nuevosMes = nuevosMesQ.data?.alumnos || [];
    const totalNuevosMes = nuevosMesQ.data?.total ?? nuevosMes.length;
    const convertidosNuevosMes = nuevosMes.filter((a) => a.convertido).length;

    // Resumen de "Clases de hoy" (tarjeta + encabezado de la sección):
    // X de Y realizadas + ocupación del día (reservas sobre cupos ofrecidos).
    const clasesHoyRealizadas = clasesHoy.filter(c => c.estado === 'realizada').length;
    const clasesHoyTotal = clasesHoy.length;
    // Contadores del GRÁFICO: TODAS las clases del día (la sección de abajo sigue con
    // las que exigen coach).
    const clasesDiaRealizadas = clasesDia.filter(c => c.estado === 'realizada').length;
    const clasesDiaTotal = clasesDia.length;
    const reservasHoy = clasesHoy.reduce((a, c) => a + (c.reservas_count || 0), 0);
    const cuposHoy = clasesHoy.reduce((a, c) => a + (c.cupo_maximo || 0), 0);
    // Migración 066: el cociente es sólo de las clases CON tope; las reservas de
    // las salas libres (Musculación / Open Box) no tienen denominador.
    const reservasHoyConTope = clasesHoy
        .filter(c => c.cupo_maximo !== null && c.cupo_maximo !== undefined)
        .reduce((a, c) => a + (c.reservas_count || 0), 0);
    const ocupacionHoyPct = cuposHoy > 0 ? Math.round(reservasHoyConTope / cuposHoy * 100) : 0;

    if (loading) {
        return (
            <Layout>
                {/* <768px: el dashboard móvil ya tiene su propio estado de carga
                    (nunca un spinner a pantalla completa que tape los KPIs). */}
                <div className="md:hidden">
                    <InicioMobileAdmin resumenAdmin={resumenAdmin} />
                </div>
                <div className="hidden md:flex items-center justify-center h-96">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4" />
                    <p className="text-zinc-400">Cargando...</p>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            {/* Vista MÓVIL (<768px): resume el día y enlaza a las pantallas que ya
                existen. No se monta en ≥768px (regla de oro: el escritorio no cambia). */}
            <div className="md:hidden">
                <InicioMobileAdmin resumenAdmin={resumenAdmin} />
            </div>

            {/* Vista de ESCRITORIO (≥768px): el dashboard de siempre, sin cambios. */}
            <div className="hidden md:block space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-zinc-100">Dashboard Administrativo</h1>
                        <p className="text-zinc-400">Panel de gestión de membresías y fidelización</p>
                    </div>
                    <button onClick={recargarDatos} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-bold">
                        🔄 Recargar
                    </button>
                </div>

                {msg && (
                    <div className={`p-4 rounded-lg font-bold shadow-lg transition-all ${msg.includes('✅') ? 'bg-green-100 text-green-800' : msg.includes('❌') ? 'bg-red-100 text-red-800' : 'bg-blue-500/20 text-blue-300'}`}>
                        {msg}
                    </div>
                )}

                {/* ── BLOQUES DEL MOCKUP (escritorio) ─────────────────────────
                    Hoy → Negocio del mes → Alumnos → Conversión → Ocupación.
                    Cada bloque dice su período. Los detalles operativos siguen
                    debajo como profundización. ─────────────────────────────── */}

                <section aria-labelledby="dashboard-hoy" className="space-y-3">
                    <div>
                        <h2 id="dashboard-hoy" className="text-lg font-bold text-zinc-100">Hoy</h2>
                        <p className="text-xs text-zinc-500">Operación e ingresos del día en curso</p>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                        {/* "Clases de hoy": resumen legible (hora + reservas/cupo; las
                            clases sin cupo van como texto). El gráfico completo se abre
                            ANCLADO debajo de esta misma tarjeta. */}
                        <TarjetaConPanel
                            abierto={panelActivo === 'clases'}
                            panel={(
                                <PanelDetalle
                                    id="dashboard-grafico-clases"
                                    titulo="Clases de hoy · reservas / cupo"
                                    subtitulo="Reservas confirmadas sobre el cupo de cada clase. Las clases sin cupo muestran sólo sus reservas."
                                    onCerrar={cerrarPanel}>
                                    <GraficoClasesHoy clases={clasesDia} alto="24rem"
                                        testid="grafico-clases-hoy-panel-escritorio" />
                                </PanelDetalle>
                            )}>
                            <div
                                role="button"
                                tabIndex={0}
                                aria-label="Ver el detalle de las clases de hoy"
                                aria-expanded={panelActivo === 'clases'}
                                data-testid="kpi-grafico-clases-escritorio"
                                onClick={() => alternarPanel('clases')}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        alternarPanel('clases');
                                    }
                                }}
                                className="bg-zinc-900 rounded-lg shadow p-4 border-l-4 border-indigo-500 cursor-pointer transition hover:ring-2 hover:ring-zinc-600 focus:outline-none focus:ring-2 focus:ring-sky-500"
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <p className="text-xs text-gray-400 uppercase tracking-wide">Clases de hoy</p>
                                    <div className="flex items-center gap-1">
                                        <CalendarDays className="w-6 h-6 text-gray-600" />
                                        <span className="text-lg leading-none text-gray-500" aria-hidden="true">›</span>
                                    </div>
                                </div>
                                <div className="mt-1">
                                    {clasesDiaLoading ? (
                                        <p className="text-2xl font-bold text-zinc-600">…</p>
                                    ) : clasesDiaError ? (
                                        <p className="text-sm font-bold text-amber-400 mt-2" title={clasesDiaError}>⚠️ s/d</p>
                                    ) : (
                                        <ResumenClasesHoy clases={clasesDia} max={6} />
                                    )}
                                </div>
                                <p className="text-[11px] text-zinc-500 mt-2">
                                    {clasesDiaRealizadas}/{clasesDiaTotal} realizadas · reservas / cupo — Clic para ver el detalle
                                </p>
                            </div>
                        </TarjetaConPanel>
                        <TarjetaConPanel
                            abierto={panelActivo === 'asistencia'}
                            align="right"
                            panel={(
                                <PanelAsistenciaHoy
                                    clases={clasesDia}
                                    cargando={clasesDiaLoading}
                                    error={clasesDiaError}
                                    onCerrar={cerrarPanel}
                                    onVerTodo={() => navigate('/admin/asistencia')}
                                />
                            )}>
                            <KpiCard
                                label="Asistencia de hoy"
                                value={asistenciaHoy}
                                icon={Users}
                                color="border-purple-500"
                                hint="Hoy · asistencias registradas en las clases del día — Clic para ver el resumen"
                                onDetalle={() => alternarPanel('asistencia')}
                                chevron
                            />
                        </TarjetaConPanel>
                        {/* "Ingresos de hoy" es la ÚNICA tarjeta del día: muestra el total
                            cobrado del día y la cantidad de cobros, y abre la lista de
                            pagos. El valor sale de "Pagos del día" (membresías + Bazar),
                            NO de la caja de `transacciones_financieras` (que se quedaba en
                            $0 cuando el webhook no escribía la transacción). "Pagos de hoy"
                            (su tarjeta hermana) se eliminó: repetía el mismo panel. */}
                        <TarjetaConPanel
                            abierto={panelActivo === 'pagos'}
                            align="right"
                            panel={(
                                <PanelDetalle
                                    id="dashboard-pagos-hoy"
                                    titulo="Pagos del día"
                                    subtitulo="Cobros de planes de hoy por Mercado Pago — el plan y si ya está activo."
                                    onCerrar={cerrarPanel}>
                                    <PagosDelDia maxFilas={6} mostrarEnlace />
                                </PanelDetalle>
                            )}>
                            <KpiCard
                                label="Ingresos de hoy"
                                value={resumenAdmin.ingresosHoy ?? null}
                                unit="CLP"
                                icon={DollarSign}
                                color="border-emerald-500"
                                hint={resumenAdmin.cobrosHoy == null
                                    ? 'Hoy · cobros del día — Clic para ver el desglose'
                                    : `Hoy · ${resumenAdmin.cobrosHoy} ${resumenAdmin.cobrosHoy === 1 ? 'cobro' : 'cobros'} de membresía y Bazar — Clic para ver el desglose`}
                                onDetalle={() => alternarPanel('pagos')}
                                chevron
                            />
                        </TarjetaConPanel>
                    </div>

                </section>

                <section aria-labelledby="dashboard-negocio-mes" className="space-y-3">
                    <div>
                        <h2 id="dashboard-negocio-mes" className="text-lg font-bold text-zinc-100">Negocio del mes</h2>
                        <p className="text-xs text-zinc-500">
                            Mes en curso · parcial · comparación con el mes anterior: n/d
                            (no se compara un mes parcial contra un mes completo)
                        </p>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                        <TarjetaConPanel
                            abierto={panelActivo === 'ingreso'}
                            panel={(
                                <PanelIngresoMes
                                    resumen={resumenAdmin.ingresoMes}
                                    cargando={resumenAdmin.ingresoMesCargando}
                                    error={resumenAdmin.ingresoMesError}
                                    onCerrar={cerrarPanel}
                                />
                            )}>
                            <KpiCard
                                label="Ingreso del mes"
                                value={resumenAdmin.ingresoMesCargando ? '…'
                                    : (resumenAdmin.ingresoMes?.total_clp ?? null)}
                                unit={resumenAdmin.ingresoMesCargando ? '' : 'CLP'}
                                icon={DollarSign}
                                color="border-amber-500"
                                hint={resumenAdmin.ingresoMesError
                                    || `Mes en curso · ${resumenAdmin.ingresoMes?.cantidad ?? 0} cobros aprobados (membresías + Bazar) — Clic para ver el desglose por día`}
                                onDetalle={() => alternarPanel('ingreso')}
                                chevron
                            />
                        </TarjetaConPanel>
                        <TarjetaConPanel
                            abierto={panelActivo === 'mrr'}
                            panel={(
                                <PanelMrr
                                    mrr={resumenAdmin.mrr}
                                    cargando={resumenAdmin.mrrCargando}
                                    error={resumenAdmin.mrrError}
                                    onCerrar={cerrarPanel}
                                />
                            )}>
                            <KpiCard
                                label="MRR"
                                value={resumenAdmin.mrrCargando ? '…'
                                    : (resumenAdmin.mrr?.total_clp ?? null)}
                                unit={resumenAdmin.mrrCargando ? '' : 'CLP'}
                                icon={Banknote}
                                color="border-emerald-500"
                                hint={resumenAdmin.mrrError
                                    || `MRR · corte de hoy (${resumenAdmin.mrr?.actual?.fecha_corte || resumenAdmin.mrr?.fecha || '—'}) · ${resumenAdmin.mrr?.alumnos ?? 0} alumnos con membresía de pago — Clic para ver el detalle por plan`}
                                onDetalle={() => alternarPanel('mrr')}
                                chevron
                            />
                        </TarjetaConPanel>
                        <TarjetaConPanel
                            abierto={panelActivo === 'bazar'}
                            align="right"
                            panel={(
                                <PanelVentasBazar
                                    pagos={resumenAdmin.ingresoMes?.pagos}
                                    cargando={resumenAdmin.ventasBazarCargando}
                                    error={resumenAdmin.ventasBazarError}
                                    onCerrar={cerrarPanel}
                                    onVerTodo={() => navigate('/admin/pedidos')}
                                />
                            )}>
                            <KpiCard
                                label="Ventas Bazar"
                                value={resumenAdmin.ventasBazarCargando ? '…'
                                    : (resumenAdmin.ventasBazar ?? null)}
                                unit={resumenAdmin.ventasBazarCargando ? '' : 'CLP'}
                                icon={ShoppingCart}
                                color="border-teal-500"
                                hint={resumenAdmin.ventasBazarError
                                    || `Mes en curso · ${resumenAdmin.ventasBazarPedidos ?? 0} pedidos cobrados — Clic para ver el resumen`}
                                onDetalle={() => alternarPanel('bazar')}
                                chevron
                            />
                        </TarjetaConPanel>
                        <TarjetaConPanel
                            abierto={panelActivo === 'membresias'}
                            align="right"
                            panel={(
                                <PanelMembresiasMes
                                    ranking={resumenAdmin.membresiasMes}
                                    cargando={resumenAdmin.membresiasMesCargando}
                                    error={resumenAdmin.membresiasMesError}
                                    onCerrar={cerrarPanel}
                                />
                            )}>
                            <KpiCard
                                label="Membresías del mes"
                                value={resumenAdmin.membresiasMesCargando ? '…'
                                    : (resumenAdmin.membresiasMes?.total_altas ?? null)}
                                icon={Users}
                                color="border-green-500"
                                hint={resumenAdmin.membresiasMesError
                                    || 'Mes en curso · planes de membresía pagados (sin pruebas) — Clic para ver el ranking'}
                                onDetalle={() => alternarPanel('membresias')}
                                chevron
                            />
                        </TarjetaConPanel>
                    </div>

                </section>

                <section aria-labelledby="dashboard-alumnos" className="space-y-3">
                    <div>
                        <h2 id="dashboard-alumnos" className="text-lg font-bold text-zinc-100">Alumnos</h2>
                        <p className="text-xs text-zinc-500">Base de clientes y señales de riesgo</p>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <TarjetaConPanel
                            abierto={panelActivo === 'alumnos'}
                            panel={(
                                <PanelAlumnosActivos
                                    resumen={resumenAdmin.alumnosActivosResumen}
                                    cargando={resumenAdmin.alumnosActivosCargando}
                                    error={resumenAdmin.alumnosActivosError}
                                    onCerrar={cerrarPanel}
                                    onVerTodo={() => navigate('/admin/alumnos?estado=activo')}
                                />
                            )}>
                            <KpiCard
                                label="Alumnos activos"
                                value={resumenAdmin.alumnosActivos}
                                icon={Users}
                                color="border-sky-500"
                                hint="Hoy · suscripciones vigentes (en vivo) — Clic para ver el resumen"
                                onDetalle={() => alternarPanel('alumnos')}
                                chevron
                            />
                        </TarjetaConPanel>
                        <KpiCard
                            label="Alumnos en riesgo"
                            value={resumenAdmin.alumnosRiesgo}
                            icon={TriangleAlert}
                            color="border-red-500"
                            hint={resumenAdmin.riesgoPendiente
                                ? 'pendiente de reentrenar'
                                : 'Hoy · crítico + alto entre los alumnos activos — Clic para ver la lista filtrada'}
                            onDetalle={() => navigate('/admin/fidelizacion?filtro=riesgo_activos')}
                        />
                        <KpiCard
                            label="Nuevos del mes"
                            value={nuevosMesQ.data ? totalNuevosMes : null}
                            icon={UserPlus}
                            color="border-green-500"
                            hint="Mes en curso · alumnos creados este mes — Clic para ver el padrón filtrado"
                            onDetalle={() => navigate('/admin/alumnos?alta=mes')}
                            chevron
                        />
                    </div>
                </section>

                <section aria-labelledby="dashboard-conversion-mock" className="space-y-3">
                    <div>
                        <h2 id="dashboard-conversion-mock" className="text-lg font-bold text-zinc-100">Conversión</h2>
                        <p className="text-xs text-zinc-500">
                            Prueba → plan · {resumenAdmin.periodoTexto
                                ? `mes en curso: ${resumenAdmin.periodoTexto}`
                                : 'mes en curso'}
                        </p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <KpiCard
                            label="Conversión prueba→plan"
                            value={resumenAdmin.conversionRate}
                            unit={resumenAdmin.conversionRate === null ? '' : '%'}
                            icon={TrendingUp}
                            color="border-green-500"
                            hint={`${resumenAdmin.conversionHint}${resumenAdmin.periodoTexto
                                ? ` · ${resumenAdmin.periodoTexto}` : ''} — Clic para ver los convertidos`}
                            onDetalle={() => navigate(
                                `/admin/alumnos-convertidos?anio=${resumenAdmin.periodoAnio}&mes=${resumenAdmin.periodoMes}`)}
                            chevron
                        />
                    </div>
                </section>

                <section aria-labelledby="dashboard-ocupacion" className="space-y-3">
                    <div>
                        <h2 id="dashboard-ocupacion" className="text-lg font-bold text-zinc-100">Ocupación</h2>
                        <p className="text-xs text-zinc-500">
                            Mes en curso · asistencia real sobre cupo de las clases realizadas
                            {resumenAdmin.periodoTexto ? ` (${resumenAdmin.periodoTexto})` : ''}
                        </p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <TarjetaConPanel
                            abierto={panelActivo === 'ocupacion'}
                            panel={(
                                <PanelOcupacionConDatos
                                    anio={anioActual}
                                    mes={mesActual}
                                    onCerrar={cerrarPanel}
                                />
                            )}>
                            <KpiCard
                                label="Ocupación"
                                value={resumenAdmin.ocupacionReal}
                                unit={resumenAdmin.ocupacionReal === null ? '' : '%'}
                                icon={Target}
                                color="border-amber-500"
                                hint={resumenAdmin.periodoTexto
                                    ? `Mes en curso · ${resumenAdmin.periodoTexto} · asistencias marcadas ÷ cupo de clases realizadas — Clic para ver el detalle por clase`
                                    : 'Mes en curso · asistencias marcadas ÷ cupo de clases realizadas — Clic para ver el detalle por clase'}
                                onDetalle={() => alternarPanel('ocupacion')}
                                chevron
                            />
                        </TarjetaConPanel>
                        <KpiCard
                            label="Asistencia real"
                            value={resumenAdmin.asistenciaReal}
                            unit={resumenAdmin.asistenciaReal === null ? '' : '%'}
                            icon={Activity}
                            color="border-purple-500"
                            hint={resumenAdmin.periodoTexto
                                ? `Mes en curso · ${resumenAdmin.periodoTexto} · asistencias marcadas ÷ reservas confirmadas (no es ocupación)`
                                : 'Mes en curso · asistencias marcadas ÷ reservas confirmadas (no es ocupación)'}
                        />
                    </div>
                </section>

                <div className="pt-3 border-t border-zinc-800">
                    <h2 className="text-lg font-bold text-zinc-100">Detalle operativo</h2>
                    <p className="text-xs text-zinc-500">
                        Clases, solicitudes, pagos y prospectos del día
                    </p>
                </div>

                {/* 1. OPERATIVA INMEDIATA: lo que requiere atención HOY va primero.
                    Clases de hoy y solicitudes de plan son las dos colas accionables. */}
                {stats && (
                    <section aria-labelledby="dashboard-operativa" className="space-y-3">
                        <div>
                            <h2 id="dashboard-operativa" className="text-lg font-bold text-zinc-100">
                                Operativa de hoy
                            </h2>
                            <p className="text-xs text-zinc-500">
                                Clases y solicitudes de plan que requieren atención ahora
                            </p>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <button onClick={() => document.getElementById('clases-hoy')?.scrollIntoView({ behavior: 'smooth' })} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-indigo-600 hover:shadow-md hover:border-indigo-700 transition-all cursor-pointer text-left">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Clases de Hoy</p>
                                {clasesHoyLoading ? (
                                    <p className="text-3xl font-bold text-zinc-600 mt-1">…</p>
                                ) : clasesHoyError ? (
                                    <p className="text-sm font-bold text-amber-400 mt-2" title={clasesHoyError}>⚠️ s/d</p>
                                ) : (
                                    <>
                                        <p className="text-3xl font-bold text-indigo-700 mt-1">
                                            {clasesHoyRealizadas}<span className="text-lg font-semibold text-zinc-500">/{clasesHoyTotal}</span>
                                        </p>
                                        <p className="text-xs text-zinc-500 mt-1">
                                            {clasesHoyRealizadas} de {clasesHoyTotal} realizadas — Clic para ver
                                        </p>
                                    </>
                                )}
                            </button>
                            <button onClick={() => navigate(rutaPendientes('solicitudes'))} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-rose-600 hover:shadow-md hover:border-rose-700 transition-all cursor-pointer text-left">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Solicitudes Pendientes</p>
                                {totalPendientes === null ? (
                                    <p className="text-sm font-bold text-rose-400 mt-2" title={registrosError || solicitudesError || resumenError}>
                                        ⚠️ s/d (no se pudo consultar)
                                    </p>
                                ) : (
                                    <p className="text-3xl font-bold text-rose-700 mt-1">{totalPendientes}</p>
                                )}
                                {/* Desglose de la pantalla unificada: antes sólo se contaban los
                                    registros y una solicitud de plan con voucher no sumaba en
                                    ninguna parte (y los pedidos / premios no aparecían acá). */}
                                <p className="text-xs text-zinc-500 mt-1">
                                    {desglosePendientes.map((d) => d.texto).join(' · ')} — Clic para ver
                                </p>
                            </button>
                        </div>
                    </section>
                )}

                {/* SECCIÓN "CLASES DE HOY": todas las clases del día que exigen coach, por hora,
                    con ocupación, coach y estado. Reutiliza GET /asistencia/clases-hoy; al hacer
                    clic en una clase se abren sus alumnos (GET /asistencia/clases/{id}/alumnos). */}
                <div id="clases-hoy" className="bg-zinc-900 rounded-lg shadow p-5">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                        <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2">
                            📅 Clases de hoy
                        </h2>
                        {ultimaActualizacion && (
                            <span className="text-xs text-zinc-500">
                                Actualizado {horaChileStr(ultimaActualizacion)} · se refresca solo
                            </span>
                        )}
                    </div>
                    <p className="text-xs text-zinc-400 mt-0.5">
                        Clases del día que exigen coach · {clasesHoyRealizadas}/{clasesHoyTotal} realizadas ·
                        {' '}{reservasHoy}/{cuposHoy} reservas ({ocupacionHoyPct}%)
                    </p>
                    {clasesHoyLoading ? (
                        <div className="flex justify-center py-6"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-500"></div></div>
                    ) : clasesHoyError ? (
                        <div className="py-6 text-center text-sm text-amber-400">⚠️ {clasesHoyError}</div>
                    ) : clasesHoy.length === 0 ? (
                        <div className="py-6 text-center text-zinc-500 text-sm">No hay clases hoy que exijan coach</div>
                    ) : (
                        <div className="mt-4 space-y-1">
                            {clasesHoy.map(c => {
                                const v = visualClaseHoy(c);
                                return (
                                    <div key={c.id} onClick={() => abrirDetalleClase(c)}
                                        className="cursor-pointer rounded-lg px-2 py-2 hover:bg-zinc-800/60 transition-colors">
                                        <div className="flex items-center gap-3">
                                            <div className="text-sm font-semibold text-zinc-300 w-12 shrink-0">{c.hora_inicio?.slice(0, 5)}</div>
                                            <div className="w-40 shrink-0">
                                                <div className="text-sm text-zinc-200 truncate">{c.disciplina_nombre}</div>
                                                <div className={`text-xs truncate ${c.coach ? 'text-zinc-500' : 'text-amber-400 font-semibold'}`}>
                                                    {c.coach ? `👤 ${c.coach}` : '⚠️ Sin coach'}
                                                </div>
                                            </div>
                                            <div className="flex-1 bg-zinc-800 rounded-full h-4 overflow-hidden min-w-[40px]">
                                                <div className={`h-full rounded-full transition-all ${v.color === 'red' ? 'bg-red-500' : v.color === 'amber' ? 'bg-amber-500' : v.color === 'sky' ? 'bg-sky-500' : 'bg-green-500'}`}
                                                    style={{ width: `${Math.min(v.pct ?? 0, 100)}%` }} />
                                            </div>
                                            <div className="text-sm text-zinc-400 w-28 shrink-0 text-right">
                                                {c.reservas_count || 0}{v.sinTope ? ' (libre)' : `/${c.cupo_maximo || 0}`}
                                                {v.ampliado > 0 && (
                                                    <span className="text-amber-400" title={`Cupo ampliado +${v.ampliado} sobre el original de ${c.cupo_original}`}> (+{v.ampliado})</span>
                                                )}
                                            </div>
                                            <div className="text-sm font-semibold text-zinc-300 w-12 shrink-0 text-right">
                                                {v.pct === null ? 'libre' : `${v.pct}%`}
                                            </div>
                                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium shrink-0 w-24 text-center ${v.badge}`}>
                                                {v.estado}
                                            </span>
                                        </div>
                                        {c.estado === 'realizada' && (
                                            <div className="text-xs text-zinc-500 mt-1 pl-14">
                                                ✅ {c.asistentes_confirmados || 0} asistieron · {c.reservas_count || 0} reservaron
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* SOLICITUDES PENDIENTES */}
                <div id="solicitudes-pendientes" className="bg-zinc-900 rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between gap-3">
                        <div>
                            <h2 className="text-lg font-bold text-zinc-100">
                                📋 Solicitudes de plan pendientes {solicitudes.length > 0 && `(${solicitudes.length})`}
                            </h2>
                            <p className="text-xs text-zinc-500 mt-0.5">
                                Comprobantes de pago (voucher) esperando aprobación o rechazo
                            </p>
                        </div>
                        <button
                            onClick={() => navigate(rutaPendientes('registros'))}
                            className="shrink-0 px-3 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-semibold transition-colors"
                            title="Ver los registros de alumnos nuevos pendientes en la pantalla unificada"
                        >
                            Ver registros pendientes ({resumen.registros})
                        </button>
                    </div>
                    {solicitudesError ? (
                        <div className="p-8 text-center">
                            <p className="text-red-400 text-sm">⚠️ {solicitudesError}</p>
                            <button
                                onClick={() => solicitudesQ.refetch()}
                                className="mt-3 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm transition-colors"
                            >
                                Reintentar
                            </button>
                        </div>
                    ) : solicitudes.length === 0 ? (
                        <div className="p-8 text-center text-zinc-400">
                            No hay solicitudes de plan esperando revisión
                            <span className="block text-xs text-zinc-500 mt-1">
                                Aparecen acá cuando un alumno sube el comprobante de un plan desde su panel.
                            </span>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-amber-800 text-white">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Alumno</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Plan</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Precio</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Voucher</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Certificado</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Fecha</th>
                                        <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                    {solicitudes.map((s, idx) => (
                                        <tr key={s.id} className={idx % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                            <td className="px-6 py-4">
                                                <p className="text-sm font-bold text-zinc-100">{s.alumno_nombre}</p>
                                                <p className="text-xs text-zinc-400">{s.alumno_email}</p>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-100">{s.plan_nombre}</td>
                                            <td className="px-6 py-4 text-sm font-bold text-green-700">
                                                ${(s.precio_final ?? s.plan_precio ?? 0).toLocaleString('es-CL')}
                                                {/* F2: si la solicitud trae un beneficio, se dice el % y el
                                                    precio de lista (lo que el alumno va a pagar es el final). */}
                                                {s.descuento_pct != null && (
                                                    <span className="block text-[11px] font-medium text-amber-600"
                                                        data-testid={`beneficio-aplicado-${s.id}`}>
                                                        Beneficio aplicado: −{s.descuento_pct} %
                                                        <span className="ml-1 text-zinc-500 line-through">
                                                            ${(s.plan_precio || 0).toLocaleString('es-CL')}
                                                        </span>
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4">
                                                {s.voucher_url ? (
                                                    <button onClick={() => setVoucherModal({ open: true, solicitud_id: s.id, tipo: 'voucher' })}
                                                        className="text-blue-400 underline text-xs hover:text-blue-300">
                                                        📎 Ver Voucher
                                                    </button>
                                                ) : (
                                                    <span className="text-zinc-500 text-xs">Sin voucher</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4">
                                                {s.certificado_estudiante_url ? (
                                                    <button onClick={() => setVoucherModal({ open: true, solicitud_id: s.id, tipo: 'certificado' })}
                                                        className="text-amber-600 underline text-xs hover:text-amber-800">
                                                        🎓 Ver Certificado
                                                    </button>
                                                ) : (
                                                    <span className="text-zinc-500 text-xs">—</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-zinc-400">
                                                {s.created_at ? new Date(s.created_at).toLocaleDateString('es-CL') : '-'}
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex gap-2">
                                                    <button onClick={() => handleAprobar(s.id)}
                                                        disabled={processingId === s.id}
                                                        className="px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-bold hover:bg-green-700 disabled:opacity-50">
                                                        {processingId === s.id ? '...' : '✅ Aprobar'}
                                                    </button>
                                                    <button onClick={() => setRechazoModal({ open: true, solicitud_id: s.id, motivo: '' })}
                                                        disabled={processingId === s.id}
                                                        className="px-3 py-1.5 bg-red-600 text-white rounded-lg text-xs font-bold hover:bg-red-700 disabled:opacity-50">
                                                        {processingId === s.id ? '...' : '❌ Rechazar'}
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* 1b. El detalle de PAGOS DEL DÍA se movió arriba: se ancla a la tarjeta
                    "Ingresos de hoy" y se despliega allí (bloque 9), para no duplicar
                    la sección ni obligar a bajar hasta el final. */}

                {/* 2. FINANCIERA Y DE NEGOCIO */}
                {stats && (
                    <section aria-labelledby="dashboard-negocio" className="space-y-3">
                        <div>
                            <h2 id="dashboard-negocio" className="text-lg font-bold text-zinc-100">
                                Finanzas y negocio
                            </h2>
                            <p className="text-xs text-zinc-500">
                                Alumnos, membresías e ingresos del mes
                            </p>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                            <button onClick={() => navigate('/admin/alumnos?estado=activo')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-blue-600 hover:shadow-md hover:border-blue-700 transition-all cursor-pointer text-left">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos Activos</p>
                                <p className="text-3xl font-bold text-blue-400 mt-1">{resumenAdmin.alumnosActivos ?? 'n/d'}</p>
                                <p className="text-xs text-zinc-500 mt-1">Hoy · suscripciones vigentes (en vivo) — Clic para ver el padrón activo</p>
                            </button>
                            <button onClick={() => setFidelizacionModal('membresias')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-green-600 hover:shadow-md hover:border-green-700 transition-all cursor-pointer text-left">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Membresías Mensuales</p>
                                <p className="text-3xl font-bold text-green-700 mt-1">{stats.totalSuscripcionesMes || 0}</p>
                                <p className="text-xs text-zinc-500 mt-1">Suscripciones iniciadas este mes (incluye pruebas) — Clic para ver detalle</p>
                            </button>
                            <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-amber-600">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Ingreso Mensual</p>
                                <p className="text-3xl font-bold text-amber-700 mt-1">
                                    ${(resumenAdmin.ingresoMes?.total_clp || 0).toLocaleString('es-CL')}
                                </p>
                                <p className="text-xs text-zinc-500 mt-1">Mes en curso · cobros aprobados (pagos)</p>
                                <p className="text-xs font-bold text-zinc-500 mt-1"
                                    title="El mes en curso no se compara contra un mes completo: no es el mismo tramo.">
                                    comparación: n/d
                                </p>
                            </div>
                            {/* Ventas del Bazar del mes: campo propio de /reportes/ (`ventasBazar`).
                                Es BRUTA y no recurrente: no está dentro de "Ingreso Mensual" (neto de
                                transacciones) ni del MRR.
                                La tarjeta abre PEDIDOS (/admin/pedidos), que es la venta REAL pedido a
                                pedido (comprobante, estado y total). Antes iba a
                                `/admin/reportes?seccion=bazar`, que sólo hacía scroll hasta este mismo
                                número en el informe de métricas: un clic para volver a leer la tarjeta. */}
                            <button onClick={() => navigate('/admin/pedidos')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-teal-600 hover:shadow-md hover:border-teal-700 transition-all cursor-pointer text-left">
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Ventas Bazar (mes)</p>
                                <p className="text-3xl font-bold text-teal-600 mt-1">
                                    ${(resumenAdmin.ventasBazar || 0).toLocaleString('es-CL')}
                                </p>
                                <p className="text-xs text-zinc-500 mt-1">
                                    {resumenAdmin.ventasBazarPedidos || 0} pedido{(resumenAdmin.ventasBazarPedidos || 0) === 1 ? '' : 's'} cobrado{(resumenAdmin.ventasBazarPedidos || 0) === 1 ? '' : 's'} del mes vía pagos
                                    {' · comparación: n/d (mes parcial)'}
                                </p>
                            </button>
                        </div>
                    </section>
                )}

                {/* 3. RETENCIÓN Y FIDELIZACIÓN: alertas tempranas, después de la
                    operativa y de los números de negocio. */}
                <section aria-labelledby="dashboard-retencion" className="space-y-3">
                    <div>
                        <h2 id="dashboard-retencion" className="text-lg font-bold text-zinc-100">
                            Retención y fidelización
                        </h2>
                        <p className="text-xs text-zinc-500">
                            Alertas tempranas para intervenir antes de perder al alumno
                        </p>
                    </div>
                    {/* El fallo se avisa ARRIBA y con Reintentar: las tarjetas ya muestran su
                    motivo en vez de un 0 falso, pero sin botón el admin tenía que
                    recargar la página entera para volver a intentar. */}
                {!fidelizacionLoading && (
                    <AvisoCarga
                        secciones={[
                            fidelizacionError.vencimientos && 'vencimientos inminentes',
                        ].filter(Boolean)}
                        variante="oscura"
                        testid="aviso-fidelizacion"
                        onReintentar={cargarFidelizacion}
                    />
                )}
                {!fidelizacionLoading && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Tarjeta Alumnos en Riesgo */}
                        <button onClick={() => navigate('/admin/fidelizacion?filtro=riesgo_activos')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-red-600 hover:shadow-md hover:border-red-700 transition-all cursor-pointer text-left">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos en riesgo</p>
                                    <p className="text-3xl font-bold text-red-700 mt-1">
                                        {resumenAdmin.alumnosRiesgo ?? 'n/d'}
                                    </p>
                                    <p className="text-xs text-zinc-500 mt-1">
                                        {resumenAdmin.riesgoPendiente
                                            ? 'pendiente de reentrenar — Clic para ir a Fidelización'
                                            : 'Hoy · crítico + alto entre los activos — Clic para ir a Fidelización'}
                                    </p>
                                </div>
                                <span className="text-4xl">⚠️</span>
                            </div>
                        </button>
                        {/* Tarjeta Vencimientos Inminentes */}
                        <button onClick={() => navigate('/admin/fidelizacion?filtro=plan_urgente')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-orange-600 hover:shadow-md hover:border-orange-700 transition-all cursor-pointer text-left">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Vencimientos Inminentes</p>
                                    {fidelizacionError.vencimientos ? (
                                        <p className="text-sm font-bold text-orange-400 mt-2">⚠️ {fidelizacionError.vencimientos}</p>
                                    ) : (
                                        <p className="text-3xl font-bold text-orange-700 mt-1">{vencimientos.length}</p>
                                    )}
                                    <p className="text-xs text-zinc-500 mt-1">Próximos 5 días — Clic para ir a Fidelización</p>
                                </div>
                                <span className="text-4xl">⏰</span>
                            </div>
                        </button>
                    </div>
                )}
                </section>

                {/* 4. CONVERSIÓN Y PROSPECTOS: el embudo de prueba a plan pagado
                    queda al final, como seguimiento y no como operativa del día. */}
                <section aria-labelledby="dashboard-conversion" className="space-y-3">
                    <div>
                        <h2 id="dashboard-conversion" className="text-lg font-bold text-zinc-100">
                            Conversión y prospectos
                        </h2>
                        <p className="text-xs text-zinc-500">
                            Alumnos de prueba del día y su paso a un plan pagado
                        </p>
                    </div>
                    {/* Tarjeta "Alumnos de Prueba Hoy" (solo panel admin) */}
                    <AdminTarjetaAlumnosPrueba />

                    {/* TARJETAS: "Alumnos nuevos de este mes" (endpoint operativo, mismo
                        número que el detalle) y "Convertidos" (BI mensual). La primera
                        abre la pantalla con los DOS listados (en prueba + altas del mes);
                        antes mandaba a /admin/kpis, que no era lo que el admin esperaba. */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <button onClick={() => navigate('/admin/alumnos-prueba')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-emerald-600 hover:shadow-md hover:border-emerald-700 transition-all cursor-pointer text-left">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos nuevos de este mes</p>
                                    {nuevosMesQ.isPending ? (
                                        <p className="text-3xl font-bold text-zinc-600 mt-1">…</p>
                                    ) : nuevosMesQ.isError ? (
                                        <p className="text-sm font-bold text-amber-400 mt-2" title={mensajeError(nuevosMesQ.error, 'No se pudieron cargar las altas del mes')}>
                                            ⚠️ s/d
                                        </p>
                                    ) : (
                                        <p className="text-3xl font-bold text-emerald-600 mt-1">{totalNuevosMes}</p>
                                    )}
                                    <p className="text-xs text-zinc-500 mt-1">
                                        {nuevosMesQ.isPending
                                            ? 'Consultando las altas del mes…'
                                            : nuevosMesQ.isError
                                                ? 'No se pudieron cargar las altas del mes'
                                                : `${convertidosNuevosMes} ya compraron plan · ${totalNuevosMes - convertidosNuevosMes} aún sin plan`}
                                        {!nuevosMesQ.isError && ' — Clic para ver el detalle'}
                                    </p>
                                </div>
                                <span className="text-4xl">👤</span>
                            </div>
                        </button>
                        <button
                            onClick={() => navigate(
                                `/admin/alumnos-convertidos?anio=${resumenAdmin.periodoAnio}&mes=${resumenAdmin.periodoMes}`)}
                            className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-teal-600 hover:shadow-md hover:border-teal-700 transition-all cursor-pointer text-left"
                        >
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Convertidos</p>
                                    {resumenAdmin.cargando ? (
                                        <p className="text-3xl font-bold text-zinc-600 mt-1">…</p>
                                    ) : resumenAdmin.planComprado === null ? (
                                        <p className="text-sm font-bold text-amber-400 mt-2">s/d</p>
                                    ) : (
                                        <p className="text-3xl font-bold text-teal-600 mt-1">{resumenAdmin.planComprado}</p>
                                    )}
                                    <p className="text-xs text-zinc-500 mt-1">
                                        {resumenAdmin.cargando
                                            ? 'Consultando el mes en curso…'
                                            : resumenAdmin.errores.mensual
                                                ? `⚠️ ${resumenAdmin.errores.mensual}`
                                                // MISMO período que la tarjeta "Conversión": mes en
                                                // curso. Ya no se mezcla un mes cerrado del BI.
                                                : `Compraron plan${resumenAdmin.periodoTexto ? ` (${resumenAdmin.periodoTexto})` : ''} · mes en curso`}
                                        {!resumenAdmin.errores.mensual && ' — Clic para ver el detalle'}
                                    </p>
                                </div>
                                <span className="text-4xl">🚀</span>
                            </div>
                        </button>
                    </div>
                </section>

            </div>

            {/* MODAL VOUCHER / CERTIFICADO */}
            {voucherModal.open && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setVoucherModal({ open: false, solicitud_id: null, tipo: 'voucher' })}>
                    <div className="bg-zinc-900 rounded-xl max-w-2xl max-h-[90vh] overflow-auto shadow-2xl"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">
                                {voucherModal.tipo === 'certificado' ? '🎓 Certificado de Estudiante' : '📎 Voucher de Pago'}
                            </h3>
                            <button onClick={() => setVoucherModal({ open: false, solicitud_id: null, tipo: 'voucher' })}
                                className="text-zinc-400 hover:text-zinc-300 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4 min-h-[12rem] flex items-center justify-center">
                            {voucherPreview.loading ? (
                                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                            ) : voucherPreview.error ? (
                                <div className="text-center py-6 space-y-3">
                                    <p className="text-red-400 text-sm">{voucherPreview.error}</p>
                                    <button type="button" onClick={reintentarVoucher}
                                        className="px-4 py-2 bg-zinc-700 text-zinc-100 rounded-lg hover:bg-zinc-600 text-sm font-bold">
                                        Reintentar
                                    </button>
                                </div>
                            ) : voucherPreview.blobUrl ? (
                                voucherPreview.mime.includes('pdf') ? (
                                    <iframe src={voucherPreview.blobUrl} className="w-full h-96" title="Documento PDF" />
                                ) : (
                                    <img src={voucherPreview.blobUrl} alt="Documento" className="w-full rounded-lg" />
                                )
                            ) : (
                                <p className="text-center text-zinc-500 text-sm py-6">Sin previsualización disponible</p>
                            )}
                        </div>
                        <div className="p-4 border-t flex justify-end gap-2">
                            <button onClick={() => handleDescargarDocumento(voucherModal.solicitud_id, voucherModal.tipo)}
                                disabled={descargandoVoucher}
                                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed">
                                {descargandoVoucher ? 'Descargando...' : '📥 Descargar'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* MODAL MEMBRESÍAS DEL MES
                Tres capas para que el scroll no sea del modal entero: la tarjeta fija el
                ancho y el alto, la cabecera no se mueve y SÓLO la lista scrollea. Antes
                `overflow-auto` estaba en el panel, así que la barra nativa quedaba pegada
                al borde y arrastraba el título al bajar. */}
            {fidelizacionModal === 'membresias' && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 sm:p-6"
                    onClick={() => setFidelizacionModal(null)}
                    role="presentation">
                    <div
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="membresias-mes-titulo"
                        className="flex max-h-[85dvh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl"
                        onClick={e => e.stopPropagation()}
                    >
                        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-zinc-700 px-5 py-4">
                            <div>
                                <h3 id="membresias-mes-titulo" className="font-bold text-zinc-100">
                                    📦 Membresías del Mes
                                </h3>
                                <p className="mt-0.5 text-xs text-zinc-500">
                                    {suscripcionesMes.length} suscripción
                                    {suscripcionesMes.length === 1 ? '' : 'es'}
                                    {' '}iniciada{suscripcionesMes.length === 1 ? '' : 's'}
                                    {' '}este mes
                                    {membresiasVisibles.length !== suscripcionesMes.length
                                        && ` · ${membresiasVisibles.length} con los filtros`}
                                    {' '}· Alumno, plan y fecha de inicio
                                </p>
                            </div>
                            <button type="button" onClick={() => setFidelizacionModal(null)}
                                aria-label="Cerrar membresías del mes"
                                className="shrink-0 rounded-lg px-1.5 text-xl font-bold text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200">
                                ✕
                            </button>
                        </div>
                        {/* FILTROS del listado: el mes trae cientos de filas. Buscador por
                            alumno, select de plan (con "Sin pruebas", que es lo que
                            interesa para vender) y orden por fecha. Todo en el cliente
                            sobre lo que ya vino en /admin/dashboard. */}
                        <div className="flex flex-col gap-2 border-b border-zinc-800 px-3 py-2.5 sm:flex-row sm:items-center sm:px-4">
                            <input
                                type="search"
                                value={busquedaMembresias}
                                onChange={(e) => setBusquedaMembresias(e.target.value)}
                                placeholder="Buscar alumno…"
                                aria-label="Buscar alumno en las membresías del mes"
                                className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-orange-500 focus:outline-none"
                            />
                            <div className="flex items-center gap-2">
                                <select
                                    value={planMembresias}
                                    onChange={(e) => setPlanMembresias(e.target.value)}
                                    aria-label="Filtrar por tipo de plan"
                                    className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-orange-500 focus:outline-none sm:flex-none"
                                >
                                    <option value={FILTRO_PLAN_TODOS}>Todos los planes</option>
                                    <option value={FILTRO_PLAN_SIN_PRUEBA}>Sin pruebas</option>
                                    {planesMembresias.map((nombre) => (
                                        <option key={nombre} value={nombre}>{nombre}</option>
                                    ))}
                                </select>
                                <button
                                    type="button"
                                    onClick={() => setOrdenMembresias((o) => (o === 'reciente' ? 'antigua' : 'reciente'))}
                                    title={ordenMembresias === 'reciente'
                                        ? 'Ordenado por fecha: más reciente primero (clic para invertir)'
                                        : 'Ordenado por fecha: más antigua primero (clic para invertir)'}
                                    className="shrink-0 rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-xs font-semibold text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                                >
                                    {ordenMembresias === 'reciente' ? '↓ Fecha' : '↑ Fecha'}
                                </button>
                            </div>
                        </div>
                        <div className="flex min-h-0 flex-1 flex-col px-3 py-3 sm:px-4 sm:py-4">
                            {/* Contenedor con scroll PROPIO (alto acotado por el flex y
                                barra separada del borde). La tabla tiene mínimo de 34rem:
                                en un teléfono scrollea en horizontal DENTRO de la tarjeta,
                                nunca desborda el modal. */}
                            <div className="min-h-0 w-full min-w-0 flex-1 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950/40 [scrollbar-gutter:stable]">
                                {suscripcionesMes.length === 0 ? (
                                    <p className="px-5 py-10 text-center text-zinc-500">
                                        No hay membresías vendidas este mes
                                    </p>
                                ) : membresiasVisibles.length === 0 ? (
                                    <div className="px-5 py-10 text-center text-zinc-500">
                                        <p>Ninguna membresía coincide con los filtros.</p>
                                        <button
                                            type="button"
                                            onClick={() => { setBusquedaMembresias(''); setPlanMembresias(FILTRO_PLAN_TODOS); }}
                                            className="mt-3 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                                        >
                                            Limpiar filtros
                                        </button>
                                    </div>
                                ) : (
                                    <table className="w-full min-w-[34rem] table-fixed text-sm">
                                        <thead className="sticky top-0 z-10 bg-zinc-800">
                                            <tr>
                                                <th className="w-[46%] px-3 py-2.5 text-left text-xs font-bold uppercase text-zinc-300 sm:px-4">Alumno</th>
                                                <th className="w-[32%] px-3 py-2.5 text-left text-xs font-bold uppercase text-zinc-300 sm:px-4">Plan</th>
                                                <th className="w-[22%] px-3 py-2.5 text-left text-xs font-bold uppercase text-zinc-300 sm:px-4">Fecha</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-zinc-800">
                                            {membresiasVisibles.map((s, idx) => (
                                                // El endpoint no manda id de suscripción: la fila no
                                                // se reordena entre renders (sale estable del filtro),
                                                // así que `idx` sirve de key.
                                                <tr key={idx} className="hover:bg-zinc-900/60">
                                                    <td className="break-words px-3 py-3 font-medium text-zinc-100 sm:px-4">{s.alumno_nombre}</td>
                                                    <td className="break-words px-3 py-3 text-green-400 sm:px-4">{s.plan_nombre}</td>
                                                    <td className="whitespace-nowrap px-3 py-3 tabular-nums text-zinc-400 sm:px-4">{s.fecha_inicio || '-'}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* MODAL DETALLE CLASE (alumnos): se abre al hacer clic en una fila de "Clases de hoy".
                Reutiliza GET /asistencia/clases/{id}/alumnos (mismos datos que el panel del coach). */}
            {claseDetalle && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setClaseDetalle(null)}>
                    <div className="bg-zinc-900 rounded-xl max-w-md w-full shadow-2xl"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b border-zinc-800 flex justify-between items-start">
                            <div>
                                <h3 className="font-bold text-zinc-100">
                                    {claseDetalle.disciplina_nombre} · {claseDetalle.hora_inicio?.slice(0, 5)}
                                </h3>
                                <p className="text-xs text-zinc-500 mt-0.5">
                                    {claseDetalle.coach ? `👤 ${claseDetalle.coach}` : '⚠️ Sin coach asignado'}
                                    {' '}· {claseDetalle.reservas_count || 0}
                                    {claseDetalle.cupo_maximo === null || claseDetalle.cupo_maximo === undefined
                                        ? ' reservas (acceso libre)'
                                        : `/${claseDetalle.cupo_maximo} reservas`}
                                </p>
                            </div>
                            <button onClick={() => setClaseDetalle(null)}
                                className="text-zinc-400 hover:text-zinc-200 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4 max-h-96 overflow-y-auto">
                            {detalleLoading ? (
                                <div className="flex justify-center py-8"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div></div>
                            ) : detalleReservas.length === 0 ? (
                                <p className="text-center text-sm text-zinc-500 py-8">Esta clase no tiene reservas activas.</p>
                            ) : (
                                <ul className="space-y-2">
                                    {detalleReservas.map(r => (
                                        <li key={r.reserva_id} className="flex items-center justify-between p-2.5 rounded-lg border border-zinc-800">
                                            <span className="text-sm text-zinc-200">{r.nombre}</span>
                                            <span className={`text-xs font-medium ${r.asistio ? 'text-green-400' : 'text-zinc-500'}`}>
                                                {r.asistio ? '✅ Asistió' : '—'}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                        <div className="px-4 py-3 border-t border-zinc-800 flex justify-end">
                            <button onClick={() => setClaseDetalle(null)}
                                className="px-4 py-2 bg-zinc-700 text-zinc-200 rounded-lg hover:bg-zinc-600 text-sm font-bold">
                                Cerrar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* MODAL RECHAZO */}
            {rechazoModal.open && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}>
                    <div className="bg-zinc-900 rounded-xl max-w-md w-full shadow-2xl"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">❌ Rechazar Solicitud</h3>
                            <button onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}
                                className="text-zinc-400 hover:text-zinc-300 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4 space-y-4">
                            <p className="text-sm text-zinc-400">Indica el motivo del rechazo:</p>
                            <textarea
                                value={rechazoModal.motivo}
                                onChange={e => setRechazoModal(prev => ({ ...prev, motivo: e.target.value }))}
                                placeholder="Voucher inválido, datos incorrectos, etc."
                                className="w-full p-3 border rounded-lg text-sm"
                                rows={3}
                            />
                            <div className="flex gap-2 justify-end">
                                <button onClick={() => setRechazoModal({ open: false, solicitud_id: null, motivo: '' })}
                                    className="px-4 py-2 bg-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-600 text-sm font-bold">
                                    Cancelar
                                </button>
                                <button onClick={() => {
                                    if (rechazoModal.motivo.trim()) {
                                        handleRechazar(rechazoModal.solicitud_id, rechazoModal.motivo.trim());
                                        setRechazoModal({ open: false, solicitud_id: null, motivo: '' });
                                    }
                                }}
                                    disabled={!rechazoModal.motivo.trim()}
                                    className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm font-bold disabled:opacity-50">
                                    Rechazar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

        </Layout>
    );
};

export default AdminDashboard;
