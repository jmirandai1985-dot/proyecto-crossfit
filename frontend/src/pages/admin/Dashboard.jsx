import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { fmtFechaChile, toChileFechaStr } from '../../utils/fecha';
import AdminTarjetaAlumnosPrueba from '../../components/AdminTarjetaAlumnosPrueba';
// Vista previa/descarga del voucher: la lógica del blob autenticado (y su
// descarga forzada) vive en el hook compartido, no en cada pantalla.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';

const AdminDashboard = () => {
    const navigate = useNavigate();
    const { tenant_id } = useAuth();
    const [solicitudes, setSolicitudes] = useState([]);
    const [countPendientes, setCountPendientes] = useState(0);
    // ── Pendientes: DOS colas distintas, cada una con su propio error ──────────
    // `countPendientes` = REGISTROS de alumnos nuevos (pendientes-activacion/count)
    // `solicitudes`     = SOLICITUDES DE PLAN con comprobante (/solicitudes/pendientes)
    // Antes la tarjeta del dashboard mostraba SOLO la primera: con 1 comprobante de
    // plan esperando revisión, el contador decía "0". Y si un endpoint fallaba, se
    // pintaba un 0 falso; ahora se muestra "s/d" + el motivo.
    const [registrosError, setRegistrosError] = useState('');
    const [solicitudesError, setSolicitudesError] = useState('');
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [processingId, setProcessingId] = useState(null);
    const [msg, setMsg] = useState('');
    const [voucherModal, setVoucherModal] = useState({ open: false, solicitud_id: null, tipo: 'voucher' });
    // Voucher AUTENTICADO: la vista previa y la descarga van por el endpoint
    // protegido GET /solicitudes/{id}/voucher (con Bearer) y se materializan como
    // blob (hook `useDocumentoAutenticado` más abajo). Así no se depende de la URL
    // pública /static/uploads/... (que se sirve sin autenticación por StaticFiles).
    const [rechazoModal, setRechazoModal] = useState({ open: false, solicitud_id: null, motivo: '' });
    // Fidelización state
    const [alumnosRiesgo, setAlumnosRiesgo] = useState([]);
    const [vencimientos, setVencimientos] = useState([]);
    const [fidelizacionLoading, setFidelizacionLoading] = useState(true);
    // Error POR TARJETA de fidelización: antes un Promise.all + catch mudo dejaba
    // ambas listas vacías y las tarjetas mostraban "0" como si no hubiera nadie en
    // riesgo (dato falso en un panel de churn).
    const [fidelizacionError, setFidelizacionError] = useState({ riesgo: '', vencimientos: '' });
    const [ocupacionHoy, setOcupacionHoy] = useState([]);
    const [ocupacionLoading, setOcupacionLoading] = useState(true);
    // Fidelización — modal membresías del mes
    const [fidelizacionModal, setFidelizacionModal] = useState(null); // 'membresias'
    // ── Tarjetas BI (data mart): "Alumnos nuevos" y "Convertidos" ─────────────
    // Reutilizan los MISMOS endpoints de la pestaña KPIs (/api/v1/kpis/diario y
    // /api/v1/kpis/mensual) — no se recalcula nada acá. Si el job BI todavía no
    // publicó el día/mes, la tarjeta dice "s/d" con el motivo, nunca un 0 falso.
    const [biNuevos, setBiNuevos] = useState({ loading: true, valor: null, fecha: '', error: '' });
    const [biConversion, setBiConversion] = useState({
        loading: true, valor: null, prueba: null, rate: null, periodo: '', error: '',
    });

    useEffect(() => {
        cargarSolicitudes();
        cargarCountPendientes();
        cargarFidelizacion();
        cargarOcupacionHoy();
        cargarBi();
    }, [tenant_id]);

    const cargarOcupacionHoy = async () => {
        setOcupacionLoading(true);
        try {
            const res = await api.get(`/api/v1/dashboard/${tenant_id}/ocupacion-hoy`);
            setOcupacionHoy(res.data || []);
        } catch { setOcupacionHoy([]); }
        setOcupacionLoading(false);
    };

    const cargarStats = async () => {
        try {
            const res = await api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`);
            setStats(res.data);
        } catch (e) {
            console.error('Error cargando estadisticas del dashboard', e);
            setStats(null);
        }
    };

    const cargarSolicitudes = async () => {
        // Fetch INDEPENDIENTES (antes un Promise.all): si /solicitudes/pendientes
        // fallaba, el catch dejaba stats=null y NO se dibujaba ninguna tarjeta.
        // Con allSettled un fallo parcial no tumba el resto de la pantalla.
        const [sols, statsRes] = await Promise.allSettled([
            api.get(`/api/v1/solicitudes/pendientes`),
            api.get(`/api/v1/reportes/?tenant_id=${tenant_id}`)
        ]);
        if (sols.status === 'fulfilled') {
            setSolicitudes(sols.value.data || []);
            setSolicitudesError('');
        } else {
            console.error('Error cargando solicitudes pendientes', sols.reason);
            setSolicitudes([]);
            setSolicitudesError(sols.reason?.response?.data?.detail
                || sols.reason?.message
                || 'No se pudieron cargar las solicitudes de plan');
        }
        if (statsRes.status === 'fulfilled') {
            setStats(statsRes.value.data);
        } else {
            // No se pisa un stats ya cargado por cargarStats().
            console.error('Error cargando estadisticas del dashboard', statsRes.reason);
        }
        setLoading(false);
    };

    const cargarCountPendientes = async () => {
        try {
            const res = await api.get('/api/v1/alumnos/pendientes-activacion/count');
            setCountPendientes(res.data?.count || 0);
            setRegistrosError('');
        } catch (err) {
            // Un fallo de red NO es "no hay nada pendiente": se guarda el motivo y
            // la tarjeta muestra "s/d" en vez de un 0 tranquilizador pero falso.
            console.error('Error cargando el conteo de registros pendientes', err);
            setCountPendientes(0);
            setRegistrosError(err?.response?.data?.detail || err?.message
                || 'No se pudo cargar el dato');
        }
    };

    // ── BI (SOLO LECTURA): "Alumnos nuevos" y "Convertidos" ───────────────────
    // Mismo criterio que la pestaña KPIs: el cron `box-crossfit-kpis-ml` publica el
    // día ANTERIOR, así que se pide ayer y, si el job todavía no corrió, se
    // retrocede hasta 3 días. El mensual usa el ÚLTIMO MES CERRADO con datos
    // (índice /kpis/mensual/periodos -> `default`), no el mes en curso (vacío).
    const cargarBi = async () => {
        setBiNuevos((prev) => ({ ...prev, loading: true }));
        const dias = [];
        for (let i = 1; i <= 3; i++) {
            const d = new Date();
            d.setDate(d.getDate() - i);
            dias.push(toChileFechaStr(d));
        }
        const res = await Promise.allSettled(
            dias.map((fecha) => api.get('/api/v1/kpis/diario', { params: { fecha } }))
        );
        const ok = res.find((r) => r.status === 'fulfilled');
        if (ok) {
            setBiNuevos({
                loading: false,
                valor: ok.value.data?.alumnos_nuevos ?? null,
                fecha: ok.value.data?.fecha || '',
                error: '',
            });
        } else {
            setBiNuevos({
                loading: false, valor: null, fecha: '',
                error: res[0]?.reason?.response?.data?.detail
                    || 'Sin dato del BI para los últimos días',
            });
        }

        setBiConversion((prev) => ({ ...prev, loading: true }));
        try {
            const rPer = await api.get('/api/v1/kpis/mensual/periodos');
            const pedido = rPer.data?.default || null;
            if (!pedido) {
                setBiConversion({
                    loading: false, valor: null, prueba: null, rate: null, periodo: '',
                    error: 'Aún no hay meses cerrados publicados por el BI',
                });
                return;
            }
            const r = await api.get('/api/v1/kpis/mensual', {
                params: { year: pedido.year, month: pedido.month },
            });
            setBiConversion({
                loading: false,
                valor: r.data?.alumnos_plan_comprado ?? null,
                prueba: r.data?.alumnos_prueba ?? null,
                rate: r.data?.conversion_rate ?? null,
                periodo: `${String(pedido.month).padStart(2, '0')}/${pedido.year}`,
                error: '',
            });
        } catch (err) {
            setBiConversion({
                loading: false, valor: null, prueba: null, rate: null, periodo: '',
                error: err?.response?.data?.detail || err?.message
                    || 'No se pudo cargar el BI mensual',
            });
        }
    };

    const cargarFidelizacion = async () => {
        // Promise.allSettled (antes Promise.all + catch mudo): si un endpoint falla,
        // el otro se sigue mostrando y la tarjeta afectada indica el error en vez de
        // mostrar "0" como si todo estuviera bien. Mismo patrón que cargarSolicitudes().
        setFidelizacionLoading(true);
        const [riesgoRes, vencRes] = await Promise.allSettled([
            api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/en-riesgo`),
            api.get(`/api/v1/fidelizacion/tenant/${tenant_id}/vencimientos`)
        ]);
        if (riesgoRes.status === 'fulfilled') {
            setAlumnosRiesgo(riesgoRes.value.data?.alumnos_alerta || []);
            setFidelizacionError(prev => ({ ...prev, riesgo: '' }));
        } else {
            console.error('Error cargando alumnos en riesgo', riesgoRes.reason);
            setAlumnosRiesgo([]);
            setFidelizacionError(prev => ({
                ...prev,
                riesgo: riesgoRes.reason?.response?.data?.detail
                    || riesgoRes.reason?.message
                    || 'No se pudo cargar el dato',
            }));
        }
        if (vencRes.status === 'fulfilled') {
            setVencimientos(vencRes.value.data?.alumnos || []);
            setFidelizacionError(prev => ({ ...prev, vencimientos: '' }));
        } else {
            console.error('Error cargando vencimientos', vencRes.reason);
            setVencimientos([]);
            setFidelizacionError(prev => ({
                ...prev,
                vencimientos: vencRes.reason?.response?.data?.detail
                    || vencRes.reason?.message
                    || 'No se pudo cargar el dato',
            }));
        }
        setFidelizacionLoading(false);
    };

    const handleAprobar = async (id) => {
        setProcessingId(id);
        setMsg('');
        try {
            await api.put(`/api/v1/solicitudes/${id}/aprobar`);
            setMsg(`✅ Solicitud #${id} aprobada. Tokens asignados.`);
            setTimeout(() => setMsg(''), 4000);
            cargarSolicitudes();
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
            await api.put(`/api/v1/solicitudes/${id}/rechazar?motivo=${encodeURIComponent(motivo)}`);
            setMsg(`✅ Solicitud #${id} rechazada.`);
            setTimeout(() => setMsg(''), 4000);
            cargarSolicitudes();
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
        const res = await descargarDocumento(
            `/api/v1/solicitudes/${solicitud_id}/${certificado ? 'certificado' : 'voucher'}`);
        setMsg(res.ok
            ? (certificado ? '✅ Certificado descargado.' : '✅ Voucher descargado.')
            : '❌ ' + res.error);
        setTimeout(() => setMsg(''), 4000);
    };

    // Pendientes por revisar = REGISTROS de alumno nuevo + SOLICITUDES DE PLAN con
    // comprobante (dos colas distintas). Si falló cualquiera de las dos fuentes se
    // devuelve null y la tarjeta muestra "s/d" en vez de un total incompleto.
    const totalPendientes = (registrosError || solicitudesError)
        ? null
        : (countPendientes || 0) + solicitudes.length;

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4" />
                    <p className="text-zinc-400">Cargando...</p>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-zinc-100">Dashboard Administrativo</h1>
                        <p className="text-zinc-400">Panel de gestión de membresías y fidelización</p>
                    </div>
                    <button onClick={() => { cargarSolicitudes(); cargarCountPendientes(); cargarFidelizacion(); cargarBi(); }} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-bold">
                        🔄 Recargar
                    </button>
                </div>

                {/* Tarjeta "Alumnos de Prueba Hoy" (solo panel admin) */}
                <AdminTarjetaAlumnosPrueba />

                {msg && (
                    <div className={`p-4 rounded-lg font-bold shadow-lg transition-all ${msg.includes('✅') ? 'bg-green-100 text-green-800' : msg.includes('❌') ? 'bg-red-100 text-red-800' : 'bg-blue-500/20 text-blue-300'}`}>
                        {msg}
                    </div>
                )}

                {/* TARJETAS DE ESTADÍSTICAS */}
                {stats && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
                        <button onClick={() => navigate('/admin/alumnos')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-blue-600 hover:shadow-md hover:border-blue-700 transition-all cursor-pointer text-left">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos Activos</p>
                            <p className="text-3xl font-bold text-blue-400 mt-1">{stats.alumnosActivos || 0}</p>
                            <p className="text-xs text-zinc-500 mt-1">Total miembros con plan vigente — Clic para ver</p>
                        </button>
                        <button onClick={() => setFidelizacionModal('membresias')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-green-600 hover:shadow-md hover:border-green-700 transition-all cursor-pointer text-left">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Membresías Mensuales</p>
                            <p className="text-3xl font-bold text-green-700 mt-1">{stats.totalSuscripcionesMes || 0}</p>
                            <p className="text-xs text-zinc-500 mt-1">Suscripciones iniciadas este mes — Clic para ver detalle</p>
                        </button>
                        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-amber-600">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Ingreso Mensual</p>
                            <p className="text-3xl font-bold text-amber-700 mt-1">
                                ${(stats.ingresoMensual || 0).toLocaleString('es-CL')}
                            </p>
                            <p className="text-xs text-zinc-500 mt-1">Ingresos del mes actual</p>
                            {/* El MoM es de INGRESOS: antes estaba mal ubicado en la tarjeta
                                de membresias, donde se leia como crecimiento de suscripciones. */}
                            {stats.crecimientoMensual === null ? (
                                <p className="text-xs font-bold text-zinc-500 mt-1"
                                    title="Sin mes anterior comparable: el ingreso neto del mes pasado fue <= 0.">
                                    s/d vs mes anterior (sin base comparable)
                                </p>
                            ) : (
                                <p className={`text-xs font-bold mt-1 ${stats.crecimientoMensual > 0 ? 'text-green-600' : stats.crecimientoMensual < 0 ? 'text-red-600' : 'text-zinc-500'}`}>
                                    {stats.crecimientoMensual > 0 ? '📈' : stats.crecimientoMensual < 0 ? '📉' : '='}{' '}
                                    {Math.abs(stats.crecimientoMensual ?? 0)}% vs mes anterior
                                </p>
                            )}
                        </div>
                        {/* Ventas del Bazar del mes: campo propio de /reportes/ (`ventasBazar`).
                            Es BRUTA y no recurrente: no está dentro de "Ingreso Mensual" (neto de
                            transacciones) ni del MRR. */}
                        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-teal-600">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Ventas Bazar (mes)</p>
                            <p className="text-3xl font-bold text-teal-600 mt-1">
                                ${(stats.ventasBazar || 0).toLocaleString('es-CL')}
                            </p>
                            <p className="text-xs text-zinc-500 mt-1">Pedidos cobrados del mes</p>
                        </div>
                        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-purple-600">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide"
                                title="Ocupacion: clases.asistentes_confirmados / clases.cupo_maximo (lugares reservados sobre cupo ofrecido). NO mide asistencia real. Puede verse 0% porque las asistencias todavia no estan vinculadas a su clase (asistencias.clase_id es NULL en toda la base).">Ocupación promedio</p>
                            <p className="text-3xl font-bold text-purple-700 mt-1">{stats.asistenciaPromedio || 0}%</p>
                            <p className="text-xs text-zinc-500 mt-1">Ocupación en clases</p>
                        </div>
                        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-indigo-600">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Clases Impartidas</p>
                            <p className="text-3xl font-bold text-indigo-700 mt-1">{stats.clasesImpartidas || 0}</p>
                            <p className="text-xs text-zinc-500 mt-1">Clases realizadas este mes</p>
                        </div>
                        <button onClick={() => document.getElementById('solicitudes-pendientes')?.scrollIntoView({ behavior: 'smooth' })} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-rose-600 hover:shadow-md hover:border-rose-700 transition-all cursor-pointer text-left">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Solicitudes Pendientes</p>
                            {totalPendientes === null ? (
                                <p className="text-sm font-bold text-rose-400 mt-2" title={registrosError || solicitudesError}>
                                    ⚠️ s/d (no se pudo consultar)
                                </p>
                            ) : (
                                <p className="text-3xl font-bold text-rose-700 mt-1">{totalPendientes}</p>
                            )}
                            {/* Desglose: son DOS colas. Antes solo se contaban los registros
                                y una solicitud de plan con voucher no sumaba en ninguna parte. */}
                            <p className="text-xs text-zinc-500 mt-1">
                                {countPendientes || 0} registro{countPendientes === 1 ? '' : 's'} ·
                                {' '}{solicitudes.length} solicitud{solicitudes.length === 1 ? '' : 'es'} de plan — Clic para ver
                            </p>
                        </button>
                    </div>
                )}

                {/* TARJETAS BI: "Alumnos nuevos" y "Convertidos". Reutilizan los
                    endpoints de /admin/kpis (el cálculo vive en el backend, en los
                    data marts daily_kpis/monthly_kpis): acá solo se pinta el número. */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <button onClick={() => navigate('/admin/kpis')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-emerald-600 hover:shadow-md hover:border-emerald-700 transition-all cursor-pointer text-left">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos Nuevos</p>
                                {biNuevos.loading ? (
                                    <p className="text-3xl font-bold text-zinc-600 mt-1">…</p>
                                ) : biNuevos.valor === null ? (
                                    <p className="text-sm font-bold text-amber-400 mt-2">s/d</p>
                                ) : (
                                    <p className="text-3xl font-bold text-emerald-600 mt-1">{biNuevos.valor}</p>
                                )}
                                <p className="text-xs text-zinc-500 mt-1">
                                    {biNuevos.loading
                                        ? 'Consultando el BI…'
                                        : biNuevos.error
                                            ? `⚠️ ${biNuevos.error === 'KPI diario no encontrado' ? 'el BI todavía no publicó esos días' : biNuevos.error}`
                                            : `Registros nuevos del ${fmtFechaChile(biNuevos.fecha)}`}
                                    {' '}— Clic para ver KPIs
                                </p>
                            </div>
                            <span className="text-4xl">👤</span>
                        </div>
                    </button>
                    <button onClick={() => navigate('/admin/kpis')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-teal-600 hover:shadow-md hover:border-teal-700 transition-all cursor-pointer text-left">
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Convertidos</p>
                                {biConversion.loading ? (
                                    <p className="text-3xl font-bold text-zinc-600 mt-1">…</p>
                                ) : biConversion.valor === null ? (
                                    <p className="text-sm font-bold text-amber-400 mt-2">s/d</p>
                                ) : (
                                    <p className="text-3xl font-bold text-teal-600 mt-1">{biConversion.valor}</p>
                                )}
                                <p className="text-xs text-zinc-500 mt-1">
                                    {biConversion.loading
                                        ? 'Consultando el BI…'
                                        : biConversion.error
                                            ? `⚠️ ${biConversion.error}`
                                            : `Compraron plan${biConversion.periodo ? ` (${biConversion.periodo})` : ''} · Conversión prueba→plan: ${biConversion.rate}% · ${biConversion.prueba || 0} en prueba`}
                                    {' '}— Clic para ver KPIs
                                </p>
                            </div>
                            <span className="text-4xl">🚀</span>
                        </div>
                    </button>
                </div>

                {/* WIDGET OCUPACION CLASES HOY */}
                <div className="bg-zinc-900 rounded-lg shadow p-5">
                    <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2">
                        📅 Clases de hoy — estado de ocupación
                    </h2>
                    <p className="text-xs text-zinc-400 mt-0.5">CrossFit y Levantamiento Olímpico, solo clases con coach asignado</p>
                    {ocupacionLoading ? (
                        <div className="flex justify-center py-6"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-900"></div></div>
                    ) : ocupacionHoy.length === 0 ? (
                        <div className="py-6 text-center text-zinc-500 text-sm">Sin clases de CrossFit/Levantamiento con coach asignado hoy</div>
                    ) : (
                        <div className="mt-4 space-y-3">
                            {ocupacionHoy.map(c => (
                                <div key={c.id} className="flex items-center gap-4">
                                    <div className="text-sm font-semibold text-zinc-300 w-16 shrink-0">{c.hora} hrs</div>
                                    <div className="flex-1 bg-zinc-800 rounded-full h-4 overflow-hidden">
                                        <div className={`h-full rounded-full transition-all ${c.color === 'red' ? 'bg-red-500' : c.color === 'amber' ? 'bg-amber-500' : 'bg-green-500'}`}
                                            style={{ width: `${Math.min(c.porcentaje, 100)}%` }} />
                                    </div>
                                    <div className="text-sm text-zinc-400 w-20 shrink-0">{c.ocupados}/{c.cupo}</div>
                                    <div className="text-sm font-semibold w-14 shrink-0">{c.porcentaje}%</div>
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium shrink-0
                                        ${c.color === 'red' ? 'bg-red-100 text-red-800' :
                                            c.color === 'amber' ? 'bg-amber-100 text-amber-800' :
                                                'bg-green-100 text-green-800'}`}>
                                        {c.estado}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* TARJETAS DE FIDELIZACIÓN */}
                {!fidelizacionLoading && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Tarjeta Alumnos en Riesgo */}
                        <button onClick={() => navigate('/admin/fidelizacion')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-red-600 hover:shadow-md hover:border-red-700 transition-all cursor-pointer text-left">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide">Alumnos en Riesgo</p>
                                    {fidelizacionError.riesgo ? (
                                        <p className="text-sm font-bold text-red-400 mt-2">⚠️ {fidelizacionError.riesgo}</p>
                                    ) : (
                                        <p className="text-3xl font-bold text-red-700 mt-1">{alumnosRiesgo.length}</p>
                                    )}
                                    <p className="text-xs text-zinc-500 mt-1">Sin actividad {'>'} 7 días — Clic para ir a Fidelización</p>
                                </div>
                                <span className="text-4xl">⚠️</span>
                            </div>
                        </button>
                        {/* Tarjeta Vencimientos Inminentes */}
                        <button onClick={() => navigate('/admin/fidelizacion')} className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-orange-600 hover:shadow-md hover:border-orange-700 transition-all cursor-pointer text-left">
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
                            onClick={() => navigate('/admin/alumnos-pendientes')}
                            className="shrink-0 px-3 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-semibold transition-colors"
                            title="Ver también los registros de alumnos nuevos pendientes"
                        >
                            Ver registros pendientes ({countPendientes || 0})
                        </button>
                    </div>
                    {solicitudesError ? (
                        <div className="p-8 text-center">
                            <p className="text-red-400 text-sm">⚠️ {solicitudesError}</p>
                            <button
                                onClick={cargarSolicitudes}
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
                                <p className="text-center text-red-400 text-sm py-6">{voucherPreview.error}</p>
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

            {/* MODAL MEMBRESÍAS DEL MES */}
            {fidelizacionModal === 'membresias' && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    onClick={() => setFidelizacionModal(null)}>
                    <div className="bg-zinc-900 rounded-xl max-w-2xl max-h-[90vh] overflow-auto shadow-2xl border border-zinc-700"
                        onClick={e => e.stopPropagation()}>
                        <div className="p-4 border-b border-zinc-700 flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">📦 Membresías del Mes</h3>
                            <button onClick={() => setFidelizacionModal(null)}
                                className="text-zinc-400 hover:text-zinc-200 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4">
                            {!stats?.suscripcionesMes || stats.suscripcionesMes.length === 0 ? (
                                <p className="text-center text-zinc-500 py-6">No hay membresías vendidas este mes</p>
                            ) : (
                                    <table className="w-full">
                                        <thead className="bg-zinc-800">
                                            <tr>
                                                <th className="px-4 py-2 text-left text-xs font-bold text-zinc-300 uppercase">Alumno</th>
                                                <th className="px-4 py-2 text-left text-xs font-bold text-zinc-300 uppercase">Plan</th>
                                                <th className="px-4 py-2 text-left text-xs font-bold text-zinc-300 uppercase">Fecha</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-zinc-800">
                                            {(stats.suscripcionesMes || []).map((s, idx) => (
                                                <tr key={idx}>
                                                    <td className="px-4 py-2.5 text-sm font-medium text-zinc-100">{s.alumno_nombre}</td>
                                                    <td className="px-4 py-2.5 text-sm text-green-400">{s.plan_nombre}</td>
                                                    <td className="px-4 py-2.5 text-sm text-zinc-400">{s.fecha_inicio || '-'}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                            )}
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
