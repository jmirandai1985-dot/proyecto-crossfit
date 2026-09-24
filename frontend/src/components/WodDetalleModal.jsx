import React, { useEffect } from 'react';

/**
 * Modal de SOLO LECTURA con el detalle completo de un WOD publicado.
 *
 * Punto 1 del panel Coach (Gestión de Clases): la tarjeta de una clase con WOD
 * publicado solo mostraba el título; al hacer clic se abre este modal con la
 * información completa, con el MISMO orden y rótulos que el formulario de
 * crear/editar el WOD (Título, Calentamiento, Fuerza/Habilidad, WOD Principal,
 * Tipo Metcon) más los movimientos estructurados si el WOD se cargó por parser.
 *
 * Props:
 *  - wod: WOD completo (GET /wods/{id}); null mientras carga
 *  - clase: {id, fecha, hora_inicio, hora_fin, disciplina_nombre} de la tarjeta
 *  - loading / error: estado de la carga
 *  - onClose: cierra el modal
 *  - accion: { etiqueta, onClick } opcional para ofrecer un paso siguiente
 *    (p. ej. "Abrir en Gestión de Clases")
 */

// Sin `new Date()`: evita el corrimiento de día por zona horaria (UTC vs Chile).
const formatearFecha = (f) => {
    if (!f) return '';
    const [a, m, d] = String(f).slice(0, 10).split('-');
    return (a && m && d) ? `${d}-${m}-${a}` : String(f);
};

const hora = (h) => (h ? String(h).slice(0, 5) : '');

const Seccion = ({ titulo, children }) => (
    <div>
        <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">{titulo}</p>
        <div className="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded-lg p-3">
            {children}
        </div>
    </div>
);

const WodDetalleModal = ({ wod, clase, loading = false, error = '', onClose, accion }) => {
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    const vacio = (t) => !t || !String(t).trim();
    const fecha = clase?.fecha || wod?.fecha;
    const hIni = clase?.hora_inicio || wod?.hora_inicio;
    const hFin = clase?.hora_fin || wod?.hora_fin;
    const fases = (wod?.fases || []).filter(f => (f?.movimientos || []).length > 0);
    const estado = (wod?.estado || '').toLowerCase();

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
            onClick={onClose}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label="Detalle del WOD"
                className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="sticky top-0 bg-emerald-700 text-white px-5 py-4 flex items-start justify-between gap-4 rounded-t-xl">
                    <div className="min-w-0">
                        <p className="text-[11px] uppercase tracking-wider text-emerald-200 font-bold">Detalle del WOD</p>
                        <h2 className="text-xl font-bold truncate">{wod?.titulo?.trim() || 'WOD sin título'}</h2>
                        <p className="text-emerald-100 text-xs mt-1">
                            {clase?.disciplina_nombre ? `${clase.disciplina_nombre} · ` : ''}
                            {formatearFecha(fecha)}
                            {hIni ? ` · ${hora(hIni)} - ${hora(hFin)}` : ''}
                            {clase?.id ? ` · Clase #${clase.id}` : ''}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Cerrar"
                        data-testid="cerrar-wod-detalle"
                        className="shrink-0 text-white/80 hover:text-white text-3xl leading-none w-8 h-8 flex items-center justify-center rounded hover:bg-white/10 transition-colors"
                    >&times;</button>
                </div>

                <div className="p-5 space-y-4">
                    {loading && <p className="text-sm text-gray-500">Cargando el WOD…</p>}
                    {error && (
                        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-3 text-sm">
                            {error}
                        </div>
                    )}

                    {!loading && !error && wod && (
                        <>
                            <div className="flex flex-wrap items-center gap-2">
                                <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${estado === 'publicado'
                                    ? 'bg-emerald-100 text-emerald-700'
                                    : 'bg-gray-100 text-gray-600'}`}>
                                    {estado === 'publicado' ? 'PUBLICADO' : (estado ? estado.toUpperCase() : 'SIN ESTADO')}
                                </span>
                                {!vacio(wod.tipo_metcon) && (
                                    <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-100 text-amber-700">
                                        {wod.tipo_metcon}
                                    </span>
                                )}
                            </div>

                            {!vacio(wod.descripcion) && (
                                <Seccion titulo="Descripción">{wod.descripcion}</Seccion>
                            )}

                            <Seccion titulo="Calentamiento">
                                {vacio(wod.calentamiento)
                                    ? <span className="text-gray-400 italic">Sin calentamiento cargado</span>
                                    : wod.calentamiento}
                            </Seccion>

                            <Seccion titulo="Fuerza / Habilidad">
                                {vacio(wod.fuerza_habilidad)
                                    ? <span className="text-gray-400 italic">Sin bloque de fuerza/habilidad</span>
                                    : wod.fuerza_habilidad}
                            </Seccion>

                            <Seccion titulo="WOD Principal">
                                {vacio(wod.wod_principal)
                                    ? <span className="text-gray-400 italic">Sin WOD principal cargado</span>
                                    : wod.wod_principal}
                            </Seccion>

                            {fases.length > 0 && (
                                <div>
                                    <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                                        Movimientos estructurados
                                    </p>
                                    <div className="space-y-3">
                                        {fases.map((fase, fi) => (
                                            <div key={fi} className="border border-gray-200 rounded-lg p-3">
                                                <p className="text-xs font-bold text-emerald-700 uppercase tracking-wide mb-2">
                                                    {fase.nombre || 'FASE'}
                                                </p>
                                                <ul className="space-y-1">
                                                    {fase.movimientos.map((m, mi) => (
                                                        <li key={mi} className="text-sm text-gray-700 flex flex-wrap items-center gap-2">
                                                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                                            <span className="font-medium">{m.nombre || `Movimiento #${m.movimiento_id}`}</span>
                                                            {m.series ? <span className="text-gray-500">{m.series}x</span> : null}
                                                            {m.repeticiones ? <span className="text-gray-500">{m.repeticiones}</span> : null}
                                                            {m.peso ? <span className="text-gray-400">@ {m.peso} kg</span> : null}
                                                            {m.tiempo ? <span className="text-gray-400">{m.tiempo}</span> : null}
                                                            {m.notas ? <span className="text-gray-400 italic">{m.notas}</span> : null}
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                                <p className="text-[11px] text-gray-400">
                                    Vista de solo lectura.
                                </p>
                                {accion?.onClick && (
                                    <button
                                        type="button"
                                        data-testid="wod-detalle-accion"
                                        onClick={accion.onClick}
                                        className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-bold hover:bg-emerald-700 transition-colors"
                                    >
                                        {accion.etiqueta || 'Abrir'}
                                    </button>
                                )}
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default WodDetalleModal;
