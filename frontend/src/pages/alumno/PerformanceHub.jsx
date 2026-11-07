import React from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import AvisoCarga from '../../components/AvisoCarga';
import BotonVolver from '../../components/BotonVolver';
import { useAuth } from '../../context/AuthContext';
// Fase 2 (Bloque 1): los datos salen de la caché compartida (`hooks/queries.js`), la
// MISMA que usan la Pizarra de RMs y Evolución.
import { useHistorialRmTodos, useRmsAlumno, useIntensidadRelativa, useNivelGeneral } from '../../hooks/queries';
// H-03: la categoría/valor de un RM salen de una única fuente (utils/rm.js).
// Antes estas 3 funciones vivían acá y había otra copia en Evolución y otra en la Pizarra.
import {
    inferirCategoriaRM as inferirCategoria,
    valorRM as getValorNumerico,
    unidadRM as getUnidad,
} from '../../utils/rm';
// TZ Chile: fechas de los RMs en el calendario chileno.
import { fmtFechaCortaChile } from '../../utils/fecha';
// Fase 2 (Bloque 2): evolución por movimiento + tips, derivados del historial.
import { evolucionPorMovimiento, tipsEvolucion, objetivosSugeridos } from '../../utils/evolucionRM';
// Acordeón por movimiento dentro de cada categoría (cuadrantes) + texto del tip "objetivo".
import { agruparMovimientosPorCategoria, textoObjetivo } from '../../utils/evolucionMovimiento';
// Intensidad relativa (%RM): cuánto de su RM usa el alumno dentro de un WOD real.
import { intensidadRelativaPorMovimiento } from '../../utils/intensidadRelativa';
// Progreso de la barra de nivel por movimiento (Fuerza/Gimnástico), lógica pura.
import { pctProgresoNivel } from '../../utils/progresoNivel';

const CAT_CONFIG = {
    fuerza: { label: 'Fuerza Máxima', color: '#3B82F6', icon: '💪' },
    gimnastico: { label: 'Gimnástico', color: '#10B981', icon: '🤸' },
    cardio: { label: 'Cardio', color: '#F97316', icon: '🧀' },
    metabolico: { label: 'Metabólico', color: '#8B5CF6', icon: '⚡' },
};

// Borde de color de las tarjetas "Para ti" (mismo patrón visual que los cuadrantes).
const COLORES_TIP = { verde: '#10B981', naranja: '#F97316', gris: '#6B7280' };

// Tip "objetivo" (tu RM es tu 100%): color índigo, propio de este tipo nuevo.
const COLOR_OBJETIVO = '#6366F1';

// Mini gráfico de barras del tip "tu RM es tu 100%": últimos 3 registros y su % respecto
// al registro actual (el 100%). Barras CSS (más liviano que recharts para solo 3 barras).
const MiniBarrasObjetivo = ({ datos }) => {
    const registros = (datos || []).slice(-3);
    const maxPct = Math.max(...registros.map((d) => d.pct ?? 0), 1);
    return (
        <div className="mt-3 flex items-end gap-1.5">
            {registros.map((d, i) => {
                const pct = d.pct ?? 0;
                const altura = Math.max(8, Math.round((pct / maxPct) * 100));
                return (
                    <div key={i} className="flex-1 flex flex-col items-center min-w-0">
                        {/* Texto de %: fuera del área de la barra, con alto propio */}
                        <span className="text-[10px] text-gray-400 h-4 leading-4">{pct}%</span>
                        {/* SÓLO acá crece la barra: el 100% ocupa este h-16 y no tapa los textos */}
                        <div className="h-16 w-full flex items-end justify-center">
                            <div className="w-full max-w-[36px] rounded-t" style={{ height: `${altura}%`, backgroundColor: COLOR_OBJETIVO }} />
                        </div>
                        {/* Texto de valor: fuera del área de la barra, con alto propio */}
                        <span className="text-[10px] text-gray-400 mt-0.5 h-4 leading-4 truncate w-full text-center">{d.valor}</span>
                    </div>
                );
            })}
        </div>
    );
};


