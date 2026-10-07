import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import AlumnoFichaModal from '../../components/AlumnoFichaModal';
import { RiskBadge } from '../../components/kpis/RiskBadge';
import RecomendacionModal from '../../components/kpis/RecomendacionModal';
import { ARQUETIPOS_UI, estiloArquetipo, arquetipoDe } from '../../components/kpis/arquetipoEstilo';
import { KpiCard } from '../../components/kpis/KpiCard';
import { ArquetipoBadge } from '../../components/kpis/ArquetipoBadge';
import ModalEnviarCorreo from '../../components/ModalEnviarCorreo';
import BeneficioModal from '../../components/BeneficioModal';
import BeneficiosPanel from '../../components/BeneficiosPanel';
import { TabBar } from '../../components/kpis/TabBar';
import { Eye, TriangleAlert, Users, Sparkles, Gift, Mail } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

/** ISO local (YYYY-MM-DD) para comparar contra fecha_proxima_renovacion. */
const toISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// "14 sep 23:27" (hora local) para la fecha del modelo de segmentación.
const MESES_HORA = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
    'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const fmtFechaHora = (iso) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${d.getDate()} ${MESES_HORA[d.getMonth()]} ${hh}:${mm}`;
};

// ── Filtros de la tabla ────────────────────────────────────────────────
// Los activa la pestaña BI por query param (KPIs es solo lectura y manda
// acá la lista ya enfocada): ?filtro=critico|alto|total|plan_urgente y/o
// ?arquetipo=CODE. Es el MISMO panel (GET /kpis/churn), filtrado client-side
// con los datos que la fila ya trae: no hay endpoint nuevo.
const FILTROS = {
    critico: {
        etiqueta: 'Abandono crítico',
        test: (p) => p.riesgo_nivel === 'CRITICO',
    },
    alto: {
        etiqueta: 'Riesgo alto',
        test: (p) => p.riesgo_nivel === 'ALTO',
    },
    total: {
        etiqueta: 'En riesgo (todos)',
        test: (p) => ['ALTO', 'CRITICO'].includes(p.riesgo_nivel),
    },
    plan_urgente: {
        // "Vencimientos inminentes": el plan vigente vence en ≤ 5 días. Es EXACTAMENTE el
        // criterio de la tarjeta del mismo nombre (la tarjeta usa este `test` para contar), así
        // que al clickearla la tabla muestra tantas filas como dice el número. Antes pedía además
        // riesgo ALTO/CRÍTICO: la tarjeta contaba 37 y la tabla mostraba 1.
        etiqueta: 'Vencimientos inminentes (≤ 5 días)',
        test: (p) => {
            const f = p.fecha_proxima_renovacion
                ? String(p.fecha_proxima_renovacion).slice(0, 10) : null;
            if (!f) return false;
            const limite = new Date();
            limite.setDate(limite.getDate() + 5);
            return f >= toISO(new Date()) && f <= toISO(limite);
        },
    },
};

// Pestañas de la pantalla. Los ids viajan en `?tab=` (TabBar) y el resto de la URL (los filtros)
// se conserva al cambiar de pestaña.
const TABS = [
    { id: 'gestion', label: 'Gestión' },
    { id: 'beneficios', label: 'Beneficios' },
];

