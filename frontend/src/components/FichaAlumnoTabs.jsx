import React, { useEffect, useMemo, useState } from 'react';
import api from '../services/api';
// Vigente/Finalizado de la pestaña Planes (regla pura, testeada en `test:ficha-alumno`).
import { esSuscripcionVigente } from '../utils/fichaAlumno';
import { fmtFechaChile } from '../utils/fecha';
import SuspensionSaludPanel from './admin/SuspensionSaludPanel';
import { usePanelHistorial } from '../hooks/queries';
// Las secciones del PanelHistorial (la MISMA pantalla que ve el alumno) se reutilizan
// como pestañas de esta ficha unificada. Se importan por separado para no montar el
// `<PanelHistorial>` completo, que maneja su propia pestaña por URL.
import {
    SeccionAsistencia,
    SeccionBeneficios,
    SeccionBazar,
    SeccionGestion,
    SeccionMembresias,
    SeccionPagos,
    SeccionRms,
} from './historial/PanelHistorial';

const TABS = [
    { key: 'resumen', label: 'Resumen' },
    { key: 'datos', label: 'Datos' },
    { key: 'planes', label: 'Planes' },
    { key: 'membresias', label: 'Membresías' },
    { key: 'asistencia', label: 'Asistencia' },
    { key: 'pagos', label: 'Pagos' },
    { key: 'bazar', label: 'Bazar' },
    { key: 'rms', label: 'RMs' },
    { key: 'beneficios', label: 'Beneficios' },
    { key: 'referidos', label: 'Referidos' },
    { key: 'suspension', label: 'Suspensión' },
];

// Pestañas que se resuelven con `usePanelHistorial` (la fuente del alumno). El resto
// (Datos/Planes/Referidos/Suspensión) sigue con los datos que ya carga esta ficha.
const SECCIONES_PANEL = new Set([
    'resumen', 'asistencia', 'membresias', 'pagos', 'bazar', 'rms', 'beneficios',
]);
const POR_PAGINA = 25;

// Envuelve una sección del PanelHistorial con su estado de carga/error, sin duplicar
// el spinner en cada pestaña.
const SeccionPanel = ({ cargando, error, onReintentar, children }) => {
    if (cargando) {
        return (
            <div className="flex justify-center py-16">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
            </div>
        );
    }
    if (error) {
        return (
            <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-4 text-sm text-red-300">
                <p className="font-medium">⚠️ {error}</p>
                <button type="button" onClick={onReintentar}
                    className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-xs font-bold hover:bg-red-700">
                    Reintentar
                </button>
            </div>
        );
    }
    return children;
};

/**
 * Ficha unificada del alumno (vista admin) con 11 pestañas. Es el ÚNICO punto de entrada
 * a la ficha desde el padrón de Alumnos: fusiona la antigua "consulta rápida" (Datos/
 * Planes/Referidos/Suspensión) con las secciones del `PanelHistorial` (Membresías/
 * Asistencia/Pagos/Bazar/RMs/Beneficios y el bloque de gestión del Resumen), la MISMA
 * fuente que ve el alumno en `/mi-historial`.
 *
 * Los datos "propios" (usuario, suscripciones, referidos, suspensiones) se cargan con
 * `Promise.allSettled`: cada bloque se resuelve aparte y muestra su propio error, sin
 * dejar la ficha en blanco por un solo fallo. Las pestañas de historial usan
 * `usePanelHistorial` (caché de React Query) controlado por el estado `tab` local.
 */
