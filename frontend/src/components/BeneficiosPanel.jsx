/**
 * Pestaña "Beneficios" de Fidelización (F2): TODOS los regalos del box, con filtros y anulación.
 *
 * Qué muestra
 * -----------
 * Los cuatro estados REALES de un regalo —vigente, usado, vencido y anulado— con su fecha de
 * vigencia, si el alumno ya lo usó (y cuántos días tardó) y con qué motivo se anuló, más el bloque
 * de métricas de efectividad de la F4 (tasa de uso, descuento aplicado, días hasta volver).
 *
 * Dos reglas que define el BACKEND y esta pantalla sólo dibuja:
 *   * `estado` viene calculado con `esta_vivo()`: un `ofrecido` cuya ventana pasó llega `vencido`
 *     aunque la fila todavía diga `ofrecido` (la lectura no escribe).
 *   * El resumen se calcula sobre el FILTRO activo (no sobre la página): por eso las métricas dicen
 *     "sobre lo filtrado" y no cambian al pasar de página.
 *
 * Props:
 *   - onVerAlumno(alumnoId): abrir la ficha del alumno (clic en su nombre).
 *   - onMensaje(texto): avisar en la pantalla (el mismo cartel que usa Fidelización).
 */
import React, { useCallback, useEffect, useState } from 'react';
import api from '../services/api';
import { fmtFechaChile } from '../utils/fecha';

const ESTADOS = [
    { id: 'todos', label: 'Todos' },
    { id: 'vigente', label: 'Vigentes' },
    { id: 'usado', label: 'Usados' },
    { id: 'vencido', label: 'Vencidos' },
    { id: 'anulado', label: 'Anulados' },
];

const ETIQUETA_ESTADO = {
    vigente: 'bg-emerald-500/15 text-emerald-300 border-emerald-600',
    usado: 'bg-sky-500/15 text-sky-300 border-sky-600',
    vencido: 'bg-zinc-700/40 text-zinc-300 border-zinc-600',
    anulado: 'bg-red-500/10 text-red-300 border-red-700',
};

const clp = (valor) => (valor == null ? '—' : `$${Number(valor).toLocaleString('es-CL')}`);

