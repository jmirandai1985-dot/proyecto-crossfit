import React, { useEffect, useMemo, useState } from 'react';
import api from '../services/api';
// Stats + agrupación por mes de asistencia: las MISMAS funciones puras que usa
// "Mis Reservas" del alumno (una sola fuente, sin red extra).
import { agruparReservasPorMes, calcularEstadisticasReservas } from '../utils/reservasEstadisticas';
// Vigente/Finalizado de la pestaña Planes (regla pura, testeada en `test:ficha-alumno`).
import { esSuscripcionVigente } from '../utils/fichaAlumno';
import { fmtFechaChile, hoyChileStr } from '../utils/fecha';
import { getEstadoColor, getEstadoDisplay } from '../utils/estadoReserva';

const TABS = [
    { key: 'resumen', label: 'Resumen' },
    { key: 'datos', label: 'Datos' },
    { key: 'planes', label: 'Planes' },
    { key: 'referidos', label: 'Referidos' },
    { key: 'asistencia', label: 'Asistencia' },
];

/**
 * Ficha de consulta rápida de un alumno con 5 pestañas (vista admin, no es el modal
 * chico `AlumnoFichaModal`). Carga todo por `Promise.allSettled`: cada bloque se
 * resuelve aparte y muestra su propio error, sin dejar la ficha en blanco por un
 * solo fallo.
 */
const FichaAlumnoTabs = ({ alumnoId, nombre }) => {
    const [tab, setTab] = useState('resumen');
    const [data, setData] = useState(null);
    const [suscripcion, setSuscripcion] = useState(null);
    const [planes, setPlanes] = useState([]);
    const [codigoReferido, setCodigoReferido] = useState(null);
    const [suscripciones, setSuscripciones] = useState([]);
    const [referidosUsados, setReferidosUsados] = useState([]);
    const [reservas, setReservas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [errores, setErrores] = useState({});

    useEffect(() => {
        if (!alumnoId) return;
        setLoading(true);
        setErrores({});
        const carga = async () => {
            const [usr, sus, plan, cod, suscHist, refs, resv] = await Promise.allSettled([
                api.get(`/api/v1/usuarios/${alumnoId}`),
                api.get('/api/v1/suscripciones', { params: { usuario_id: alumnoId, estado: 'activo' } }),
                api.get('/api/v1/planes'),
                api.get(`/api/v1/admin/alumnos/${alumnoId}/codigo-referido`),
                api.get('/api/v1/suscripciones', { params: { usuario_id: alumnoId } }),
                api.get(`/api/v1/admin/alumnos/${alumnoId}/referidos-usados`),
                api.get('/api/v1/reservas', { params: { usuario_id: alumnoId, limit: 200 } }),
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

            if (resv.status === 'fulfilled') setReservas(Array.isArray(resv.value.data) ? resv.value.data : []);
            else errs.reservas = det(resv);

            setErrores(errs);
            setLoading(false);
        };
        carga();
    }, [alumnoId]);

    // Al cambiar de alumno se vuelve a la pestaña Resumen.
    useEffect(() => { setTab('resumen'); }, [alumnoId]);

    const planActivo = planes.find((p) => p.id === suscripcion?.plan_id);
    const stats = useMemo(() => calcularEstadisticasReservas(reservas, hoyChileStr()), [reservas]);
    const historialMeses = useMemo(() => agruparReservasPorMes(reservas), [reservas]);
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

            <div className="flex gap-1 px-3 pt-3 border-b border-zinc-800 overflow-x-auto">
                {TABS.map((t) => (
                    <button
                        key={t.key}
                        type="button"
                        onClick={() => setTab(t.key)}
                        className={`px-3 py-2 text-sm font-medium rounded-t-lg transition-colors whitespace-nowrap ${tab === t.key ? 'text-orange-400 border-b-2 border-orange-500 bg-zinc-800/60' : 'text-zinc-400 hover:text-zinc-200'}`}
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
                        {errores.reservas && <p className="text-sm text-red-400">⚠️ {errores.reservas}</p>}
                        <div className="grid grid-cols-3 gap-3">
                            <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 p-3">
                                <p className="text-xs text-zinc-500">Clases este mes</p>
                                <p className="text-2xl font-bold text-zinc-100">{stats.clasesEsteMes}</p>
                            </div>
                            <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 p-3">
                                <p className="text-xs text-zinc-500">Asistidas</p>
                                <p className="text-2xl font-bold text-zinc-100">{stats.asistidasEsteMes}</p>
                            </div>
                            <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 p-3">
                                <p className="text-xs text-zinc-500">% Asistencia</p>
                                <p className="text-2xl font-bold text-zinc-100">{stats.pctAsistencia}%</p>
                            </div>
                        </div>
                        {historialMeses.length === 0 ? (
                            <p className="text-sm text-zinc-400">Sin historial de asistencia.</p>
                        ) : (
                            historialMeses.map((g) => (
                                <div key={g.clave}>
                                    <p className="text-xs font-bold text-zinc-400 uppercase tracking-wide mb-2">{g.label}</p>
                                    <ul className="space-y-1.5">
                                        {g.reservas.map((r) => (
                                            <li key={r.id} className="flex items-center justify-between gap-2 text-sm">
                                                <span className="text-zinc-200 truncate">🏋️ {r.disciplina_nombre || 'Clase'}</span>
                                                <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-medium border ${getEstadoColor(r.estado_visible)}`}>
                                                    {getEstadoDisplay(r.estado_visible)}
                                                </span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            ))
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default FichaAlumnoTabs;

