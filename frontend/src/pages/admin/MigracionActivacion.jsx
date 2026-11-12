import React, { useState } from 'react';
import Layout from '../../components/Layout';
import { KpiCard } from '../../components/kpis/KpiCard';
import { useMigracionActivacion } from '../../hooks/queries';
import {
    ETAPAS_ACTIVACION, activadosHoy, badgeEtapa, conteoPorEtapa, filtrarAlumnos,
    hayFiltro, pendientesPorActivar, porcentajeComprado, totalAlumnos,
} from '../../utils/migracionActivacion';

/**
 * Panel de ACTIVACIÓN de la migración BoxMagic (Fase 4).
 *
 * TEMPORAL: es el panel de control de la carga de los ~712 alumnos reales desde
 * BoxMagic. Cuando la migración termine se borran, de una sola vez, la sección del menú
 * (`config/menu.js`), las rutas de `App.jsx` y este archivo.
 *
 * SÓLO LEE: todo el cálculo del embudo (en qué etapa está cada alumno y el resumen con
 * los activados de las últimas 24 h) viene resuelto del backend en
 * `GET /api/v1/migracion-boxmagic/activacion`. Acá no se escribe nada ni se toca a
 * ningún alumno: la pantalla es para MIRAR a quién le falta qué.
 *
 * Interacción (mismo patrón que Fidelización): las tarjetas son botones que filtran la
 * tabla de abajo, se prenden y se apagan con el mismo clic, y el filtro activo queda a
 * la vista en los chips. Los conteos y las reglas del filtro viven en
 * `utils/migracionActivacion.js` (probado sin navegador).
 */