// Acordeón de un movimiento dentro de un cuadrante de categoría: la fila SIEMPRE
// muestra el nombre + valor actual; al expandir se ve su propio mini-gráfico (solo
// SUS puntos) y una línea de contexto sobre su PR. Usa <details>/<summary> nativo.
const MovimientoAcordeon = ({ mov, color, nivelInfo }) => {
    const maxValor = Math.max(...mov.puntos.map((p) => p.valor), 1);
    // Progreso del nivel (Fuerza/Gimnástico): valor actual entre el umbral del
    // nivel actual y el siguiente (misma barra que el panel expandido de Evolución).
    const pctNivel = pctProgresoNivel(mov.valorActual, nivelInfo);
    const contexto = mov.registros === 1
        ? 'Primera marca registrada'
        : mov.esPR
            ? 'Este es tu PR actual'
            : `Último PR hace ${mov.diasDesdePR ?? '—'} días`;
    return (
        <details className="group">
            <summary className="flex items-center justify-between gap-2 cursor-pointer list-none [&::-webkit-details-marker]:hidden py-2.5 px-1 rounded-lg hover:bg-gray-50">
                <span className="min-w-0">
                    <span className="flex items-center gap-1.5 flex-wrap">
                        <span className="block font-semibold text-gray-800 break-words">{mov.movimiento_nombre}</span>
                        {nivelInfo && nivelInfo.nivel && nivelInfo.nivel !== 'Sin datos' && (
                            <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                                🥉 {nivelInfo.nivel}
                            </span>
                        )}
                    </span>
                    <span className="block text-xs text-gray-500 mt-0.5">{contexto}</span>
                </span>
                <span className="shrink-0 flex items-center gap-2">
                    <span className="text-sm font-bold text-gray-800">{mov.valorActual}<span className="text-xs font-normal text-gray-400 ml-1">{mov.unidad}</span></span>
                    <span className="text-gray-400 text-xs transition-transform group-open:rotate-180" aria-hidden="true">▼</span>
                </span>
            </summary>
            <div className="pb-3 px-1">
                {mov.puntos.length > 1 && (
                    <div className="mt-2 flex items-end gap-1 h-16">
                        {mov.puntos.map((p, i) => {
                            const altura = Math.max(8, Math.round((p.valor / maxValor) * 100));
                            return (
                                <div
                                    key={i}
                                    className="flex-1 flex flex-col items-center justify-end h-full min-w-0"
                                    title={`${formatFecha(p.fecha)} · ${p.valor} ${mov.unidad}`}
                                >
                                    <div className="w-full max-w-[28px] rounded-t" style={{ height: `${altura}%`, backgroundColor: color }} />
                                </div>
                            );
                        })}
                    </div>
                )}
                {nivelInfo && nivelInfo.nivel && nivelInfo.nivel !== 'Sin datos' && (
                    <div className="mt-3">
                        <p className="text-[11px] text-gray-500">
                            {nivelInfo.siguiente_nivel
                                ? `Para subir a ${nivelInfo.siguiente_nivel} te faltarían ${nivelInfo.valor_faltante} ${mov.unidad}`
                                : 'Ya alcanzaste el nivel máximo (Elite)'}
                        </p>
                        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-gray-100">
                            <div className="h-full rounded-full transition-all" style={{ width: `${pctNivel}%`, backgroundColor: color }} />
                        </div>
                    </div>
                )}
                <p className="text-[11px] text-gray-400 mt-1.5">
                    {mov.registros === 1
                        ? 'Registra otro RM para ver tu progresión.'
                        : `${mov.registros} marcas registradas.`}
                </p>
            </div>
        </details>
    );
};


