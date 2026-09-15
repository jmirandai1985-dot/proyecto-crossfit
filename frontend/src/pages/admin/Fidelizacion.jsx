import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import AlumnoFichaModal from '../../components/AlumnoFichaModal';
import { RiskBadge } from '../../components/kpis/RiskBadge';
import RecomendacionModal from '../../components/kpis/RecomendacionModal';
import { estiloReco } from '../../components/kpis/recoEstilo';
import { ARQUETIPOS_UI, estiloArquetipo, arquetipoDe } from '../../components/kpis/arquetipoEstilo';
import { KpiCard } from '../../components/kpis/KpiCard';
import { ArquetipoBadge } from '../../components/kpis/ArquetipoBadge';
import { Eye, TriangleAlert, Users, Sparkles } from 'lucide-react';
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
        // Misma Regla B del backend/BI: riesgo ALTO/CRÍTICO con plan vigente
        // que vence en ≤7 días.
        etiqueta: 'Riesgo alto/crítico con plan que vence en ≤7 días',
        test: (p) => {
            if (!['ALTO', 'CRITICO'].includes(p.riesgo_nivel)) return false;
            if (!p.fecha_proxima_renovacion) return false;
            const limite = new Date();
            limite.setDate(limite.getDate() + 7);
            return String(p.fecha_proxima_renovacion).slice(0, 10) <= toISO(limite);
        },
    },
};