const BeneficiosPanel = ({ onVerAlumno, onMensaje }) => {
    const [estado, setEstado] = useState('todos');
    const [tipo, setTipo] = useState('');
    const [busqueda, setBusqueda] = useState('');
    const [pagina, setPagina] = useState(1);
    const [datos, setDatos] = useState(null);
    const [cargando, setCargando] = useState(true);
    const [error, setError] = useState('');
    const [anular, setAnular] = useState(null);     // el beneficio que se está anulando
    const [motivo, setMotivo] = useState('');
    const [anulando, setAnulando] = useState(false);

    const cargar = useCallback(async () => {
        setCargando(true);
        setError('');
        try {
            const { data } = await api.get('/api/v1/beneficios', {
                params: {
                    estado, tipo: tipo || undefined,
                    q: busqueda || undefined, pagina, por_pagina: 25,
                },
            });
            setDatos(data);
        } catch (e) {
            setDatos(null);
            setError(e.response?.data?.detail || 'No se pudieron cargar los beneficios.');
        } finally {
            setCargando(false);
        }
    }, [estado, tipo, busqueda, pagina]);

    useEffect(() => { cargar(); }, [cargar]);

    // Los filtros vuelven a la página 1: si no, un filtro que acorta la lista deja al usuario
    // mirando una página vacía sin entender por qué.
    const cambiar = (setter) => (valor) => { setter(valor); setPagina(1); };

    const confirmarAnulacion = async () => {
        setAnulando(true);
        setError('');
        try {
            const { data } = await api.post(`/api/v1/beneficios/${anular.id}/anular`,
                { motivo });
            setAnular(null);
            setMotivo('');
            onMensaje?.(`🗑️ Beneficio de ${data.beneficio.alumno_nombre || `alumno #${data.beneficio.alumno_id}`} anulado: ${data.beneficio.anulado_motivo}`);
            await cargar();
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo anular el beneficio.');
        } finally {
            setAnulando(false);
        }
    };

    const resumen = datos?.resumen || null;
    const items = datos?.items || [];
    const totalPaginas = datos ? Math.max(1, Math.ceil(datos.total / datos.por_pagina)) : 1;

    return (
        <div className="space-y-6">
            {/* ── Métricas de efectividad (el espacio que la F4 llena con estos mismos números) ── */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
                <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
                    <h2 className="font-semibold text-white">📈 Efectividad de los beneficios (F4)</h2>
                    <p className="text-xs text-zinc-500">
                        Sobre lo filtrado{resumen ? ` (${resumen.total} beneficios)` : ''} · los
                        números salen de la tabla, no de una proyección
                    </p>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
                    {[
                        { label: 'Vigentes', valor: resumen?.por_estado?.vigente ?? 0, borde: 'border-emerald-600' },
                        { label: 'Usados', valor: resumen?.por_estado?.usado ?? 0, borde: 'border-sky-500' },
                        { label: 'Vencidos', valor: resumen?.por_estado?.vencido ?? 0, borde: 'border-zinc-600' },
                        { label: 'Anulados', valor: resumen?.por_estado?.anulado ?? 0, borde: 'border-red-600' },
                        { label: 'Tasa de uso', valor: resumen?.tasa_uso_pct == null ? '—' : `${resumen.tasa_uso_pct}%`, borde: 'border-orange-500' },
                        { label: 'Días hasta volver', valor: resumen?.dias_hasta_uso_promedio ?? '—', borde: 'border-purple-500' },
                        { label: 'Descuento aplicado', valor: clp(resumen?.descuento_clp_total), borde: 'border-amber-500' },
                    ].map(({ label, valor, borde }) => (
                        <div key={label} className={`bg-zinc-800/60 rounded-lg border-l-4 ${borde} p-3`}
                            data-testid={`beneficios-metrica-${label}`}>
                            <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">{label}</p>
                            <p className="mt-1 text-xl font-bold text-white">{valor}</p>
                        </div>
                    ))}
                </div>
                {resumen && (
                    <p className="mt-3 text-xs text-zinc-500">
                        {resumen.con_correo} avisados por correo · {resumen.sin_correo} dados sin correo
                        {' '}(la casilla "Avisar por correo" es opcional: el regalo vale igual)
                    </p>
                )}
            </div>

            {/* ── Filtros ── */}
            <div className="flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1 text-xs text-zinc-400">
                    Estado
                    <select value={estado} data-testid="beneficios-filtro-estado"
                        onChange={(e) => cambiar(setEstado)(e.target.value)}
                        className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-orange-500">
                        {ESTADOS.map((e) => (
                            <option key={e.id} value={e.id}>{e.label}</option>
                        ))}
                    </select>
                </label>
                <label className="flex flex-col gap-1 text-xs text-zinc-400">
                    Tipo
                    <select value={tipo} data-testid="beneficios-filtro-tipo"
                        onChange={(e) => cambiar(setTipo)(e.target.value)}
                        className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-orange-500">
                        <option value="">Todos</option>
                        <option value="descuento">Descuento en su próximo plan</option>
                        <option value="clases_gratis">Clases gratis</option>
                    </select>
                </label>
                <label className="flex flex-col gap-1 text-xs text-zinc-400">
                    Alumno
                    <input value={busqueda} data-testid="beneficios-filtro-busqueda"
                        onChange={(e) => cambiar(setBusqueda)(e.target.value)}
                        placeholder="Nombre o correo"
                        className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-orange-500" />
                </label>
                <button type="button" onClick={cargar}
                    className="px-3 py-1.5 bg-zinc-800 text-zinc-200 rounded-lg text-xs font-medium hover:bg-zinc-700">
                    🔄 Recargar
                </button>
                <span className="text-xs text-zinc-500">
                    {datos ? `${datos.total} beneficios con este filtro` : ''}
                </span>
            </div>

            {error && (
                <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300"
                    data-testid="beneficios-error">
                    {error}
                </div>
            )}

            <div className="bg-zinc-900 rounded-lg shadow overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-amber-800 text-white">
                            <tr>
                                <th className="px-4 py-3 text-left text-sm font-medium">Alumno</th>
                                <th className="px-4 py-3 text-left text-sm font-medium">Beneficio</th>
                                <th className="px-4 py-3 text-left text-sm font-medium">Estado</th>
                                <th className="px-4 py-3 text-left text-sm font-medium">Vigencia</th>
                                <th className="px-4 py-3 text-left text-sm font-medium">Uso</th>
                                <th className="px-4 py-3 text-left text-sm font-medium">Correo</th>
                                <th className="px-4 py-3 text-left text-sm font-medium">Acción</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800" data-testid="beneficios-tabla">
                            {cargando && (
                                <tr>
                                    <td colSpan={7} className="px-4 py-8 text-center">
                                        <div className="flex justify-center">
                                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                                        </div>
                                    </td>
                                </tr>
                            )}
                            {!cargando && items.length === 0 && (
                                <tr>
                                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-zinc-500">
                                        No hay beneficios que cumplan este filtro.
                                    </td>
                                </tr>
                            )}
                            {!cargando && items.map((b, idx) => (
                                <tr key={b.id} data-testid={`beneficio-fila-${b.id}`}
                                    className={idx % 2 === 0 ? 'bg-zinc-900' : 'bg-zinc-800/50'}>
                                    <td className="px-4 py-3">
                                        <button type="button" onClick={() => onVerAlumno?.(b.alumno_id)}
                                            className="text-sm font-bold text-zinc-100 hover:text-orange-300 underline decoration-dotted"
                                            title="Ver la ficha del alumno">
                                            {b.alumno_nombre || `Alumno #${b.alumno_id}`}
                                        </button>
                                        <p className="text-xs text-zinc-500">
                                            #{b.alumno_id}{b.alumno_correo ? ` · ${b.alumno_correo}` : ''}
                                        </p>
                                    </td>
                                    <td className="px-4 py-3 text-sm text-zinc-300">
                                        {b.tipo_label}
                                        <span className="ml-1 font-bold text-zinc-100">
                                            {b.unidad === 'pct'
                                                ? `−${b.valor} %`
                                                : `${b.valor} clase${b.valor === 1 ? '' : 's'}`}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`inline-block px-2 py-0.5 rounded-full border text-xs ${ETIQUETA_ESTADO[b.estado] || ''}`}>
                                            {b.estado}
                                        </span>
                                        {b.aviso && (
                                            <p className="mt-1 text-[11px] text-amber-300"
                                                data-testid={`beneficio-aviso-${b.id}`}>{b.aviso}</p>
                                        )}
                                    </td>

                                    <td className="px-4 py-3 text-xs text-zinc-400">
                                        dado el {fmtFechaChile(b.created_at)}
                                        <br />hasta el <span className="text-zinc-200">{fmtFechaChile(b.vigente_hasta)}</span>
                                    </td>
                                    <td className="px-4 py-3 text-xs text-zinc-400">
                                        {b.estado === 'usado' ? (
                                            <>
                                                {fmtFechaChile(b.usado_en)}
                                                {b.dias_hasta_uso != null && ` (${b.dias_hasta_uso} días)`}
                                                {b.descuento_clp != null && <><br />{clp(b.descuento_clp)}</>}
                                            </>
                                        ) : '—'}
                                    </td>
                                    <td className="px-4 py-3 text-xs text-zinc-400">
                                        {b.notificacion_id ? `avisado (#${b.notificacion_id})` : 'sin correo'}
                                    </td>
                                    <td className="px-4 py-3">
                                        {b.puede_anular ? (
                                            <button type="button"
                                                onClick={() => { setAnular(b); setMotivo(''); }}
                                                data-testid={`beneficio-anular-${b.id}`}
                                                className="px-3 py-1.5 bg-red-600/90 text-white rounded-lg text-xs font-bold hover:bg-red-700">
                                                Anular
                                            </button>
                                        ) : (
                                            <span className="text-xs text-zinc-500">
                                                {b.estado === 'usado' ? 'ya usado' : '—'}
                                            </span>
                                        )}
                                        {b.estado === 'anulado' && b.anulado_motivo && (
                                            <p className="mt-1 text-[11px] text-zinc-500">{b.anulado_motivo}</p>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {datos && totalPaginas > 1 && (
                <div className="flex items-center justify-end gap-3 text-sm">
                    <button type="button" disabled={pagina <= 1}
                        onClick={() => setPagina(pagina - 1)}
                        className="px-3 py-1.5 bg-zinc-800 text-zinc-200 rounded-lg text-xs font-medium hover:bg-zinc-700 disabled:opacity-40">
                        ← Anterior
                    </button>
                    <span className="text-xs text-zinc-500">Página {datos.pagina} de {totalPaginas}</span>
                    <button type="button" disabled={pagina >= totalPaginas}
                        onClick={() => setPagina(pagina + 1)}
                        className="px-3 py-1.5 bg-zinc-800 text-zinc-200 rounded-lg text-xs font-medium hover:bg-zinc-700 disabled:opacity-40">
                        Siguiente →
                    </button>
                </div>
            )}

            {/* ── Anulación: el motivo es obligatorio (el backend no anula sin él) ── */}
            {anular && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                    role="dialog" aria-modal="true" data-testid="modal-anular">
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-lg">
                        <div className="p-5 border-b border-zinc-800">
                            <h3 className="text-lg font-bold text-zinc-100">Anular beneficio</h3>
                            <p className="text-sm text-zinc-400">
                                {anular.tipo_label} de {anular.alumno_nombre || `alumno #${anular.alumno_id}`}
                                {' '}({anular.unidad === 'pct' ? `−${anular.valor} %` : `${anular.valor} clases`}).
                                Se le quita lo que el regalo le había dado.
                            </p>
                        </div>
                        <div className="p-5 space-y-3">
                            <label className="block text-xs font-semibold uppercase tracking-wide text-zinc-500">
                                Motivo (obligatorio)
                            </label>
                            <textarea
                                value={motivo} rows={3} data-testid="anular-motivo"
                                onChange={(e) => setMotivo(e.target.value)}
                                placeholder="Por qué se anula (queda en la auditoría del beneficio)"
                                className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                            />
                        </div>
                        <div className="p-5 border-t border-zinc-800 flex justify-end gap-2">
                            <button type="button" onClick={() => setAnular(null)}
                                className="px-4 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700">
                                Cancelar
                            </button>
                            <button type="button" onClick={confirmarAnulacion}
                                disabled={motivo.trim().length < 3 || anulando}
                                data-testid="anular-confirmar"
                                className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-bold hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed">
                                {anulando ? 'Anulando...' : 'Anular beneficio'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default BeneficiosPanel;