const MigracionActivacion = () => {
    const { data, isPending, isError, error, refetch } = useMigracionActivacion();
    // Filtros de la tabla. Se COMBINAN entre sí (etapa + "se activaron hoy").
    const [etapaFiltro, setEtapaFiltro] = useState(null);
    const [soloHoy, setSoloHoy] = useState(false);

    const alumnos = data?.alumnos || [];
    const resumen = data?.resumen || {};
    // Derivaciones baratas (el backend ya mandó el resumen hecho y son cientos de filas):
    // se calculan en el render, sin `useMemo` — memoizar objetos que se arman con `||`
    // sólo agrega una dependencia que cambia en cada render.
    const conteo = conteoPorEtapa(resumen);
    const total = totalAlumnos(resumen);
    const pendientes = pendientesPorActivar(resumen);
    const comprados = conteo.plan_comprado;
    const avance = porcentajeComprado(resumen);
    const hoy = activadosHoy(resumen);

    const visibles = filtrarAlumnos(alumnos, { etapa: etapaFiltro, soloActivadosHoy: soloHoy });
    const conFiltro = hayFiltro({ etapa: etapaFiltro, soloActivadosHoy: soloHoy });

    const alternarEtapa = (clave) => setEtapaFiltro((previa) => (previa === clave ? null : clave));
    const quitarFiltros = () => { setEtapaFiltro(null); setSoloHoy(false); };

    const mensajeError = error?.response?.data?.detail || 'No se pudo cargar el panel de activación.';

    if (isPending) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-64">
                    <div className="animate-spin rounded-full h-10 w-10 border-4 border-orange-500 border-t-transparent" />
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl font-extrabold text-zinc-100">
                            Panel de Activación — Migración BoxMagic
                        </h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            En qué etapa del alta quedó cada alumno del padrón de BoxMagic.
                            Sólo lectura: acá no se activa a nadie.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => refetch()}
                        className="shrink-0 px-4 py-2 rounded-xl border border-zinc-700 bg-zinc-800 text-zinc-200 text-sm font-bold hover:border-orange-500 hover:text-orange-400 transition-colors"
                    >
                        Actualizar
                    </button>
                </div>

                {isError && (
                    <div className="mb-4 rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-[13px] text-red-200">
                        {mensajeError}
                        <button type="button" onClick={() => refetch()} className="ml-3 underline font-semibold">
                            Reintentar
                        </button>
                    </div>
                )}

                {/* ── Pendientes por activar: el número que importa + avance del embudo ── */}
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 mb-4">
                    <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
                        <div>
                            <p className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">
                                Pendientes por activar
                            </p>
                            <p className="text-3xl font-extrabold text-zinc-100 mt-1" data-testid="pendientes-por-activar">
                                {pendientes}
                            </p>
                            <p className="text-[12px] text-zinc-500 mt-1">
                                de {total} alumnos migrados
                            </p>
                        </div>
                        <p className="text-sm text-zinc-400">
                            <span className="font-extrabold text-emerald-400">{comprados}</span>
                            {' '}ya compraron plan ({avance}%)
                        </p>
                    </div>
                    <div
                        className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-800"
                        role="progressbar"
                        aria-valuenow={avance}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label="Porcentaje de alumnos migrados que ya compraron plan"
                        data-testid="barra-avance-activacion"
                    >
                        <div
                            className="h-full rounded-full bg-emerald-500 transition-all"
                            style={{ width: `${avance}%` }}
                        />
                    </div>
                </div>

                {/* ── Hoy se activaron: CLICKEABLE, filtra la tabla por `activado_hoy` ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-6">
                    <button
                        type="button"
                        onClick={() => setSoloHoy((previo) => !previo)}
                        aria-pressed={soloHoy}
                        aria-label="Filtrar la tabla por los alumnos que se activaron hoy"
                        title={soloHoy ? 'Quitar este filtro' : 'Filtrar la tabla por los que se activaron hoy'}
                        data-testid="tarjeta-activados-hoy"
                        className={`w-full text-left rounded-2xl transition ${soloHoy
                            ? 'ring-2 ring-orange-500'
                            : 'hover:ring-1 hover:ring-zinc-600'}`}
                    >
                        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                            <span className="absolute left-0 top-0 bottom-0 w-1 bg-emerald-500" />
                            <p className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">
                                Hoy se activaron
                            </p>
                            <p className="text-2xl font-extrabold text-zinc-100 mt-1.5">{hoy}</p>
                            <p className="text-[11px] text-zinc-500 mt-1">
                                alumnos en las últimas 24 h
                            </p>
                        </div>
                    </button>
                </div>

                {/* ── Las 5 etapas: tarjetas que filtran la tabla (patrón de Fidelización) ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5 mb-4">
                    {ETAPAS_ACTIVACION.map((etapa) => {
                        const activa = etapaFiltro === etapa.key;
                        return (
                            <button
                                key={etapa.key}
                                type="button"
                                onClick={() => alternarEtapa(etapa.key)}
                                aria-pressed={activa}
                                aria-label={`Filtrar la tabla por la etapa: ${etapa.label}`}
                                title={activa ? 'Quitar este filtro' : `Filtrar la tabla por ${etapa.label}`}
                                data-testid={`tarjeta-etapa-${etapa.key}`}
                                className={`w-full text-left rounded-lg transition ${activa
                                    ? 'ring-2 ring-orange-500'
                                    : 'hover:ring-1 hover:ring-zinc-600'}`}
                            >
                                <KpiCard
                                    label={etapa.label}
                                    value={conteo[etapa.key]}
                                    color={etapa.color}
                                />
                            </button>
                        );
                    })}
                </div>

                {/* ── Filtros activos (se pueden quitar uno por uno) ── */}
                {conFiltro && (
                    <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="filtros-activos">
                        <span className="text-xs text-zinc-500">Filtrando:</span>
                        {etapaFiltro && (
                            <button
                                type="button"
                                onClick={() => setEtapaFiltro(null)}
                                className="px-3 py-1 rounded-full text-xs font-semibold border border-orange-500/40 bg-orange-500/10 text-orange-400 hover:bg-orange-500/20 transition-colors"
                            >
                                Etapa: {badgeEtapa(etapaFiltro).texto} <span aria-hidden="true">×</span>
                            </button>
                        )}
                        {soloHoy && (
                            <button
                                type="button"
                                onClick={() => setSoloHoy(false)}
                                className="px-3 py-1 rounded-full text-xs font-semibold border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-colors"
                            >
                                Activados hoy <span aria-hidden="true">×</span>
                            </button>
                        )}
                        <button type="button" onClick={quitarFiltros} className="ml-1 text-xs font-semibold text-zinc-400 underline">
                            Ver todos
                        </button>
                    </div>
                )}


                {/* ── Tabla ── */}
                <div className="overflow-x-auto rounded-2xl border border-zinc-800 bg-zinc-900">
                    <table className="w-full">
                        <thead className="bg-zinc-800/60">
                            <tr>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Nombre</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Correo</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Etapa</th>
                                <th className="px-6 py-3 text-left text-sm font-medium text-zinc-300">Plan</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800">
                            {visibles.length > 0 ? visibles.map((alumno) => {
                                const badge = badgeEtapa(alumno.etapa);
                                // Clave de la fila = `candidato_id` (el padrón). `id` es la
                                // cuenta REAL y viene en null mientras no exista: usarlo de
                                // clave repetiría la misma key en casi todas las filas.
                                const clave = alumno.candidato_id ?? alumno.id;
                                return (
                                    <tr key={clave} data-alumno-id={clave} className="hover:bg-zinc-800/40">
                                        <td className="px-6 py-3 text-sm font-medium text-zinc-100">{alumno.nombre}</td>
                                        <td className="px-6 py-3 text-sm text-zinc-400">{alumno.correo}</td>
                                        <td className="px-6 py-3 text-sm">
                                            <span className={`px-3 py-1 rounded-full text-xs font-medium border ${badge.clase}`}>
                                                {badge.texto}
                                            </span>
                                            {/* El hito de las últimas 24 h, al lado de la etapa: así el número
                                                de la tarjeta "Hoy se activaron" se puede verificar fila por
                                                fila, sin una columna propia. */}
                                            {alumno.activado_hoy && (
                                                <span className="ml-2 text-[11px] font-bold uppercase tracking-wide text-emerald-400">
                                                    Hoy
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-6 py-3 text-sm">
                                            {alumno.plan_comprado
                                                ? <span className="px-2 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-300">{alumno.plan_comprado}</span>
                                                : <span className="text-zinc-500">—</span>}
                                        </td>
                                    </tr>
                                );
                            }) : (
                                <tr>
                                    <td colSpan={4} className="px-6 py-8 text-center text-sm text-zinc-400">
                                        {alumnos.length === 0
                                            ? 'El padrón de BoxMagic no tiene alumnos de activación cargados todavía.'
                                            : 'Ningún alumno coincide con el filtro.'}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>

                <p className="text-[12px] text-zinc-500 mt-4">
                    Mostrando <span className="font-bold text-zinc-300">{visibles.length}</span> de{' '}
                    <span className="font-bold text-zinc-300">{alumnos.length}</span> alumnos.{' '}
                    &quot;Pendientes por activar&quot; son los que todavía no compraron plan.
                </p>
            </div>
        </Layout>
    );
};

export default MigracionActivacion;

