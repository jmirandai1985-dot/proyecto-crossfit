/**
 * Modal "Dar beneficio" de Fidelización (F2): tipo → valor → plan del pase → correo.
 *
 * Qué resuelve
 * ------------
 * Antes, regalar algo era sólo un correo: no quedaba registro de qué se regaló ni de si el alumno
 * volvió. Acá el admin elige el regalo, el backend lo DA (materializa el acceso) y, si la casilla
 * "Avisar por correo" está marcada, le manda el correo EXACTO que el admin ve antes de confirmar.
 *
 * Reglas que este modal NO decide (las trae del backend)
 * -----------------------------------------------------
 *   * La ventana (`dias_vigencia`) y el tope del descuento (`tope_descuento`) los fija el box.
 *   * Si el alumno ya tiene un regalo VIVO del mismo tipo, el aviso se muestra ANTES de intentar
 *     crear (`avisos[tipo]`, el mismo texto del 409): no se manda una petición que va a fallar.
 *   * Si el alumno no tiene plan vigente, las clases gratis necesitan el plan del PASE, que se
 *     elige entre los planes no comerciales del box.
 *
 * Props:
 *   - alumno:      fila del BI (usa `usuario_id` y `alumno_nombre`).
 *   - onClose():   cerrar.
 *   - onCreado(resultado): el beneficio quedó dado (para recargar la tabla/avisar en la pantalla).
 */
import React, { useCallback, useEffect, useState } from 'react';
import api from '../services/api';
import { fmtFechaChile } from '../utils/fecha';

const ETIQUETA_CORREO = {
    enviado: '✅ Beneficio dado y correo enviado al alumno',
    simulado: '🧪 Beneficio dado · modo prueba: el correo NO salió (quedó como simulado)',
    fallido: '⚠️ El beneficio quedó dado, pero el correo no salió',
};

