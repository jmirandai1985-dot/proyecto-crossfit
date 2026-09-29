/**
 * Modal "Enviar correo" de Fidelización (F1): elegir plantilla → VER el correo exacto → enviar.
 *
 * Antes la Acción Rápida mandaba el correo a ciegas. Acá el mensaje lo renderiza el BACKEND
 * (`POST /fidelizacion/preview`, el mismo render que usa el envío), así que lo que el admin
 * aprueba es literalmente lo que recibe el alumno.
 *
 * El catálogo viene de `GET /fidelizacion/plantillas` y el frontend dibuja SOLO lo que recibe:
 * el grupo `beneficios` (Fase 2) queda oculto porque el backend no lo manda, no por un flag
 * escondido acá.
 *
 * Props:
 *   - alumno:           fila del BI (usa `usuario_id`, `alumno_nombre` y `alumno_correo`).
 *   - onClose():        cerrar.
 *   - onEnviado(resultado): el correo SALIÓ de verdad (no en modo prueba) y quedó registrado.
 *
 * La plantilla con la que arranca la elige el BACKEND (`POST /fidelizacion/sugerir`): la pantalla
 * no tiene su propia heurística (con 5 plantillas, "si vence en ≤5 días → vencimiento, si no →
 * inactividad" nunca podría sugerir las otras tres). El modal muestra la regla y el motivo para
 * que el admin sepa POR QUÉ se sugirió esa.
 */
import React, { useCallback, useEffect, useState } from 'react';
import api from '../services/api';

const ETIQUETA_ESTADO = {
    enviado: '✅ Correo enviado',
    simulado: '🧪 Modo prueba: el correo NO se envió (quedó registrado como simulado)',
    fallido: '❌ No se pudo enviar el correo',
};