const FichaAlumnoTabs = ({ alumnoId, nombre }) => {
    const [tab, setTab] = useState('resumen');
    const [pagina, setPagina] = useState(1);
    const [data, setData] = useState(null);
    const [suscripcion, setSuscripcion] = useState(null);
    const [planes, setPlanes] = useState([]);
    const [codigoReferido, setCodigoReferido] = useState(null);
    const [suscripciones, setSuscripciones] = useState([]);
    const [referidosUsados, setReferidosUsados] = useState([]);
    const [suspensionesPropias, setSuspensionesPropias] = useState([]);
    const [loading, setLoading] = useState(true);
    const [errores, setErrores] = useState({});

    // Pestañas de historial (membresías/asistencia/pagos/bazar/rms/beneficios + el bloque
    // de gestión del Resumen): la MISMA fuente que ve el alumno en `/mi-historial`. Sólo se
    // pide cuando la pestaña activa lo necesita (`enabled`), para no pegar al backend en
    // Datos/Planes/Referidos/Suspensión.
    const seccionPanel = SECCIONES_PANEL.has(tab) ? tab : 'resumen';
    const {
        data: panel,
        isPending: cargandoPanel,
        isError: errorPanel,
        error: errorConsulta,
        refetch: reintentarPanel,
    } = usePanelHistorial({
        alumnoId,
        seccion: seccionPanel,
        pagina,
        porPagina: POR_PAGINA,
        enabled: SECCIONES_PANEL.has(tab),
    });
    const errorPanelMsg = errorPanel
        ? (errorConsulta?.response?.data?.detail || 'No se pudo cargar el historial.')
        : '';

    useEffect(() => {
        if (!alumnoId) return;
        setLoading(true);
        setErrores({});
        const carga = async () => {
            const [usr, sus, plan, cod, suscHist, refs, susp] = await Promise.allSettled([
                api.get(`/api/v1/usuarios/${alumnoId}`),
                api.get('/api/v1/suscripciones', { params: { usuario_id: alumnoId, estado: 'activo' } }),
                api.get('/api/v1/planes'),
                api.get(`/api/v1/admin/alumnos/${alumnoId}/codigo-referido`),
                api.get('/api/v1/suscripciones', { params: { usuario_id: alumnoId } }),
                api.get(`/api/v1/admin/alumnos/${alumnoId}/referidos-usados`),
                api.get('/api/v1/admin/suspensiones', { params: { usuario_id: alumnoId } }),
            ]);
            const det = (r) => r.reason?.response?.data?.detail || r.reason?.message || 'No se pudo cargar';
            const errs = {};

            if (usr.status === 'fulfilled') setData(usr.value.data || {});
            else { setData(null); errs.usuario = det(usr); }

            if (sus.status === 'fulfilled') setSuscripcion((sus.value.data || [])[0] || null);
            else errs.suscripcion = det(sus);

            if (plan.status === 'fulfilled') {
                const d = plan.value.data;
                setPlanes(Array.isArray(d) ? d : (d?.planes || []));
            } else errs.planes = det(plan);

            if (cod.status === 'fulfilled') setCodigoReferido(cod.value.data || null);
            else errs.codigo = det(cod);

            if (suscHist.status === 'fulfilled') setSuscripciones(Array.isArray(suscHist.value.data) ? suscHist.value.data : []);
            else errs.suscripciones = det(suscHist);

            if (refs.status === 'fulfilled') setReferidosUsados(Array.isArray(refs.value.data) ? refs.value.data : []);
            else errs.referidos = det(refs);

            if (susp.status === 'fulfilled') setSuspensionesPropias(Array.isArray(susp.value.data) ? susp.value.data : []);
            else errs.suspensiones = det(susp);

            setErrores(errs);
            setLoading(false);
        };
        carga();
    }, [alumnoId]);

    // Al cambiar de alumno se vuelve a la pestaña Resumen.
    useEffect(() => { setTab('resumen'); }, [alumnoId]);

    const planActivo = planes.find((p) => p.id === suscripcion?.plan_id);
    const suscripcionesOrdenadas = useMemo(
        () => [...suscripciones].sort((a, b) => new Date(b.fecha_inicio || 0) - new Date(a.fecha_inicio || 0)),
        [suscripciones],
    );

    const fmtFecha = (v) => (v ? (fmtFechaChile(v) || '—') : '—');

    const etiquetaEstado = (d) => {
        const est = String(d?.estado || '').toLowerCase();
        if (est === 'pendiente_activacion') return { texto: 'Pendiente', clase: 'bg-amber-500/15 text-amber-300' };
        if (est === 'rechazado') return { texto: 'Rechazado', clase: 'bg-red-500/15 text-red-300' };
        if (est === 'activo' || d?.activo) return { texto: 'Activo', clase: 'bg-emerald-500/15 text-emerald-300' };
        return { texto: 'Inactivo', clase: 'bg-red-500/15 text-red-300' };
    };

    if (!alumnoId) return null;

    const estadoBadge = data ? etiquetaEstado(data) : null;

    return (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 shadow overflow-hidden">
            <div className="px-5 py-4 border-b border-zinc-800 flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                    <h3 className="font-bold text-zinc-100 truncate">{data?.nombre || nombre || 'Ficha del alumno'}</h3>
                    <p className="text-sm text-zinc-400 truncate">{data?.correo || ''}</p>
                </div>
                {estadoBadge && (
                    <span className={`px-3 py-1 rounded-full text-xs font-bold ${estadoBadge.clase}`}>{estadoBadge.texto}</span>
                )}
            </div>

            <div className="grid gap-2 px-3 pt-3 border-b border-zinc-800 max-md:flex max-md:flex-nowrap max-md:gap-1 max-md:overflow-x-auto max-md:snap-x" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))' }}>
                {TABS.map((t) => (
                    <button
                        key={t.key}
                        type="button"
                        onClick={() => { setPagina(1); setTab(t.key); }}
                        className={`px-3 py-2 text-sm font-medium rounded-lg border transition-colors whitespace-nowrap max-md:shrink-0 max-md:snap-start ${tab === t.key ? 'border-orange-500 bg-orange-500/10 text-orange-400' : 'border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500'}`}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            <div className="p-5">
                {loading ? (
                    <div className="flex justify-center py-10">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                    </div>
                ) : !data ? (
                    <div className="py-6 text-center text-red-400 text-sm">⚠️ {errores.usuario || 'Alumno no encontrado'}</div>
                ) : tab === 'resumen' ? (
                    <div className="space-y-4">
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide mb-3">Membresía activa</p>
                            {errores.suscripcion && <p className="text-sm text-red-400 mb-2">⚠️ {errores.suscripcion}</p>}
                            {suscripcion ? (
                                <div className="grid grid-cols-2 gap-3 text-sm">
                                    <div><p className="text-xs text-zinc-500">Plan</p><p className="text-zinc-200">{planActivo ? planActivo.nombre : `Plan ID ${suscripcion.plan_id}`}</p></div>
                                    <div><p className="text-xs text-zinc-500">Créditos</p><p className="text-zinc-200">{suscripcion.creditos_disponibles === null || suscripcion.creditos_disponibles === undefined ? <span className="text-orange-500">∞</span> : suscripcion.creditos_disponibles}</p></div>
                                    <div><p className="text-xs text-zinc-500">Vence el</p><p className="text-zinc-200">{fmtFecha(suscripcion.fecha_expiracion)}</p></div>
                                    <div><p className="text-xs text-zinc-500">Estado</p><p className="text-zinc-200 capitalize">{suscripcion.estado || '—'}</p></div>
                                </div>
                            ) : (
                                <p className="text-sm text-zinc-400">Sin suscripción activa.</p>
                            )}
                        </div>
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide mb-2">Código de referido</p>
                            <p className="text-zinc-200 text-lg font-mono">{codigoReferido?.codigo || 'Sin código asignado'}</p>
                        </div>

                        {/* Bloque de gestión (arquetipo/riesgo): la MISMA info que el box ve
                            en el PanelHistorial, fusionada en el Resumen de esta ficha. */}
                        <SeccionPanel cargando={cargandoPanel} error={errorPanelMsg} onReintentar={reintentarPanel}>
                            <SeccionGestion datos={panel?.datos || {}} />
                        </SeccionPanel>
                    </div>
                ) : tab === 'datos' ? (
                    <div className="grid grid-cols-2 gap-3 text-sm">
                        {[
                            ['RUT', data.rut],
                            ['Teléfono', data.telefono],
                            ['Fecha de nacimiento', fmtFecha(data.fecha_nacimiento)],
                            ['Género', data.genero],
                            ['Peso', data.peso_kg ? `${data.peso_kg} kg` : null],
                            ['Estatura', data.estatura_cm ? `${data.estatura_cm} cm` : null],
                            ['Fecha de registro', fmtFecha(data.created_at)],
                            ['Rol', data.rol],
                        ].map(([label, valor]) => (
                            <div key={label}>
                                <p className="text-xs text-zinc-500">{label}</p>
                                <p className="text-zinc-200 capitalize">{valor || '—'}</p>
                            </div>
                        ))}
                    </div>

                ) : tab === 'planes' ? (
                    <div className="space-y-3">
                        {errores.suscripciones && <p className="text-sm text-red-400">⚠️ {errores.suscripciones}</p>}
                        {suscripcionesOrdenadas.length === 0 ? (
                            <p className="text-sm text-zinc-400">Sin suscripciones registradas.</p>
                        ) : (
                            suscripcionesOrdenadas.map((s) => {
                                const vigente = esSuscripcionVigente(s);
                                return (
                                    <div key={s.id} className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-800/40 px-3 py-2.5">
                                        <div className="min-w-0">
                                            <p className="text-zinc-200 font-medium truncate">{planes.find((p) => p.id === s.plan_id)?.nombre || `Plan ID ${s.plan_id}`}</p>
                                            <p className="text-xs text-zinc-500">{fmtFecha(s.fecha_inicio)} → {fmtFecha(s.fecha_expiracion)}</p>
                                        </div>
                                        <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-bold ${vigente ? 'bg-emerald-500/15 text-emerald-300' : 'bg-zinc-700 text-zinc-300'}`}>
                                            {vigente ? 'Vigente' : 'Finalizado'}
                                        </span>
                                    </div>
                                );
                            })
                        )}
                    </div>
                ) : tab === 'membresias' ? (
                    <SeccionPanel cargando={cargandoPanel} error={errorPanelMsg} onReintentar={reintentarPanel}>
                        <SeccionMembresias datos={panel?.datos || {}} onPagina={setPagina} />
                    </SeccionPanel>
                ) : tab === 'asistencia' ? (
                    <SeccionPanel cargando={cargandoPanel} error={errorPanelMsg} onReintentar={reintentarPanel}>
                        <SeccionAsistencia datos={panel?.datos || {}} onPagina={setPagina} />
                    </SeccionPanel>
                ) : tab === 'pagos' ? (
                    <SeccionPanel cargando={cargandoPanel} error={errorPanelMsg} onReintentar={reintentarPanel}>
                        <SeccionPagos datos={panel?.datos || {}} onPagina={setPagina} />
                    </SeccionPanel>
                ) : tab === 'bazar' ? (
                    <SeccionPanel cargando={cargandoPanel} error={errorPanelMsg} onReintentar={reintentarPanel}>
                        <SeccionBazar datos={panel?.datos || {}} onPagina={setPagina} />
                    </SeccionPanel>
                ) : tab === 'rms' ? (
                    <SeccionPanel cargando={cargandoPanel} error={errorPanelMsg} onReintentar={reintentarPanel}>
                        <SeccionRms datos={panel?.datos || {}} onPagina={setPagina} />
                    </SeccionPanel>
                ) : tab === 'beneficios' ? (
                    <SeccionPanel cargando={cargandoPanel} error={errorPanelMsg} onReintentar={reintentarPanel}>
                        <SeccionBeneficios datos={panel?.datos || {}} onPagina={setPagina} />
                    </SeccionPanel>
                ) : tab === 'referidos' ? (
                    <div className="space-y-4">
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide mb-2">Tu código</p>
                            <p className="text-zinc-200 text-lg font-mono">{codigoReferido?.codigo || 'Sin código asignado'}</p>
                        </div>
                        <div>
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide mb-2">Quién lo usó</p>
                            {errores.referidos && <p className="text-sm text-red-400 mb-2">⚠️ {errores.referidos}</p>}
                            {referidosUsados.length === 0 ? (
                                <p className="text-sm text-zinc-400">Nadie usó su código todavía.</p>
                            ) : (
                                <ul className="space-y-2">
                                    {referidosUsados.map((r) => (
                                        <li key={r.usuario_invitado_id} className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-800/40 px-3 py-2.5">
                                            <div className="min-w-0">
                                                <p className="text-zinc-200 font-medium truncate">{r.nombre}</p>
                                                <p className="text-xs text-zinc-500 truncate">{r.correo}</p>
                                            </div>
                                            <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-bold ${r.estado === 'convertido' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}>
                                                {r.estado === 'convertido' ? 'Convertido' : 'Pendiente'}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {/* Resumen de solo lectura: suspensiones propias (origen='alumno') */}
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                            <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide mb-2">
                                Suspensiones del alumno (solo lectura)
                            </p>
                            {errores.suspensiones && <p className="text-sm text-red-400 mb-2">⚠️ {errores.suspensiones}</p>}
                            {suspensionesPropias.length === 0 ? (
                                <p className="text-sm text-zinc-400">Sin suspensiones propias.</p>
                            ) : (
                                <ul className="space-y-2">
                                    {suspensionesPropias.map((s) => (
                                        <li key={s.id} className="flex items-center justify-between gap-3 text-sm">
                                            <span className="text-zinc-300">
                                                {fmtFecha(s.fecha_inicio)} → {fmtFecha(s.fecha_fin)} · {s.dias} día(s)
                                            </span>
                                            <span className="shrink-0 px-2 py-0.5 rounded-full text-xs font-bold bg-zinc-700 text-zinc-300 capitalize">
                                                {s.cancelada ? 'Cancelada' : s.estado}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>

                        {/* Panel de salud (crea/cancela el admin) */}
                        <SuspensionSaludPanel usuarioId={alumnoId} />
                    </div>
                )}
            </div>
        </div>
    );
};

export default FichaAlumnoTabs;