const BeneficioModal = ({ alumno, onClose, onCreado }) => {
    // Lo que el backend sabe del alumno ANTES de crear nada.
    const [estado, setEstado] = useState(null);
    const [tipo, setTipo] = useState(null);
    const [valor, setValor] = useState(1);
    const [planPase, setPlanPase] = useState('');
    const [avisar, setAvisar] = useState(false);
    const [preview, setPreview] = useState(null);
    const [previewando, setPreviewando] = useState(false);
    const [cargando, setCargando] = useState(true);
    const [creando, setCreando] = useState(false);
    const [error, setError] = useState('');
    const [resultado, setResultado] = useState(null);

    const alumnoId = alumno?.usuario_id;
    const nombre = alumno?.alumno_nombre || `alumno #${alumnoId}`;

    useEffect(() => {
        let vivo = true;
        const cargar = async () => {
            setCargando(true);
            setError('');
            try {
                const { data } = await api.get(`/api/v1/beneficios/alumno/${alumnoId}`);
                if (!vivo) return;
                setEstado(data);
                // Arranca en el primer tipo que el alumno PUEDE recibir hoy (sin regalo vivo).
                const disponibles = (data.tipos || []).filter((t) => !data.avisos?.[t.id]);
                const inicial = disponibles[0] || (data.tipos || [])[0];
                if (inicial) {
                    setTipo(inicial.id);
                    setValor(inicial.unidad === 'pct'
                        ? Math.min(10, data.tope_descuento)
                        : (inicial.valores || [1])[0]);
                }
            } catch (e) {
                if (vivo) {
                    setError(e.response?.data?.detail
                        || 'No se pudo cargar el estado del alumno para darle un beneficio.');
                }
            } finally {
                if (vivo) setCargando(false);
            }
        };
        if (alumnoId) cargar();
        return () => { vivo = false; };
    }, [alumnoId]);

    const entradaTipo = (estado?.tipos || []).find((t) => t.id === tipo) || null;
    const aviso = tipo ? estado?.avisos?.[tipo] : null;
    const planVigente = estado?.plan_vigente || null;
    // Las clases gratis necesitan el plan del PASE sólo si el alumno no tiene plan vigente.
    const necesitaPase = Boolean(entradaTipo?.materializa && !planVigente);
    const planesPase = estado?.planes_pase || [];
    const sinPlanPase = necesitaPase && planesPase.length === 0;
    const tieneCorreo = Boolean(estado?.alumno?.tiene_correo);
    const puedeCrear = Boolean(tipo) && !aviso && !sinPlanPase && !creando
        && (!necesitaPase || Boolean(planPase));

    const pedirPreview = useCallback(async () => {
        if (!tipo || !alumnoId) return;
        setPreviewando(true);
        setError('');
        try {
            const { data } = await api.post('/api/v1/beneficios/preview', {
                alumno_id: alumnoId, tipo, valor: Number(valor),
                plan_id: necesitaPase && planPase ? Number(planPase) : null,
            });
            setPreview(data);
        } catch (e) {
            setPreview(null);
            setError(e.response?.data?.detail || 'No se pudo generar la vista previa del correo.');
        } finally {
            setPreviewando(false);
        }
    }, [alumnoId, tipo, valor, necesitaPase, planPase]);

    useEffect(() => {
        if (avisar) pedirPreview();
        else setPreview(null);
    }, [avisar, pedirPreview]);

    const dar = async () => {
        setCreando(true);
        setError('');
        try {
            const { data } = await api.post('/api/v1/beneficios', {
                alumno_id: alumnoId, tipo, valor: Number(valor),
                plan_id: necesitaPase && planPase ? Number(planPase) : null,
                avisar_por_correo: avisar,
            });
            setResultado(data);
            onCreado?.(data);
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo dar el beneficio.');
        } finally {
            setCreando(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
            role="dialog" aria-modal="true" data-testid="modal-beneficio">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-3xl max-h-[92vh] flex flex-col">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div>
                        <h3 className="text-lg font-bold text-zinc-100">🎁 Dar beneficio</h3>
                        <p className="text-sm text-zinc-400">
                            Para <span className="text-zinc-100 font-medium">{nombre}</span>
                            {estado?.alumno?.correo && ` · ${estado.alumno.correo}`}
                        </p>
                    </div>
                    <button onClick={onClose} aria-label="Cerrar" data-testid="modal-beneficio-cerrar"
                        className="text-zinc-400 hover:text-zinc-100 text-xl leading-none">×</button>
                </div>

                <div className="p-5 space-y-4 overflow-y-auto">
                    {cargando && (
                        <div className="flex justify-center py-16">
                            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
                        </div>
                    )}

                    {!cargando && error && (
                        <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300"
                            data-testid="modal-beneficio-error">
                            {error}
                        </div>
                    )}

                    {!cargando && estado && (
                        <>
                            {/* El aviso se muestra ANTES de intentar crear: es el mismo texto que
                                devolvería el 409, así el panel no manda una petición que ya sabe
                                que va a fallar. */}
                            {aviso && (
                                <div className="bg-amber-500/10 border-l-4 border-amber-500 rounded p-3 text-sm text-amber-200"
                                    data-testid="beneficio-aviso">
                                    {aviso} Si hay que darle otro, se puede anular desde la pestaña
                                    Beneficios.
                                </div>
                            )}

                            <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                                    Qué le regalamos
                                </p>
                                <div className="flex flex-wrap gap-2" data-testid="beneficio-tipos">
                                    {(estado.tipos || []).map((t) => (
                                        <button
                                            key={t.id}
                                            type="button"
                                            data-testid={`beneficio-tipo-${t.id}`}
                                            onClick={() => {
                                                setTipo(t.id);
                                                setValor(t.unidad === 'pct'
                                                    ? Math.min(10, estado.tope_descuento)
                                                    : (t.valores || [1])[0]);
                                                setResultado(null);
                                            }}
                                            disabled={creando || Boolean(estado.avisos?.[t.id])}
                                            title={t.descripcion}
                                            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
                                                tipo === t.id
                                                    ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/40'
                                                    : 'text-zinc-300 hover:bg-zinc-800'
                                            } disabled:opacity-40`}
                                        >
                                            {t.label}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {entradaTipo && entradaTipo.unidad === 'pct' && (
                                <div>
                                    <label className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                                        Descuento (%)
                                    </label>
                                    <input
                                        type="number" min={1} max={estado.tope_descuento}
                                        value={valor} data-testid="beneficio-valor"
                                        onChange={(e) => { setValor(e.target.value); setResultado(null); }}
                                        className="w-32 bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                                    />
                                    <span className="ml-3 text-xs text-zinc-500">
                                        Este box autoriza hasta {estado.tope_descuento} %.
                                    </span>
                                </div>
                            )}

                            {entradaTipo && entradaTipo.unidad === 'clases' && (
                                <div>
                                    <label className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                                        Clases de regalo
                                    </label>
                                    <select
                                        value={valor} data-testid="beneficio-valor"
                                        onChange={(e) => { setValor(e.target.value); setResultado(null); }}
                                        className="bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                                    >
                                        {(entradaTipo.valores || []).map((v) => (
                                            <option key={v} value={v}>{v}</option>
                                        ))}
                                    </select>
                                </div>
                            )}

                            {necesitaPase && (
                                <div>
                                    <label className="block text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-1">
                                        Plan del pase
                                    </label>
                                    {sinPlanPase ? (
                                        <p className="text-sm text-red-300">
                                            No tiene plan vigente y este box no tiene un plan de pase
                                            configurado (un plan no comercial): sin él no hay acceso
                                            que regalarle.
                                        </p>
                                    ) : (
                                        <select
                                            value={planPase} data-testid="beneficio-plan-pase"
                                            onChange={(e) => setPlanPase(e.target.value)}
                                            className="bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                                        >
                                            <option value="">Elegir el plan del pase…</option>
                                            {planesPase.map((p) => (
                                                <option key={p.id} value={p.id}>{p.nombre}</option>
                                            ))}
                                        </select>
                                    )}
                                </div>
                            )}

                            {/* Qué va a pasar, con los datos REALES del alumno (no una suposición). */}
                            {entradaTipo && (
                                <p className="text-xs text-zinc-400" data-testid="beneficio-efecto">
                                    {entradaTipo.unidad === 'pct' ? (
                                        <>Se le aplica al solicitar su próximo plan: va a ver el precio final con el descuento hecho. </>
                                    ) : planVigente ? (
                                        <>Se SUMAN a su plan vigente <span className="text-zinc-200">{planVigente.nombre}</span> (vence el {fmtFechaChile(planVigente.vence)}). </>
                                    ) : (
                                        <>Se le abre un pase con esas clases, sin esperar ningún pago. </>
                                    )}
                                    Vigencia: {estado.dias_vigencia} días desde que lo des.
                                </p>
                            )}

                            <label className="flex items-center gap-2 text-sm text-zinc-300">
                                <input
                                    type="checkbox" checked={avisar} data-testid="beneficio-avisar"
                                    onChange={(e) => { setAvisar(e.target.checked); setResultado(null); }}
                                    disabled={!tieneCorreo || creando}
                                    className="accent-orange-500"
                                />
                                Avisar por correo
                                {!tieneCorreo && (
                                    <span className="text-xs text-zinc-500">
                                        (el alumno no tiene correo registrado)
                                    </span>
                                )}
                            </label>

                            {avisar && (
                                <div className="space-y-3">
                                    {previewando && (
                                        <div className="flex justify-center py-8">
                                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                                        </div>
                                    )}
                                    {!previewando && preview && (
                                        <>
                                            <div className="bg-zinc-800/60 rounded-lg p-3 text-sm">
                                                <p className="text-zinc-400">
                                                    <span className="text-zinc-500">Asunto:</span>{' '}
                                                    <span className="text-zinc-100 font-medium"
                                                        data-testid="beneficio-preview-asunto">
                                                        {preview.asunto}
                                                    </span>
                                                </p>
                                            </div>
                                            <iframe
                                                title="Vista previa del correo del beneficio"
                                                srcDoc={preview.html}
                                                sandbox=""
                                                data-testid="beneficio-preview-html"
                                                className="w-full h-72 bg-white rounded-lg border border-zinc-700"
                                            />
                                        </>
                                    )}
                                </div>
                            )}

                            {resultado && (
                                <p className={`text-sm rounded p-3 border-l-4 ${
                                    resultado.correo?.estado === 'fallido'
                                        ? 'bg-amber-500/10 border-amber-500 text-amber-200'
                                        : 'bg-emerald-500/10 border-emerald-500 text-emerald-300'
                                }`}
                                    data-testid="beneficio-resultado">
                                    {resultado.correo
                                        ? (ETIQUETA_CORREO[resultado.correo.estado]
                                           || resultado.correo.estado)
                                        : '✅ Beneficio dado (sin avisar por correo)'}
                                    {resultado.correo?.detalle_error
                                        && ` · ${resultado.correo.detalle_error}`}
                                    {resultado.beneficio?.vigente_hasta
                                        && ` · vale hasta el ${fmtFechaChile(resultado.beneficio.vigente_hasta)}`}
                                </p>
                            )}
                        </>
                    )}
                </div>

                <div className="p-5 border-t border-zinc-800 flex justify-end gap-2">
                    <button onClick={onClose} data-testid="modal-beneficio-cancelar"
                        className="px-4 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700">
                        {resultado ? 'Cerrar' : 'Cancelar'}
                    </button>
                    <button
                        onClick={dar}
                        disabled={!puedeCrear || Boolean(resultado)}
                        data-testid="beneficio-confirmar"
                        className="px-4 py-2 bg-orange-600 text-white rounded-lg text-sm font-bold hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {creando ? 'Dando el beneficio...' : 'Dar beneficio'}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default BeneficioModal;