const ModalEnviarCorreo = ({ alumno, onClose, onEnviado }) => {
    const [catalogo, setCatalogo] = useState(null);
    const [sugerencia, setSugerencia] = useState(null);
    const [plantilla, setPlantilla] = useState(null);
    const [preview, setPreview] = useState(null);
    const [cargando, setCargando] = useState(true);
    const [previewando, setPreviewando] = useState(false);
    const [enviando, setEnviando] = useState(false);
    const [error, setError] = useState('');
    const [resultado, setResultado] = useState(null);

    const alumnoId = alumno?.usuario_id;

    // ── Catálogo + sugerencia ──
    const cargarCatalogo = useCallback(async () => {
        setCargando(true);
        setError('');
        try {
            const { data } = await api.get('/api/v1/fidelizacion/plantillas');
            setCatalogo(data);
            const disponibles = (data?.plantillas || []).map((p) => p.id);
            // La sugerencia la define el backend. Si ese pedido falla, el modal sigue sirviendo
            // (se elige la plantilla a mano): no se rompe el envío por una comodidad.
            let propuesta = null;
            try {
                const r = await api.post('/api/v1/fidelizacion/sugerir', { alumno_id: alumnoId });
                propuesta = r.data;
                setSugerencia(r.data);
            } catch {
                // Si el pedido de la sugerencia falla, el modal sigue sirviendo (se elige a mano):
                // el envío no se cae por una comodidad.
                setSugerencia(null);
            }
            // La sugerencia manda sólo si existe en el catálogo (el backend es el dueño de qué
            // se puede mandar): si no, se usa la primera disponible.
            const inicial = propuesta?.plantilla;
            setPlantilla(
                inicial && disponibles.includes(inicial) ? inicial : (disponibles[0] || null)
            );
        } catch (e) {
            setCatalogo(null);
            setError(e.response?.data?.detail || 'No se pudo cargar el catálogo de plantillas.');
        } finally {
            setCargando(false);
        }
    }, [alumnoId]);

    useEffect(() => { cargarCatalogo(); }, [cargarCatalogo]);

    // ── Preview (se rehace al cambiar de plantilla: el texto usa datos reales) ──
    const verPreview = useCallback(async () => {
        if (!plantilla || !alumnoId) return;
        setPreviewando(true);
        setError('');
        setResultado(null);
        try {
            const { data } = await api.post('/api/v1/fidelizacion/preview', {
                plantilla,
                alumno_id: alumnoId,
            });
            setPreview(data);
        } catch (e) {
            setPreview(null);
            setError(e.response?.data?.detail
                || 'No se pudo generar la vista previa de este correo.');
        } finally {
            setPreviewando(false);
        }
    }, [plantilla, alumnoId]);

    useEffect(() => { verPreview(); }, [verPreview]);

    // ── Envío ──
    const enviar = async () => {
        setEnviando(true);
        setError('');
        try {
            const { data } = await api.post('/api/v1/fidelizacion/enviar', {
                plantilla,
                alumno_id: alumnoId,
            });
            setResultado(data);
            // En modo prueba NO se avisa como enviado: la gestión no se marca.
            if (data?.ok && data?.estado === 'enviado') onEnviado?.(data);
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo enviar el correo.');
        } finally {
            setEnviando(false);
        }
    };

    const plantillas = catalogo?.plantillas || [];
    const seleccionada = plantillas.find((p) => p.id === plantilla) || null;
    const enModoPrueba = catalogo?.modo_envio === 'noop';
    const yaEnviado = resultado?.ok === true;


    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
            role="dialog" aria-modal="true" data-testid="modal-enviar-correo">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-3xl max-h-[92vh] flex flex-col">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div>
                        <h3 className="text-lg font-bold text-zinc-100">Enviar correo</h3>
                        <p className="text-sm text-zinc-400">
                            Para <span className="text-zinc-100 font-medium">
                                {alumno?.alumno_nombre || `alumno #${alumnoId}`}
                            </span>
                            {alumno?.alumno_correo && ` · ${alumno.alumno_correo}`}
                        </p>
                    </div>
                    <button onClick={onClose} aria-label="Cerrar"
                        data-testid="modal-correo-cerrar"
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
                            data-testid="modal-correo-error">
                            <p className="font-medium">⚠️ {error}</p>
                            <button type="button" onClick={verPreview}
                                className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-xs font-bold hover:bg-red-700">
                                Reintentar
                            </button>
                        </div>
                    )}

                    {!cargando && enModoPrueba && (
                        <p className="text-xs text-amber-300 bg-amber-500/10 border-l-4 border-amber-500 rounded p-3"
                            data-testid="modal-correo-modo-prueba">
                            Modo prueba (<code>EMAIL_MODO=noop</code>): el correo se registra pero NO sale.
                        </p>
                    )}

                    {!cargando && !error && (
                        <>
                            <div>
                                <p className="text-xs font-bold uppercase tracking-wide text-zinc-400 mb-2">
                                    Plantilla
                                </p>
                                <div className="flex flex-wrap gap-2" data-testid="modal-correo-plantillas">
                                    {plantillas.map((p) => (
                                        <button
                                            key={p.id}
                                            type="button"
                                            data-testid={`plantilla-${p.id}`}
                                            onClick={() => setPlantilla(p.id)}
                                            disabled={enviando}
                                            title={p.descripcion}
                                            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
                                                plantilla === p.id
                                                    ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/40'
                                                    : 'text-zinc-300 hover:bg-zinc-800'
                                            } disabled:opacity-50`}
                                        >
                                            {p.label}
                                        </button>
                                    ))}
                                </div>
                                {/* Por qué esta plantilla: la eligió el backend con los datos
                                    del alumno (y si no hay situación, lo dice). */}
                                {sugerencia && (
                                    <p className="text-xs mt-2" data-testid="modal-correo-sugerencia">
                                        {sugerencia.plantilla ? (
                                            <>
                                                <span className="text-zinc-500">Sugerida por el sistema:</span>{' '}
                                                <span className="text-orange-300 font-medium">
                                                    {sugerencia.label}
                                                </span>
                                                <span className="text-zinc-500"> · {sugerencia.motivo}</span>
                                            </>
                                        ) : (
                                            <>
                                                <span className="text-zinc-500">Hoy no le corresponde ninguna plantilla:</span>{' '}
                                                <span className="text-zinc-300">{sugerencia.motivo}</span>
                                            </>
                                        )}
                                    </p>
                                )}
                                {seleccionada && (
                                    <p className="text-xs text-zinc-500 mt-2">
                                        {seleccionada.descripcion} <em>{seleccionada.requiere}</em>
                                    </p>
                                )}
                            </div>

                            {previewando && (
                                <div className="flex justify-center py-10">
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                                </div>
                            )}

                            {!previewando && preview && (
                                <>
                                    <div className="bg-zinc-800/60 rounded-lg p-3 text-sm">
                                        <p className="text-zinc-400">
                                            <span className="text-zinc-500">Para:</span>{' '}
                                            <span className="text-zinc-100 font-medium"
                                                data-testid="preview-destinatario">
                                                {preview.destinatario}
                                            </span>
                                        </p>
                                        <p className="text-zinc-400 mt-1">
                                            <span className="text-zinc-500">Asunto:</span>{' '}
                                            <span className="text-zinc-100 font-medium"
                                                data-testid="preview-asunto">
                                                {preview.asunto}
                                            </span>
                                        </p>
                                    </div>
                                    <iframe
                                        title="Vista previa del correo"
                                        srcDoc={preview.html}
                                        sandbox=""
                                        data-testid="preview-html"
                                        className="w-full h-72 bg-white rounded-lg border border-zinc-700"
                                    />
                                </>
                            )}

                            {resultado && (
                                <p className={`text-sm rounded p-3 border-l-4 ${
                                    resultado.estado === 'fallido'
                                        ? 'bg-red-500/10 border-red-500 text-red-300'
                                        : 'bg-emerald-500/10 border-emerald-500 text-emerald-300'
                                }`}
                                    data-testid="modal-correo-resultado">
                                    {ETIQUETA_ESTADO[resultado.estado] || resultado.estado}
                                    {resultado.detalle_error && ` · ${resultado.detalle_error}`}
                                </p>
                            )}
                        </>
                    )}
                </div>

                <div className="p-5 border-t border-zinc-800 flex justify-end gap-2">
                    <button onClick={onClose} data-testid="modal-correo-cancelar"
                        className="px-4 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700">
                        {yaEnviado ? 'Cerrar' : 'Cancelar'}
                    </button>
                    <button
                        onClick={enviar}
                        disabled={cargando || enviando || yaEnviado || !plantilla || !preview}
                        data-testid="modal-correo-enviar"
                        className="px-4 py-2 bg-orange-600 text-white rounded-lg text-sm font-bold hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {enviando ? 'Enviando...' : (yaEnviado ? 'Enviado' : 'Enviar correo')}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ModalEnviarCorreo;