const Fidelizacion = () => {
    const { tenant_id } = useAuth();
    // Filtros que llegan desde la pestaña BI (?filtro=... y/o ?arquetipo=...).
    const [searchParams, setSearchParams] = useSearchParams();
    // Datos del BI (GET /kpis/churn): score, motivo, recomendación, gestión.
    const [churn, setChurn] = useState(null);
    // Segmentación (conteos por arquetipo) para las 6 tarjetas de abajo.
    const [segmentacion, setSegmentacion] = useState(null);
    const [loading, setLoading] = useState(true);
    const [menuAccion, setMenuAccion] = useState(null);
    const [enviandoCorreo, setEnviandoCorreo] = useState(null);
    const [fichaAlumnoId, setFichaAlumnoId] = useState(null);
    const [detalleReco, setDetalleReco] = useState(null);
    const [msg, setMsg] = useState('');

    const cargarFidelizacion = async () => {
        setLoading(true);
        try {
            // Una sola fuente: el BI (score ML + motivo + recomendación + gestión).
            const res = await api.get('/api/v1/kpis/churn');
            setChurn(res.data);
            setMsg('');
            // Segmentación: opcional (si falla o no se entrenó, las tarjetas de
            // arquetipo no se muestran y el resto del panel sigue igual).
            const rSeg = await api.get('/api/v1/segmentacion').catch(() => null);
            setSegmentacion(rSeg?.data || null);
        } catch (err) {
            setChurn(null);
            setMsg('❌ ' + (err.response?.data?.detail || err.message || 'No se pudo cargar el panel'));
        }
        setLoading(false);
    };

    useEffect(() => {
        cargarFidelizacion();
    }, [tenant_id]);

    const toggleMenuAccion = (id) => {
        setMenuAccion(menuAccion === id ? null : id);
    };

    const enviarCorreoManual = async (alumno, tipo) => {
        setMenuAccion(null);
        setEnviandoCorreo(alumno.usuario_id);
        setMsg('');
        try {
            const tipoEnvio = tipo === 'riesgo' ? 'inactividad' : 'vencimiento';
            const res = await api.post(`/api/v1/notificaciones-enviadas/enviar-manual`, null, {
                params: { alumno_id: alumno.usuario_id, tipo: tipoEnvio }
            });
            if (res.data?.exito) {
                setMsg(`✅ Correo de ${tipoEnvio === 'inactividad' ? 'recuperación' : 'renovación'} enviado a ${alumno.alumno_nombre}`);
                // Marca la gestión como CONTACTADO en el BI (mismo PUT probado que
                // usa la pestaña de KPIs: no se creó endpoint nuevo). Si el PUT
                // falla, el correo YA salió: se avisa y no se rompe el flujo.
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
            } else {
                const detalle = res.data?.detalle_error || 'No se pudo enviar el correo via Gmail SMTP (revisar credenciales o destinatario).';
                setMsg(`❌ Error al enviar correo a ${alumno.alumno_nombre}: ${detalle}`);
            }
        } catch (err) {
            setMsg('❌ ' + (err.response?.data?.detail || err.message));
        }
        setEnviandoCorreo(null);
        setTimeout(() => setMsg(''), 6000);
    };

    const verDetalleAlumno = (id) => {
        setMenuAccion(null);
        setFichaAlumnoId(id);
    };

    // ── Derivados del BI (los mismos criterios que las 2 tarjetas de siempre) ──
    // En riesgo: riesgo ALTO/CRÍTICO del modelo. Próximos a vencer: plan que
    // expira en <= 5 días (el campo es de la fila: no hay endpoint nuevo).
    const predicciones = churn?.predicciones || [];
    const hoyISO = toISO(new Date());
    const limite5ISO = (() => { const d = new Date(); d.setDate(d.getDate() + 5); return toISO(d); })();
    const venceISO = (p) => (p.fecha_proxima_renovacion ? String(p.fecha_proxima_renovacion).slice(0, 10) : null);
    const enRiesgo = predicciones.filter((p) => ['ALTO', 'CRITICO'].includes(p.riesgo_nivel));
    const porVencer = predicciones.filter((p) => {
        const f = venceISO(p);
        return f && f >= hoyISO && f <= limite5ISO;
    });
    const idsPorVencer = new Set(porVencer.map((p) => p.usuario_id));
    // Tipo de correo manual: renovación si el plan vence en ≤5 días; si no, recuperación.
    const tipoEnvioDe = (p) => (idsPorVencer.has(p.usuario_id) ? 'vencimiento' : 'inactividad');

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
    const etiquetaFiltro = filtroArquetipo
        ? `Arquetipo: ${estiloArquetipo(filtroArquetipo).label}`
        : (filtroDef?.etiqueta || null);

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

                {msg && (
                    <div className={`p-4 rounded-lg font-bold shadow-lg transition-all ${msg.includes('✅') ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                        {msg}
                    </div>
                )}

                {loading ? (
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
                                { clave: 'critico', label: 'Abandono Crítico', valor: churn?.criticos ?? 0, icon: TriangleAlert, color: 'border-red-500' },
                                { clave: 'alto', label: 'Riesgo alto', valor: churn?.altos ?? 0, icon: TriangleAlert, color: 'border-orange-500' },
                                { clave: 'total', label: 'En riesgo (total)', valor: churn?.total ?? 0, icon: Users, color: 'border-yellow-500' },
                            ].map(({ clave, label, valor, icon, color }) => (
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
                                </button>
                            ))}
                            {/* Informativa (no filtra): define el tipo de correo de la Acción Rápida. */}
                            <div className="bg-zinc-900 rounded-lg shadow p-6 border-l-4 border-orange-600">
                                <p className="text-sm text-gray-400 uppercase tracking-wide">Vencimientos Inminentes</p>
                                <p className="text-3xl font-bold text-white mt-2">{porVencer.length}</p>
                                <p className="text-sm mt-2 text-zinc-500">Plan que vence en ≤ 5 días</p>
                            </div>
                        </div>

                        {/* ── Tarjetas de arquetipos (MOVIDAS desde la BI) ──
                            Igual que las de riesgo: filtran la tabla de abajo in-place. */}
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

                        {/* ── Filtros de la tabla (mismo estado que en KPIs) ── */}
                        <div className="flex flex-wrap items-center gap-3">
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
                            {etiquetaFiltro && (
                                <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-orange-300">
                                    Filtro: {etiquetaFiltro}
                                </span>
                            )}
                            <span className="text-xs text-zinc-500">
                                {prediccionesFiltradas.length} de {predicciones.length} alumnos
                            </span>
                            {etiquetaFiltro && (
                                <button
                                    type="button"
                                    onClick={quitarFiltros}
                                    className="text-xs text-zinc-300 underline hover:text-orange-300"
                                >
                                    Ver todos
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
                                                    <p className="text-sm font-bold text-zinc-100">{p.alumno_nombre || `Alumno #${p.usuario_id}`}</p>
                                                    <p className="text-xs text-zinc-500">#{p.usuario_id}{p.alumno_correo ? ` · ${p.alumno_correo}` : ''}</p>
                                                </td>
                                                <td className="px-6 py-4">
                                                    <RiskBadge nivel={p.riesgo_nivel} />
                                                    <p className="text-xs text-zinc-500 mt-1">{Number(p.probabilidad_churn || 0).toFixed(1)}%</p>
                                                </td>
                                                <td className="px-6 py-4">
                                                    <ArquetipoBadge arquetipo={p.arquetipo} />
                                                </td>
                                                <td className="px-6 py-4 text-sm text-zinc-400">{p.motivo || '—'}</td>
                                                <td className="px-6 py-4">
                                                    {p.recomendacion ? (
                                                        <div className={`max-w-xs border-l-2 pl-2 ${estiloReco(p.recomendacion_codigo).borde}`} title={p.recomendacion}>
                                                            <div className="flex items-start justify-between gap-2">
                                                                <span className={`text-[10px] font-semibold uppercase tracking-wide ${estiloReco(p.recomendacion_codigo).texto}`}>
                                                                    {estiloReco(p.recomendacion_codigo).etiqueta}
                                                                </span>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => setDetalleReco(p)}
                                                                    title="Ver recomendación completa"
                                                                    aria-label={`Ver recomendación completa de ${p.alumno_nombre || `alumno #${p.usuario_id}`}`}
                                                                    className="shrink-0 rounded p-0.5 text-zinc-400 hover:bg-zinc-700/60 hover:text-orange-400"
                                                                >
                                                                    <Eye className="h-3.5 w-3.5" />
                                                                </button>
                                                            </div>
                                                            <div className="text-xs leading-snug text-zinc-300 line-clamp-2">{p.recomendacion}</div>
                                                        </div>
                                                    ) : (
                                                        <span className="text-zinc-500">—</span>
                                                    )}
                                                </td>
                                                <td className="px-6 py-4 text-xs">
                                                    <span className="inline-block px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300">
                                                        {p.estado_gestion || 'PENDIENTE'}
                                                    </span>
                                                </td>
                                                <td className="px-6 py-4">
                                                    <div className="relative inline-block">
                                                        <button
                                                            onClick={() => toggleMenuAccion(p.usuario_id)}
                                                            disabled={enviandoCorreo === p.usuario_id}
                                                            aria-label={`Acciones para ${p.alumno_nombre || `alumno #${p.usuario_id}`}`}
                                                            className="px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700 disabled:opacity-50"
                                                        >
                                                            {enviandoCorreo === p.usuario_id ? '⏳ Enviando...' : '⚡ Acción Rápida'}
                                                        </button>
                                                        {menuAccion === p.usuario_id && (
                                                            <div className="absolute right-0 mt-1 w-44 bg-zinc-900 rounded-lg shadow-xl border border-zinc-700 z-20 overflow-hidden">
                                                                <button
                                                                    onClick={() => enviarCorreoManual(p, tipoEnvioDe(p))}
                                                                    disabled={enviandoCorreo === p.usuario_id}
                                                                    className="w-full px-4 py-2.5 text-left text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
                                                                >
                                                                    ✉️ Enviar correo
                                                                </button>
                                                                <button
                                                                    onClick={() => verDetalleAlumno(p.usuario_id)}
                                                                    className="w-full px-4 py-2.5 text-left text-sm text-zinc-200 hover:bg-zinc-800 border-t border-zinc-700"
                                                                >
                                                                    👤 Ver detalle
                                                                </button>
                                                            </div>
                                                        )}
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
                )}
            </div>

            {/* MODAL FICHA ALUMNO */}
            {fichaAlumnoId && (
                <AlumnoFichaModal
                    alumnoId={fichaAlumnoId}
                    tenantId={tenant_id}
                    onClose={() => {
                        setFichaAlumnoId(null);
                        // Limpia el deep-link para no re-abrir la ficha.
                        const next = new URLSearchParams(searchParams);
                        next.delete('alumno_id');
                        setSearchParams(next);
                    }}
                />
            )}

            {/* MODAL RECOMENDACIÓN (mismo componente que usa la pestaña BI) */}
            {detalleReco && (
                <RecomendacionModal
                    fila={detalleReco}
                    onClose={() => setDetalleReco(null)}
                />
            )}
        </Layout>
    );
};

export default Fidelizacion;