const Fidelizacion = () => {
    const { tenant_id } = useAuth();
    // Filtros que llegan desde la pestaña BI (?filtro=... y/o ?arquetipo=...).
    const [searchParams, setSearchParams] = useSearchParams();
    // Pestaña activa: Gestión (la tabla de siempre) o Beneficios (todos los regalos del box).
    const tab = searchParams.get('tab') || 'gestion';
    // Datos del BI (GET /kpis/churn): score, motivo, recomendación, gestión.
    const [churn, setChurn] = useState(null);
    // Segmentación (conteos por arquetipo) para las 6 tarjetas de abajo.
    const [segmentacion, setSegmentacion] = useState(null);
    const [segError, setSegError] = useState(false);
    const [loading, setLoading] = useState(true);
    // Búsqueda server-side (nombre o correo) de la tabla: input con debounce (350ms,
    // igual que Alumnos.jsx). `buscar` es el término YA aplicado (el que viaja al
    // backend); los filtros de riesgo/arquetipo se combinan ENCIMA de su resultado.
    const [searchTerm, setSearchTerm] = useState('');
    const [buscar, setBuscar] = useState('');
    // Alumno al que se le va a mandar un correo: abre el modal de envío (F1).
    const [alumnoCorreo, setAlumnoCorreo] = useState(null);
    // Alumno al que se le va a DAR un beneficio: abre el modal de la F2.
    const [alumnoBeneficio, setAlumnoBeneficio] = useState(null);
    // Sugerencia de plantilla por alumno (`POST /fidelizacion/sugerencias`): es la MISMA regla
    // que usa el modal de envío, así la columna "Recomendación" y la plantilla propuesta no
    // pueden decir cosas distintas.
    const [sugerencias, setSugerencias] = useState({});
    const [fichaAlumnoId, setFichaAlumnoId] = useState(null);
    const [detalleReco, setDetalleReco] = useState(null);
    const [msg, setMsg] = useState('');
    // Navegación al Historial del alumno (`/admin/alumnos/:id/historial`): desde la ficha
    // el admin entra a la MISMA pantalla "Mi historial" que ve el alumno (con la gestión
    // del box, incluida la pestaña Bazar), reutilizando `PanelHistorial`.
    const navigate = useNavigate();

    // Trae la tabla del churn (+ sugerencias de esa misma lista, en UNA petición).
    // `spinner` sólo en la carga completa: al BUSCAR no se tapa la pantalla (sin parpadeo).
    const cargarChurn = async (termino, { spinner = false } = {}) => {
        if (spinner) setLoading(true);
        try {
            // `buscar` es server-side (nombre o correo, sin mayúsculas ni tildes).
            const res = await api.get('/api/v1/kpis/churn', {
                params: { buscar: termino || undefined },
            });
            setChurn(res.data);
            setMsg('');
            // La sugerencia de plantilla de TODA la tabla, en UNA petición: la columna
            // "Recomendación" y el modal de envío salen de la MISMA regla del backend
            // (`sugerir()`), que es la única forma de que no digan cosas distintas.
            const ids = (res.data?.predicciones || []).map((p) => p.usuario_id).slice(0, 300);
            if (ids.length) {
                try {
                    const rSug = await api.post('/api/v1/fidelizacion/sugerencias',
                        { alumno_ids: ids });
                    setSugerencias(rSug?.data?.sugerencias || {});
                } catch {
                    // Sin sugerencias la tabla sigue (esa columna queda en "—"): el panel no se
                    // cae por una comodidad.
                    setSugerencias({});
                }
            } else {
                setSugerencias({});
            }
        } catch (err) {
            setChurn(null);
            setMsg('❌ ' + (err.response?.data?.detail || err.message || 'No se pudo cargar el panel'));
        } finally {
            if (spinner) setLoading(false);
        }
    };

    // Segmentación: opcional (si falla o no se entrenó, las tarjetas de arquetipo no se
    // muestran y el resto del panel sigue igual). Se pide aparte: NO depende de la
    // búsqueda. Se distingue "falló el fetch" (error) de "respondió bien pero todavía no
    // hay nada generado" (total 0): antes un .catch(() => null) dejaba los dos casos
    // idénticos y el bloque de las 6 tarjetas se ocultaba sin ningún aviso.
    const cargarSegmentacion = async () => {
        try {
            const rSeg = await api.get('/api/v1/segmentacion');
            setSegmentacion(rSeg?.data || null);
            setSegError(false);
        } catch {
            setSegmentacion(null);
            setSegError(true);
        }
    };

    // Carga completa (montaje / cambio de tenant / botón Recargar): tabla + segmentación.
    const cargarFidelizacion = async () => {
        setLoading(true);
        await Promise.all([cargarChurn(buscar), cargarSegmentacion()]);
        setLoading(false);
    };

    useEffect(() => {
        cargarFidelizacion();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tenant_id]);

    // Al cambiar el término BUSCADO (ya debounced) se re-trae SÓLO la tabla, sin spinner.
    // La carga inicial ya la cubre el efecto de arriba (`churn` todavía es null).
    useEffect(() => {
        if (churn === null) return;
        cargarChurn(buscar);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [buscar]);

    // Debounce del input (350ms): no dispara una request por tecla.
    useEffect(() => {
        const t = setTimeout(() => setBuscar(searchTerm.trim()), 350);
        return () => clearTimeout(t);
    }, [searchTerm]);

    // Enviar correo (F1): abre el modal con la plantilla sugerida. La sugerencia la resuelve el
    // BACKEND con los datos del alumno (`POST /fidelizacion/sugerir`) y la pantalla le pasa la que
    // ya trajo en lote (`/sugerencias`), así el modal arranca con EXACTAMENTE lo que muestra la
    // columna "Recomendación" de esta misma tabla.
    const enviarCorreoManual = (alumno) => {
        setMsg('');
        setAlumnoCorreo({ fila: alumno });
    };

    // Dar beneficio (F2): abre el modal que crea el regalo (y, si se pide, avisa por correo).
    const darBeneficio = (alumno) => {
        setMsg('');
        setAlumnoBeneficio({ fila: alumno });
    };

    // El beneficio quedó dado: se avisa en el cartel de la pantalla (la pestaña Beneficios lo
    // muestra al recargar) y se dice CÓMO se avisó al alumno.
    const beneficioDado = (resultado) => {
        const b = resultado?.beneficio || {};
        const entrega = b.unidad === 'pct' ? `−${b.valor} %` : `${b.valor} clases`;
        let correo = 'sin avisar por correo';
        if (resultado?.correo) {
            correo = resultado.correo.estado === 'fallido'
                ? 'el correo no salió'
                : `correo ${resultado.correo.estado}`;
        }
        setMsg(`🎁 Beneficio dado a ${b.alumno_nombre || 'el alumno'}: ${entrega} · ${correo}`);
        setTimeout(() => setMsg(''), 10000);
    };

    // El correo SALIÓ (el modal no avisa en modo prueba): se marca la gestión como CONTACTADO
    // en el BI, con el mismo PUT probado que usa la pestaña de KPIs. Si el PUT falla, el correo
    // ya salió: se avisa y no se rompe el flujo.
    const correoEnviado = async () => {
        const alumno = alumnoCorreo?.fila;
        if (!alumno) return;
        setMsg(`✅ Correo enviado a ${alumno.alumno_nombre}`);
        try {
            const { data } = await api.put(
                `/api/v1/kpis/churn/${alumno.usuario_id}/estado`,
                { estado_gestion: 'CONTACTADO' },
            );
            const { estado_anterior, ...fila } = data;
            setChurn((prev) => (prev ? {
                ...prev,
                predicciones: (prev.predicciones || []).map(
                    (p) => (p.usuario_id === alumno.usuario_id ? { ...p, ...fila } : p)),
            } : prev));
            setMsg(`✅ Correo enviado a ${alumno.alumno_nombre} · gestión marcada como CONTACTADO (antes ${estado_anterior || 'PENDIENTE'})`);
        } catch (errPut) {
            setMsg(`✅ Correo enviado a ${alumno.alumno_nombre}. ⚠️ No se pudo marcar la gestión como CONTACTADO: ${errPut.response?.data?.detail || errPut.message}`);
        }
        setTimeout(() => setMsg(''), 8000);
    };

    // Ver la ficha del alumno: se abre con el CLIC EN SU NOMBRE (ya no hay menú de acciones).
    const verDetalleAlumno = (id) => {
        setFichaAlumnoId(id);
    };

    // ── Derivados del BI (los mismos criterios que las tarjetas) ──
    // En riesgo: riesgo ALTO/CRÍTICO del modelo. Vencimientos inminentes: el plan vence en ≤ 5
    // días, medido con el MISMO test que aplica su filtro (el número de la tarjeta y las filas
    // de la tabla no pueden diferir; el campo es de la fila: no hay endpoint nuevo).
    const predicciones = churn?.predicciones || [];
    const enRiesgo = predicciones.filter((p) => ['ALTO', 'CRITICO'].includes(p.riesgo_nivel));
    const porVencer = predicciones.filter(FILTROS.plan_urgente.test);

    // ── Filtro activo (query params) ─────────────────────────────────────
    const claveFiltro = searchParams.get('filtro') || null;
    const filtroArquetipo = searchParams.get('arquetipo') || null;

    // ?alumno_id=<id>: deep-link desde Notificaciones -> abre la ficha de ESE
    // alumno. AlumnoFichaModal se auto-carga por API, asi que no depende de que
    // el alumno este en la lista. Al cerrar se limpia el param (si no, un cambio
    // de filtro lo volveria a abrir).
    useEffect(() => {
        const id = Number(searchParams.get('alumno_id'));
        if (Number.isFinite(id) && id > 0) setFichaAlumnoId(id);
    }, [searchParams]);

    const filtroDef = claveFiltro ? FILTROS[claveFiltro] : null;
    const prediccionesFiltradas = predicciones.filter((p) => {
        const okRiesgo = filtroDef ? filtroDef.test(p) : true;
        const okArquetipo = filtroArquetipo ? arquetipoDe(p) === filtroArquetipo : true;
        return okRiesgo && okArquetipo;
    });
    const quitarFiltros = () => setSearchParams({});

    // TODOS los filtros activos, uno por chip: el de riesgo y el de arquetipo SE SUMAN, así que la
    // pantalla no puede mostrar sólo uno (antes, con los dos puestos, el de riesgo quedaba oculto:
    // la tarjeta decía 37 y la tabla mostraba 1). Cada chip se quita solo.
    const filtrosActivos = [
        claveFiltro && { clave: 'filtro', valor: claveFiltro,
                         etiqueta: `Riesgo: ${filtroDef?.etiqueta || claveFiltro}` },
        filtroArquetipo && { clave: 'arquetipo', valor: filtroArquetipo,
                             etiqueta: `Arquetipo: ${estiloArquetipo(filtroArquetipo).label}` },
    ].filter(Boolean);
    const hayFiltros = filtrosActivos.length > 0;

    const quitarFiltro = (clave) => {
        const next = new URLSearchParams(searchParams);
        next.delete(clave);
        setSearchParams(next);
    };

    // Los filtros viven en la URL (query params): los setean las tarjetas y el
    // dropdown de ESTA pantalla, y el link que llega desde KPIs ya los trae.
    const ponerFiltro = (clave) => {
        const next = new URLSearchParams(searchParams);
        if (clave) next.set('filtro', clave);
        else next.delete('filtro');
        setSearchParams(next);
    };
    const alternarFiltro = (clave) => ponerFiltro(claveFiltro === clave ? null : clave);
    const ponerArquetipo = (codigo) => {
        const next = new URLSearchParams(searchParams);
        if (codigo) next.set('arquetipo', codigo);
        else next.delete('arquetipo');
        setSearchParams(next);
    };
    const alternarArquetipo = (codigo) => (
        ponerArquetipo(filtroArquetipo === codigo ? null : codigo));

    // Las 6 tarjetas de arquetipo, en el orden de ARQUETIPOS_UI (el backend manda
    // su propio orden y puede no traer los que quedaron en 0).
    const arquetiposSegmentacion = ARQUETIPOS_UI.map((codigo) => {
        const item = (segmentacion?.arquetipos || [])
            .find((a) => a.arquetipo === codigo);
        return { codigo, ...(item || { n: 0, pct: 0, descripcion: '' }) };
    });

    const chartData = [
        { name: 'Riesgo alto/crítico', total: enRiesgo.length },
        { name: 'Vencen en ≤5 días', total: porVencer.length },
    ];

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-zinc-100">🎯 Fidelización</h1>
                        <p className="text-zinc-400">Alumnos en riesgo de abandono y vencimientos próximos</p>
                    </div>
                    <button onClick={cargarFidelizacion} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-bold">
                        🔄 Recargar
                    </button>
                </div>

                <TabBar tabs={TABS} />

                {msg && (
                    <div className={`p-4 rounded-lg font-bold shadow-lg transition-all ${msg.includes('✅') ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                        {msg}
                    </div>
                )}

                {/* ── Pestaña Beneficios: TODOS los regalos del box (F2) ── */}
                {tab === 'beneficios' && (
                    <BeneficiosPanel onVerAlumno={verDetalleAlumno} onMensaje={setMsg} />
                )}

                {tab === 'gestion' && (loading ? (
                    <div className="flex justify-center py-12">
                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
                    </div>
                ) : (
                    <>
                        {/* ── Tarjetas de riesgo (MOVIDAS desde la BI) ──
                            Acá NO navegan: filtran la tabla de abajo en el acto (el
                            filtro vive en la URL, igual que el link que llega de KPIs).
                            La ex "Alumnos en Riesgo" se reemplaza por la de riesgo
                            total: era el mismo número. */}
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                            {[
                                { clave: 'critico', label: 'Abandono Crítico', valor: churn?.criticos ?? 0, icon: TriangleAlert, color: 'border-red-500', test: FILTROS.critico.test },
                                { clave: 'alto', label: 'Riesgo alto', valor: churn?.altos ?? 0, icon: TriangleAlert, color: 'border-orange-500', test: FILTROS.alto.test },
                                { clave: 'total', label: 'En riesgo (total)', valor: churn?.total ?? 0, icon: Users, color: 'border-yellow-500', test: FILTROS.total.test },
                            ].map(({ clave, label, valor, icon, color, test }) => {
                                // Los números de la tarjeta son los del BI; con un filtro puesto se
                                // aclara cuántos de ese grupo quedan EN LA TABLA (el arquetipo y el
                                // riesgo se suman): así el número grande no contradice al de abajo.
                                const conFiltro = predicciones.filter((p) => test(p)
                                    && (!filtroArquetipo || arquetipoDe(p) === filtroArquetipo)).length;
                                return (
                                    <button
                                        key={clave}
                                        type="button"
                                        onClick={() => alternarFiltro(clave)}
                                        aria-pressed={claveFiltro === clave}
                                        aria-label={`Filtrar la tabla por: ${label}`}
                                        title={claveFiltro === clave
                                            ? 'Quitar este filtro'
                                            : 'Filtrar la tabla por este grupo'}
                                        className={`w-full text-left rounded-lg transition ${claveFiltro === clave
                                            ? 'ring-2 ring-orange-500'
                                            : 'hover:ring-1 hover:ring-zinc-600'}`}
                                    >
                                        <KpiCard label={label} value={valor} icon={icon} color={color} />
                                        <p className="px-6 -mt-4 pb-2 text-xs text-zinc-500"
                                            data-testid={`tarjeta-aclaracion-${clave}`}>
                                            {hayFiltros ? `${conFiltro} con el filtro activo` : `${valor} en total`}
                                        </p>
                                    </button>
                                );
                            })}
                            {/* Clickeable: aplica el filtro `plan_urgente` (≤ 5 días) con su chip ✕, y se
                                combina con los otros. El número sale del MISMO test que el filtro. */}
                            <button
                                type="button"
                                onClick={() => alternarFiltro('plan_urgente')}
                                aria-pressed={claveFiltro === 'plan_urgente'}
                                aria-label="Filtrar la tabla por vencimientos inminentes (≤ 5 días)"
                                title={claveFiltro === 'plan_urgente'
                                    ? 'Quitar este filtro'
                                    : 'Filtrar la tabla por los planes que vencen en ≤ 5 días'}
                                data-testid="tarjeta-vencimientos"
                                className={`w-full text-left rounded-lg transition ${claveFiltro === 'plan_urgente'
                                    ? 'ring-2 ring-orange-500'
                                    : 'hover:ring-1 hover:ring-zinc-600'}`}
                            >
                                <div className="bg-zinc-900 rounded-lg shadow p-6 border-l-4 border-orange-600">
                                    <p className="text-sm text-gray-400 uppercase tracking-wide">Vencimientos Inminentes</p>
                                    <p className="text-3xl font-bold text-white mt-2">{porVencer.length}</p>
                                    <p className="text-sm mt-2 text-zinc-500">
                                        Plan que vence en ≤ 5 días
                                        {hayFiltros && ` · ${porVencer.filter((p) => !filtroArquetipo || arquetipoDe(p) === filtroArquetipo).length} con el filtro activo`}
                                    </p>
                                </div>
                            </button>
                        </div>

                        {/* ── Tarjetas de arquetipos (MOVIDAS desde la BI) ──
                            Igual que las de riesgo: filtran la tabla de abajo in-place. */}
                        {segError && (
                            <div className="bg-red-500/10 border-l-4 border-red-500 rounded-lg p-4">
                                <p className="text-sm text-red-300">
                                    No se pudo cargar la segmentación de alumnos.
                                </p>
                                <button
                                    onClick={cargarFidelizacion}
                                    className="mt-3 px-4 py-2 bg-red-500 text-white rounded-lg text-sm font-bold hover:bg-red-600 transition-colors"
                                >
                                    Reintentar
                                </button>
                            </div>
                        )}

                        {!segError && segmentacion && segmentacion.total === 0 && (
                            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
                                <p className="text-sm text-zinc-300">
                                    Todavía no hay segmentación generada para este box.
                                </p>
                                <p className="text-xs text-zinc-500 mt-1">
                                    Se genera al correr el reentrenamiento del modelo
                                    (POST /api/v1/segmentacion/reentrenar); recargar esta
                                    página no la crea.
                                </p>
                            </div>
                        )}

                        {segmentacion?.total > 0 && (
                            <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5">
                                <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                                    <div className="flex items-center gap-2">
                                        <Sparkles className="w-5 h-5 text-sky-400" />
                                        <h2 className="font-semibold text-white">Segmentación de alumnos</h2>
                                    </div>
                                    <p className="text-xs text-zinc-500">
                                        {segmentacion.total} alumnos segmentados
                                        {segmentacion.modelo_fecha
                                            ? ` · modelo del ${fmtFechaHora(segmentacion.modelo_fecha)}`
                                            : ''}
                                    </p>
                                </div>
                                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                                    {arquetiposSegmentacion.map(({ codigo, n, pct, descripcion }) => {
                                        const estilo = estiloArquetipo(codigo);
                                        const activo = filtroArquetipo === codigo;
                                        return (
                                            <button
                                                key={codigo}
                                                type="button"
                                                onClick={() => alternarArquetipo(codigo)}
                                                aria-pressed={activo}
                                                aria-label={`Filtrar la tabla por arquetipo: ${estilo.label}`}
                                                title={descripcion
                                                    ? `${descripcion} Click para filtrar la tabla.`
                                                    : 'Click para filtrar la tabla.'}
                                                className={`rounded-lg border-l-4 ${estilo.borde} bg-zinc-800/60 p-3 text-left transition ${activo
                                                    ? 'ring-2 ring-orange-500'
                                                    : 'hover:ring-1 hover:ring-zinc-600'}`}
                                            >
                                                <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                                                    {estilo.label}
                                                </p>
                                                <p className="mt-1 text-2xl font-bold text-white">{n}</p>
                                                <p className="text-[11px] text-zinc-500">{pct}% del total</p>
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* ── Buscador + filtros de la tabla (mismo estado que en KPIs) ── */}
                        <div className="flex flex-wrap items-center gap-3">
                            {/* Buscador SERVER-SIDE por nombre o correo (sin mayúsculas ni
                                tildes, con debounce 350ms). Se combina con los filtros de abajo:
                                el backend filtra por texto y la tabla por riesgo/arquetipo. */}
                            <div className="relative">
                                <input
                                    type="text"
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                    placeholder="Buscar por nombre o correo…"
                                    aria-label="Buscar alumno por nombre o correo"
                                    data-testid="buscar-fidelizacion"
                                    className="bg-zinc-800 border border-zinc-600 rounded px-3 py-1 pr-8 text-xs text-white w-56 focus:outline-none focus:border-orange-500"
                                />
                                {searchTerm && (
                                    <button
                                        type="button"
                                        onClick={() => { setSearchTerm(''); setBuscar(''); }}
                                        aria-label="Limpiar búsqueda"
                                        title="Limpiar búsqueda"
                                        data-testid="limpiar-busqueda"
                                        className="absolute right-1.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white"
                                    >✕</button>
                                )}
                            </div>
                            <label className="flex items-center gap-2 text-xs text-zinc-400">
                                Arquetipo
                                <select
                                    value={filtroArquetipo || ''}
                                    onChange={(e) => ponerArquetipo(e.target.value || null)}
                                    aria-label="Filtrar la tabla por arquetipo de segmentación"
                                    className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-orange-500"
                                >
                                    <option value="">Todos</option>
                                    {ARQUETIPOS_UI.map((codigo) => (
                                        <option key={codigo} value={codigo}>
                                            {estiloArquetipo(codigo).label}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            {/* TODOS los filtros activos como chips: el riesgo y el arquetipo se SUMAN,
                                y cada uno se quita solo con su ✕ (antes se mostraba uno solo y el otro
                                quedaba oculto mintiendo sobre el número de filas). */}
                            {filtrosActivos.map((f) => (
                                <span key={f.clave}
                                    data-testid={`chip-filtro-${f.clave}`}
                                    className="flex items-center gap-1 rounded-full bg-zinc-800 border border-zinc-600 px-2 py-0.5 text-xs text-orange-300">
                                    {f.etiqueta}
                                    <button type="button" onClick={() => quitarFiltro(f.clave)}
                                        aria-label={`Quitar el filtro ${f.etiqueta}`}
                                        className="text-zinc-400 hover:text-white">✕</button>
                                </span>
                            ))}
                            <span className="text-xs text-zinc-500" data-testid="resultados-fidelizacion">
                                {prediccionesFiltradas.length} resultados
                            </span>
                            <span className="text-xs text-zinc-600">
                                {prediccionesFiltradas.length} de {predicciones.length} alumnos
                            </span>
                            {hayFiltros && (
                                <button
                                    type="button"
                                    onClick={quitarFiltros}
                                    data-testid="limpiar-filtros"
                                    className="px-3 py-1 bg-zinc-800 text-zinc-200 rounded-lg text-xs font-medium hover:bg-zinc-700"
                                >
                                    Limpiar filtros
                                </button>
                            )}
                        </div>


                        {/* Tabla de acción y fidelización */}
                        <div className="bg-zinc-900 rounded-lg shadow overflow-hidden">
                            <div className="px-6 py-4 border-b border-zinc-800">
                                <h2 className="text-lg font-bold text-zinc-100">
                                    🎯 Panel de Acción y Fidelización ({prediccionesFiltradas.length} alumnos)
                                </h2>
                            </div>

                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead className="bg-amber-800 text-white">
                                        <tr>
                                            <th className="px-6 py-3 text-left text-sm font-medium">Alumno</th>
                                            <th className="px-6 py-3 text-left text-sm font-medium">Riesgo</th>
                                            <th className="px-6 py-3 text-left text-sm font-medium">Arquetipo</th>
                                            <th className="px-6 py-3 text-left text-sm font-medium">Motivo</th>
                                            <th className="px-6 py-3 text-left text-sm font-medium">Recomendación</th>
                                            <th className="px-6 py-3 text-left text-sm font-medium">Gestión</th>
                                            <th className="px-6 py-3 text-left text-sm font-medium">Acción</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800">
                                        {prediccionesFiltradas.length === 0 && (
                                            <tr>
                                                <td colSpan={7} className="px-6 py-8 text-center text-sm text-zinc-500">
                                                    No hay alumnos que cumplan este filtro.
                                                </td>
                                            </tr>
                                        )}
                                        {prediccionesFiltradas.map((p, idx) => (
                                            <tr key={p.usuario_id} className={idx % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                                <td className="px-6 py-4">
                                                    {/* El detalle se abre con clic en el NOMBRE (ya no hay
                                                        menú "Acción Rápida"): las dos acciones están a la
                                                        vista, una por fila. */}
                                                    <button
                                                        type="button"
                                                        onClick={() => verDetalleAlumno(p.usuario_id)}
                                                        aria-label={`Ver el detalle de ${p.alumno_nombre || `alumno #${p.usuario_id}`}`}
                                                        className="text-sm font-bold text-zinc-100 hover:text-orange-300 underline decoration-dotted"
                                                        data-testid={`alumno-nombre-${p.usuario_id}`}
                                                    >
                                                        {p.alumno_nombre || `Alumno #${p.usuario_id}`}
                                                    </button>
                                                    <p className="text-xs text-zinc-500">#{p.usuario_id}{p.alumno_correo ? ` · ${p.alumno_correo}` : ''}</p>
                                                </td>
                                                <td className="px-6 py-4">
                                                    <RiskBadge nivel={p.riesgo_nivel} />
                                                    <p className="text-xs text-zinc-500 mt-1">{Number(p.probabilidad_churn || 0).toFixed(1)}%</p>
                                                    {p.riesgo_calculado_en && (
                                                        <p className="text-[10px] text-zinc-600 mt-0.5"
                                                            title="Cuándo se calculó el modelo (no es la situación de hoy, que es en vivo)">
                                                            calculado el {fmtFechaHora(p.riesgo_calculado_en)}
                                                        </p>
                                                    )}
                                                </td>
                                                <td className="px-6 py-4">
                                                    <ArquetipoBadge arquetipo={p.arquetipo} />
                                                    {p.arquetipo_calculado_en && (
                                                        <p className="text-[10px] text-zinc-600 mt-0.5"
                                                            title="Cuándo se entrenó el modelo de segmentación">
                                                            calculado el {fmtFechaHora(p.arquetipo_calculado_en)}
                                                        </p>
                                                    )}
                                                </td>
                                                <td className="px-6 py-4 text-sm text-zinc-400">{p.motivo || '—'}</td>
                                                <td className="px-6 py-4">
                                                    {/* Esta columna y el modal de detalle salen de la MISMA función
                                                        del backend (`sugerir()`), pedida en lote: no pueden decir
                                                        cosas distintas del mismo alumno. */}
                                                    {(() => {
                                                        const sug = sugerencias[String(p.usuario_id)];
                                                        if (!sug) return <span className="text-zinc-500">—</span>;
                                                        return (
                                                            <div className="max-w-xs border-l-2 pl-2 border-orange-500"
                                                                data-testid={`sugerencia-${p.usuario_id}`}>
                                                                <div className="flex items-start justify-between gap-2">
                                                                    <span className="text-[10px] font-semibold uppercase tracking-wide text-orange-300"
                                                                        title={sug.label || 'Sin correo que mandar'}>
                                                                        {sug.plantilla || 'Sin correo que mandar'}
                                                                    </span>
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => setDetalleReco(p)}
                                                                        title={`Detalle de hoy: ${sug.plantilla ? sug.label : 'sin acción'} · ${sug.motivo}`}
                                                                        aria-label={`Ver el detalle para ${p.alumno_nombre || `alumno #${p.usuario_id}`}`}
                                                                        className="shrink-0 rounded p-0.5 text-zinc-400 hover:bg-zinc-700/60 hover:text-orange-400"
                                                                    >
                                                                        <Eye className="h-3.5 w-3.5" />
                                                                    </button>
                                                                </div>
                                                                <div className="text-xs leading-snug text-zinc-300 line-clamp-2">
                                                                    {sug.plantilla ? sug.label : sug.motivo}
                                                                </div>
                                                                {sug.plantilla && (
                                                                    <div className="text-[11px] leading-snug text-zinc-500 line-clamp-1">
                                                                        {sug.motivo}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        );
                                                    })()}
                                                </td>
                                                <td className="px-6 py-4 text-xs">
                                                    <span className="inline-block px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300">
                                                        {p.estado_gestion || 'PENDIENTE'}
                                                    </span>
                                                </td>
                                                <td className="px-6 py-4">
                                                    {/* DOS botones a la vista (antes era un menú "Acción Rápida"):
                                                        una fila = dos acciones, sin abrir nada para verlas. */}
                                                    <div className="flex flex-wrap gap-2">
                                                        <button
                                                            type="button"
                                                            onClick={() => enviarCorreoManual(p)}
                                                            title="Elegir plantilla y ver el correo exacto antes de mandarlo"
                                                            data-testid={`enviar-correo-${p.usuario_id}`}
                                                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700"
                                                        >
                                                            <Mail className="h-3.5 w-3.5" /> Enviar correo
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => darBeneficio(p)}
                                                            title="Regalar clases o un descuento (y avisarle por correo si quieres)"
                                                            data-testid={`dar-beneficio-${p.usuario_id}`}
                                                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-emerald-600 text-white rounded-lg text-xs font-bold hover:bg-emerald-700"
                                                        >
                                                            <Gift className="h-3.5 w-3.5" /> Dar beneficio
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        {/* Gráfico de barras: desglose de alertas (al final, para que arriba de la tabla queden las tarjetas de conteo y los filtros) */}
                        <div className="bg-zinc-900 rounded-lg shadow p-5">
                            <h2 className="text-lg font-bold text-zinc-100 mb-2">📊 Desglose de alertas</h2>
                            <p className="text-xs text-zinc-400 mb-4">Riesgo alto/crítico del modelo vs planes que vencen en ≤5 días</p>
                            {predicciones.length === 0 ? (
                                <div className="py-8 text-center text-zinc-500 text-sm">Sin alertas activas 🎉</div>
                            ) : (
                                <ResponsiveContainer width="100%" height={220}>
                                    <BarChart data={chartData} barSize={70}>
                                        <CartesianGrid strokeDasharray="3 3" />
                                        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                                        <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                                        <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} />
                                        <Bar dataKey="total" name="Alumnos" radius={[6, 6, 0, 0]}>
                                            {chartData.map((d, idx) => (
                                                <Cell key={idx} fill={d.name === 'Riesgo alto/crítico' ? '#dc2626' : '#f97316'} />
                                            ))}
                                        </Bar>
                                    </BarChart>
                                </ResponsiveContainer>
                            )}
                        </div>

                    </>
                ))}
            </div>

            {/* MODAL FICHA ALUMNO */}
            {fichaAlumnoId && (
                <AlumnoFichaModal
                    alumnoId={fichaAlumnoId}
                    tenantId={tenant_id}
                    onVerHistorial={() => navigate(`/admin/alumnos/${fichaAlumnoId}/historial`)}
                    onClose={() => {
                        setFichaAlumnoId(null);
                        // Limpia el deep-link para no re-abrir la ficha.
                        const next = new URLSearchParams(searchParams);
                        next.delete('alumno_id');
                        setSearchParams(next);
                    }}
                />
            )}

            {/* MODAL DE DETALLE: la recomendación es la MISMA función que la columna (sugerir),
                y el riesgo/probabilidad del modelo va aparte, como contexto. */}
            {detalleReco && (
                <RecomendacionModal
                    fila={detalleReco}
                    sugerencia={sugerencias[String(detalleReco.usuario_id)] || null}
                    onClose={() => setDetalleReco(null)}
                />
            )}

            {/* MODAL ENVIAR CORREO (F1): elegir plantilla → ver el correo exacto → enviar.
                La sugerencia viaja desde acá (la misma que muestra la columna "Recomendación"),
                para que el modal arranque con la plantilla que el admin acaba de ver en la tabla. */}
            {alumnoCorreo && (
                <ModalEnviarCorreo
                    alumno={alumnoCorreo.fila}
                    sugerencia={sugerencias[String(alumnoCorreo.fila.usuario_id)] || null}
                    onClose={() => setAlumnoCorreo(null)}
                    onEnviado={correoEnviado}
                />
            )}

            {/* MODAL DAR BENEFICIO (F2): tipo → valor → plan del pase → (avisar por correo) */}
            {alumnoBeneficio && (
                <BeneficioModal
                    alumno={alumnoBeneficio.fila}
                    onClose={() => setAlumnoBeneficio(null)}
                    onCreado={beneficioDado}
                />
            )}
        </Layout>
    );
};

export default Fidelizacion;