const PerformanceHub = () => {
    const { usuario_id } = useAuth();
    const navigate = useNavigate();

    // Fase 2 (Bloque 1): las DOS consultas son del PROPIO alumno y viven en la caché
    // compartida; los cuadrantes y las series semanales se DERIVAN de esos datos (antes
    // se recalculaban dentro del fetch y se guardaban en estado, así que cualquier
    // re-render los volvía a escribir).
    //
    // N-4: `/historial-rm/alumnos/{id}/rms` trae sus RMs y `/historial-rm?limit=500`
    // (sin filtro de alumno) también devuelve sólo los suyos cuando quien consulta es un
    // alumno (scoping por JWT). Es el perfil del atleta, no un tablero del box.
    const rmsQ = useRmsAlumno(usuario_id);
    const historialQ = useHistorialRmTodos(500);
    // Intensidad relativa (%RM): prescripción de los WODs asistidos (endpoint nuevo).
    const intensidadQ = useIntensidadRelativa();
    // Nivel por movimiento (Fuerza/Gimnástico): el MISMO endpoint que usa el panel
    // expandido de Evolución. No bloquea la pantalla si falla (ver erroresCarga).
    const nivelGeneralQ = useNivelGeneral(usuario_id);

    const rms = React.useMemo(
        () => (rmsQ.data || []).map(rm => ({ ...rm, categoria: inferirCategoria(rm) })),
        [rmsQ.data],
    );

    // Cuadrantes: mejor valor de cada categoría y cuántas marcas hay.
    const catsData = React.useMemo(() => {
        const cats = { fuerza: [], gimnastico: [], cardio: [], metabolico: [] };
        rms.forEach(rm => {
            const c = inferirCategoria(rm);
            if (cats[c]) cats[c].push(getValorNumerico(rm));
        });
        const catsRes = {};
        Object.keys(cats).forEach(c => {
            const arr = cats[c];
            catsRes[c] = { valor: arr.length > 0 ? Math.max(...arr) : 0, count: arr.length };
        });
        return catsRes;
    }, [rms]);

    // Fase 2 (Bloque 2): evolución por MOVIMIENTO (no por categoría). Compara el último
    // RM de cada movimiento contra el anterior de ESE MISMO movimiento (mejora real, ya
    // que un RM es siempre el mismo ejercicio). Vive en utils/evolucionRM.js.
    const evolucion = React.useMemo(
        () => evolucionPorMovimiento(historialQ.data),
        [historialQ.data],
    );

    // Tips "Para ti" (logro / alerta / comparación) derivados de esa evolución.
    const tips = React.useMemo(() => tipsEvolucion(evolucion), [evolucion]);

    // Tips "objetivo" (tu RM es tu 100%): un objetivo por movimiento de fuerza/gimnástico.
    // Limitado a los 3 más recientes para no saturar la sección (mismo criterio que el resto).
    const objetivos = React.useMemo(
        () => objetivosSugeridos(evolucion).slice(0, 3),
        [evolucion],
    );

    // Intensidad relativa (%RM): cruza la prescripción de los WODs con el historial de
    // RMs (el RM vigente a la fecha de cada WOD). Vive en utils/intensidadRelativa.js.
    const intensidad = React.useMemo(
        () => intensidadRelativaPorMovimiento(intensidadQ.data, historialQ.data),
        [intensidadQ.data, historialQ.data],
    );

    // Acordeón por movimiento dentro de cada categoría: agrupa `historialQ.data` por
    // `movimiento_id` (sin mezclar movimientos), ordena por fecha y descarta fechas
    // inválidas. Reemplaza al BarChart que mezclaba todos los movimientos de la
    // categoría por semana tomando el máximo. `descartados` se conserva para el
    // banner de errores (`erroresCarga`).
    const { porCategoria: movimientosPorCategoria, descartados } = React.useMemo(
        () => agruparMovimientosPorCategoria(historialQ.data),
        [historialQ.data],
    );

    // Nivel de clasificación indexado por `movimiento_id` (solo Fuerza/Gimnástico).
    // Unifica `detalle_fuerza` + `detalle_gimnastico` en un único mapa para el acordeón.
    const nivelPorMovimiento = React.useMemo(() => {
        const g = nivelGeneralQ.data;
        if (!g) return {};
        const mapa = {};
        (g.detalle_fuerza || []).forEach((d) => {
            if (d?.movimiento_id != null) mapa[d.movimiento_id] = { ...d, eje: 'fuerza' };
        });
        (g.detalle_gimnastico || []).forEach((d) => {
            if (d?.movimiento_id != null) mapa[d.movimiento_id] = { ...d, eje: 'gimnastico' };
        });
        return mapa;
    }, [nivelGeneralQ.data]);

    // "Cargando" sólo mientras NO hay dato: al volver a la pantalla se pinta la copia en
    // caché al instante (misma queryKey que las otras pantallas de RMs).
    const loading = rmsQ.isPending || historialQ.isPending || intensidadQ.isPending;

    const erroresCarga = React.useMemo(() => {
        const fallaron = [];
        if (rmsQ.isError) fallaron.push('mis RMs');
        if (historialQ.isError) fallaron.push('tu historial de RMs');
        if (intensidadQ.isError) fallaron.push('la intensidad de tus WODs');
        if (nivelGeneralQ.isError) fallaron.push('tu nivel de clasificación');
        if (descartados.length > 0) {
            fallaron.push(`evolución de RMs (${descartados.length} registro/s con fecha o valor inválido)`);
        }
        return fallaron;
    }, [rmsQ.isError, historialQ.isError, intensidadQ.isError, nivelGeneralQ.isError, descartados]);

    // Reintentar = volver a pedir las tres (mismo botón del banner de antes).
    const cargarTodo = () => {
        rmsQ.refetch();
        historialQ.refetch();
        intensidadQ.refetch();
        nivelGeneralQ.refetch();
    };

    if (loading) return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>);

    if (rms.length === 0 && erroresCarga.length === 0) return (
        <Layout><div className="max-w-6xl mx-auto text-center py-16">
            <span className="text-7xl block mb-6">📊</span>
            <h2 className="text-xl font-bold text-gray-800 mb-3">Registra tu primer RM</h2>
            <p className="text-gray-500 max-w-md mx-auto mb-6">Para desbloquear tu perfil de atleta, comienza registrando tus marcas personales.</p>
            <a href="/alumno/rms" className="inline-block px-8 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm">Ir a Pizarra de RMs</a>
        </div></Layout>
    );

    const renderCuadrante = (cat) => {
        const cfg = CAT_CONFIG[cat];
        const data = catsData[cat] || {};
        const movimientos = movimientosPorCategoria[cat] || [];
        const tieneDatos = data.count > 0;
        return (
            <div key={cat} className="bg-white rounded-xl border p-4 shadow-sm" style={{ borderLeft: `4px solid ${cfg.color}` }}>
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2"><span>{cfg.icon}</span><span className="font-bold text-gray-800 text-xl">{cfg.label}</span></div>
                    {tieneDatos && <span className="text-4xl font-bold" style={{ color: cfg.color }}>{data.valor}<span className="text-base font-normal text-gray-400 ml-1">{cat === 'gimnastico' ? 'reps' : cat === 'fuerza' ? 'kg' : ''}</span></span>}
                </div>
                {movimientos.length > 0 ? (
                    <div className="divide-y divide-gray-100">
                        {movimientos.map((mov) => (
                            <MovimientoAcordeon
                                key={mov.movimiento_id}
                                mov={mov}
                                color={cfg.color}
                                nivelInfo={(cat === 'fuerza' || cat === 'gimnastico')
                                    ? nivelPorMovimiento[mov.movimiento_id]
                                    : undefined}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="h-[118px] flex items-center justify-center text-gray-400 text-sm">
                        {tieneDatos ? 'Sin movimientos con fechas válidas' : 'Sin registros aún'}
                    </div>
                )}
            </div>
        );
    };

    return (
        <Layout>
            <div className="max-w-6xl mx-auto">
                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

                <div className="flex items-center gap-3 mb-6">
                    <BotonVolver />
                    <span className="text-3xl">🏆</span>
                    <div><h1 className="text-2xl font-bold text-gray-800">Performance Hub</h1><p className="text-sm text-gray-500">Perfil completo de atleta basado en tus RMs</p></div>
                    <button type="button" onClick={() => navigate('/alumno/rms')}
                        className="ml-auto shrink-0 px-4 py-2 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors">
                        + Registrar RM
                    </button>
                </div>
                <div className="space-y-6">
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div className="px-3 py-3 border-b border-gray-100"><h2 className="font-bold text-gray-800 text-xl">📋 Tus RMs</h2></div>
                        {/* MOBILE/TABLET (<lg): una tarjeta por RM. La tabla de 7 columnas no
                            entra en un teléfono: "REPS" y "SER." quedaban pegadas ("REPSSER."),
                            el movimiento se cortaba ("Snatch (Ar...") y NOTAS desaparecía al
                            final sin indicar scroll horizontal. Desde lg vuelve la tabla. */}
                        <ul className="lg:hidden divide-y divide-gray-100">
                            {rms.map((rm, i) => {
                                const mejor = Math.max(...rms.map(r => getValorNumerico(r)));
                                const isPB = getValorNumerico(rm) === mejor;
                                return (
                                    <li key={rm.movimiento_id || i}>
                                        <button type="button"
                                            onClick={() => navigate(`/alumno/evolucion?movimiento=${rm.movimiento_id}`)}
                                            className="w-full text-left px-3 py-3 flex items-start justify-between gap-3 hover:bg-emerald-50 transition-colors">
                                            <span className="min-w-0">
                                                <span className="block font-semibold text-gray-800 break-words">
                                                    {rm.movimiento_nombre}{isPB && <span className="ml-1 text-amber-500 text-xs">⭐</span>}
                                                </span>
                                                <span className="block text-xs text-gray-500 mt-0.5">
                                                    {rm.repeticiones || '—'} rep · {rm.series || '—'} ser ·{' '}
                                                    {rm.fecha ? formatFecha(rm.fecha) : '—'}
                                                </span>
                                                {rm.notas && (
                                                    <span className="block text-xs text-gray-400 italic mt-1 break-words">
                                                        {rm.notas}
                                                    </span>
                                                )}
                                            </span>
                                            <span className="shrink-0 text-right">
                                                <span className="block text-lg font-bold text-emerald-600">
                                                    {getValorNumerico(rm) || '—'}
                                                </span>
                                                <span className="block text-[11px] text-gray-400">
                                                    {getUnidad(rm) || '—'}
                                                </span>
                                            </span>
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>

                        <div className="hidden lg:block overflow-x-auto">
                            <table className="w-full" style={{ tableLayout: 'fixed' }}>
                                <thead><tr className="text-xs text-gray-500 uppercase bg-gray-50">
                                    <th className="px-2 py-2 text-left w-[26%]">Movimiento</th>
                                    <th className="px-1 py-2 text-center w-[11%]">RM</th>
                                    <th className="px-1 py-2 text-center w-[8%]">Ud.</th>
                                    <th className="px-1 py-2 text-center w-[10%] whitespace-nowrap">Reps</th>
                                    <th className="px-1 py-2 text-center w-[9%] whitespace-nowrap">Ser.</th>
                                    <th className="px-1 py-2 text-center w-[14%]">Fecha</th>
                                    <th className="px-2 py-2 text-left w-[22%]">Notas</th>
                                </tr></thead>
                                <tbody>{rms.map((rm, i) => {
                                    const mejor = Math.max(...rms.map(r => getValorNumerico(r)));
                                    const isPB = getValorNumerico(rm) === mejor;
                                    return (
                                        <tr key={rm.movimiento_id || i} onClick={() => navigate(`/alumno/evolucion?movimiento=${rm.movimiento_id}`)}
                                            className="border-t border-gray-100 hover:bg-emerald-50 cursor-pointer transition-colors">
                                            <td className="px-2 py-1.5 font-medium text-gray-800 text-base truncate" title={rm.movimiento_nombre}>{rm.movimiento_nombre}{isPB && <span className="ml-0.5 text-amber-500 text-xs">⭐</span>}</td>
                                            <td className="px-1 py-1.5 text-center font-bold text-emerald-600 text-base">{getValorNumerico(rm) || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{getUnidad(rm) || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{rm.repeticiones || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{rm.series || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-400 text-base">{rm.fecha ? formatFecha(rm.fecha) : '—'}</td>
                                            <td className="px-2 py-1.5 text-gray-400 italic text-base truncate max-w-0" title={rm.notas || ''}>{rm.notas || '—'}</td>
                                        </tr>
                                    );
                                })}</tbody>
                            </table>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        {Object.keys(CAT_CONFIG).map(cat => renderCuadrante(cat))}
                    </div>

                    {/* Fase 2 (Bloque 2): mejora REAL por movimiento (último vs anterior). */}
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div className="px-3 py-3 border-b border-gray-100">
                            <h2 className="font-bold text-gray-800 text-xl">📈 Evolución por movimiento</h2>
                            <p className="text-sm text-gray-500">Mejora de cada movimiento contra su registro anterior.</p>
                        </div>
                        {evolucion.length === 0 ? (
                            <p className="px-4 py-6 text-gray-400 text-sm">Sin movimientos registrados todavía.</p>
                        ) : (
                            <ul className="divide-y divide-gray-100">
                                {evolucion.map((m) => {
                                    const pct = formatearPctCambio(m.pctCambio);
                                    return (
                                        <li key={m.movimiento_id}>
                                            <button type="button"
                                                onClick={() => navigate(`/alumno/evolucion?movimiento=${m.movimiento_id}`)}
                                                className="w-full text-left px-3 py-3 flex items-center justify-between gap-3 hover:bg-emerald-50 transition-colors">
                                                <span className="min-w-0">
                                                    <span className="block font-semibold text-gray-800 break-words">
                                                        {m.movimiento_nombre}
                                                        {m.esPR && <span className="ml-1 text-amber-500 text-xs" title="Mejor marca personal">⭐</span>}
                                                    </span>
                                                    <span className="block text-xs text-gray-500 mt-0.5">
                                                        {m.valorActual} {m.unidad}
                                                        {m.diasSinTestear !== null && m.diasSinTestear > 30 && (
                                                            <span className="ml-2 inline-block px-2 py-0.5 bg-orange-100 text-orange-700 text-[11px] font-semibold rounded-full">
                                                                sin testear hace {m.diasSinTestear} días
                                                            </span>
                                                        )}
                                                    </span>
                                                </span>
                                                <span className={`shrink-0 text-base font-bold ${pct.clase}`}>{pct.texto}</span>
                                            </button>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </div>

                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div className="px-3 py-3 border-b border-gray-100">
                            <h2 className="font-bold text-gray-800 text-xl">💡 Para ti</h2>
                        </div>
                        {tips.length === 0 && objetivos.length === 0 ? (
                            <p className="px-4 py-6 text-gray-400 text-sm">Registrá más RMs para recibir recomendaciones personalizadas.</p>
                        ) : (
                            <div className="p-3 space-y-3">
                                {tips.length > 0 && (
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                        {tips.map((tip, i) => (
                                            <button key={`${tip.tipo}-${i}`} type="button"
                                                onClick={() => navigate(`/alumno/evolucion?movimiento=${tip.movimientoId}`)}
                                                className="text-left rounded-xl border border-gray-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow"
                                                style={{ borderLeft: `4px solid ${COLORES_TIP[tip.color] || '#6B7280'}` }}>
                                                <span className="block text-lg">{tip.icono}</span>
                                                <span className="block font-semibold text-gray-800 mt-1">{tip.titulo}</span>
                                                <span className="block text-sm text-gray-500 mt-0.5">{tip.detalle}</span>
                                            </button>
                                        ))}
                                    </div>
                                )}
                                {objetivos.length > 0 && (
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                        {objetivos.map((o) => (
                                            <button key={`objetivo-${o.movimiento_id}`} type="button"
                                                onClick={() => navigate(`/alumno/evolucion?movimiento=${o.movimiento_id}`)}
                                                className="text-left rounded-xl border border-gray-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow"
                                                style={{ borderLeft: `4px solid ${COLOR_OBJETIVO}` }}>
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="text-lg">🎯</span>
                                                    <span className="text-[11px] text-gray-400 shrink-0">tu RM es tu 100%</span>
                                                </div>
                                                <span className="block font-semibold text-gray-800 mt-1 truncate">{o.movimiento_nombre}</span>
                                                <div className="mt-2 flex items-baseline gap-2">
                                                    <span className="text-2xl font-bold text-gray-800">{o.valorActual}<span className="text-sm font-normal text-gray-400 ml-1">{o.unidad}</span></span>
                                                    <span className="text-sm text-gray-500">→ objetivo {o.objetivoSugerido} {o.unidad}</span>
                                                </div>
                                                <p className="text-xs text-gray-500 mt-1">
                                                    {o.diasDesdePR !== null && o.diasDesdePR > 0
                                                        ? `Último PR hace ${o.diasDesdePR} días`
                                                        : 'Este es tu PR actual'}
                                                </p>
                                                <MiniBarrasObjetivo datos={o.ultimos3} />
                                                <p className="text-xs text-gray-500 mt-2">{textoObjetivo(o)}</p>
                                                <div className="mt-2 pt-2 border-t border-gray-100">
                                                    <p className="text-[11px] font-semibold text-gray-500">Plan de progresión</p>
                                                    <div className="mt-1 space-y-1">
                                                        {o.planProgresion.map((paso, i) => (
                                                            <div key={i} className="flex gap-1.5 text-xs text-gray-500">
                                                                <span className="shrink-0 font-semibold text-indigo-500">{i + 1}.</span>
                                                                <span>{paso.texto}</span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                    <p className="text-[11px] text-gray-400 mt-1.5">Ventana de reintento: {o.ventanaReintento}</p>
                                                </div>
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* 🔥 Intensidad en tus WODs: cuánto de su RM usa en un WOD real. */}
                    {intensidad.length > 0 && (
                        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                            <div className="px-3 py-3 border-b border-gray-100">
                                <h2 className="font-bold text-gray-800 text-xl">🔥 Intensidad en tus WODs</h2>
                            </div>
                            <div className="p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                {intensidad.map((mov) => {
                                    // Subió/bajó vs el WOD anterior del MISMO movimiento (en puntos de %).
                                    const pctCambio = mov.anteriorPct === null ? null : mov.ultimoPct - mov.anteriorPct;
                                    const cambio = formatearPctCambio(pctCambio);
                                    return (
                                        <div key={mov.movimiento_id}
                                            className="text-left rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                                            <div className="flex items-center justify-between gap-2">
                                                <span className="font-semibold text-gray-800 truncate">
                                                    {mov.movimiento_nombre || 'Movimiento'}
                                                </span>
                                                <span className={`shrink-0 text-sm font-bold ${cambio.clase}`}>
                                                    {cambio.texto}
                                                </span>
                                            </div>
                                            <div className="mt-2 flex items-end gap-1">
                                                <span className="text-2xl font-bold text-gray-800">{mov.ultimoPct}%</span>
                                                <span className="text-sm text-gray-500 mb-0.5">de tu RM ({mov.unidad})</span>
                                            </div>
                                            <p className="text-xs text-gray-400 mt-1">
                                                Último WOD {formatFecha(mov.ultimaFecha)} · {mov.puntos.length} registro{mov.puntos.length === 1 ? '' : 's'}
                                            </p>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </Layout>
    );
};



// TZ Chile: las fechas de los RMs llegan como 'YYYY-MM-DD'; se formatean en el
// calendario chileno (con new Date(f) a medianoche UTC la fecha se corría un día).
function formatFecha(f) {
    return fmtFechaCortaChile(f) || '—';
}

// Texto/color del % de cambio de un movimiento: sube (verde), baja (rojo), igual ("=") o
// "primera marca" cuando todavía no hay registro previo con qué comparar.
function formatearPctCambio(pct) {
    if (pct === null) return { texto: 'primera marca', clase: 'text-gray-400' };
    if (pct > 0) return { texto: `+${pct.toFixed(1)}%`, clase: 'text-emerald-600' };
    if (pct < 0) return { texto: `${pct.toFixed(1)}%`, clase: 'text-red-600' };
    return { texto: '=', clase: 'text-gray-400' };
}



export default PerformanceHub;
