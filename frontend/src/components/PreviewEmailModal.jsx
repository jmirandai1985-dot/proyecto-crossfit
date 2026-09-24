/**
 * Preview del correo de inactividad ANTES de enviarlo (P1).
 *
 * El asunto y el cuerpo los renderiza el BACKEND (`render_email_fidelizacion`),
 * que es la MISMA función que usa el envío real: lo que se ve acá es
 * exactamente lo que se manda (sin riesgo de que el preview "derive").
 * Se pinta en un <iframe sandbox=""> para tener fidelidad total del HTML del
 * correo sin ejecutar nada.
 */
import React, { useEffect, useState } from 'react';
import api from '../services/api';

const PreviewEmailModal = ({ alumnoId, coachId, onClose, onConfirmar, enviando }) => {
    const [preview, setPreview] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const cargar = async () => {
        setLoading(true);
        setError('');
        try {
            const r = await api.get(`/api/v1/fidelizacion/coach/${coachId}/contactar/${alumnoId}/preview`);
            setPreview(r.data);
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo generar la vista previa del correo.');
            setPreview(null);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (alumnoId) cargar();
    }, [alumnoId, coachId]);

    if (!alumnoId) return null;

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" data-testid="preview-email-modal">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
                <div className="flex items-start justify-between p-5 border-b border-zinc-800">
                    <div>
                        <h3 className="text-lg font-bold text-zinc-100">Vista previa del correo</h3>
                        <p className="text-sm text-zinc-400">
                            Revisá el mensaje antes de enviarlo. Es exactamente lo que va a recibir el alumno.
                        </p>
                    </div>
                    <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100 text-xl leading-none" aria-label="Cerrar">×</button>
                </div>

                <div className="p-5 space-y-3 overflow-y-auto">
                    {loading && (
                        <div className="flex justify-center py-10">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                        </div>
                    )}

                    {!loading && error && (
                        <div className="bg-red-500/10 border-l-4 border-red-500 rounded p-3 text-sm text-red-300">
                            <p className="font-medium">⚠️ {error}</p>
                            <button onClick={cargar} className="mt-2 px-3 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">
                                Reintentar
                            </button>
                        </div>
                    )}

                    {!loading && !error && preview && (
                        <>
                            <div className="bg-zinc-800/60 rounded-lg p-3 text-sm">
                                <p className="text-zinc-400">
                                    <span className="text-zinc-500">Para:</span>{' '}
                                    <span className="text-zinc-100 font-medium" data-testid="preview-destinatario">
                                        {preview.destinatario}
                                    </span>
                                </p>
                                <p className="text-zinc-400 mt-1">
                                    <span className="text-zinc-500">Asunto:</span>{' '}
                                    <span className="text-zinc-100 font-medium" data-testid="preview-asunto">
                                        {preview.asunto}
                                    </span>
                                </p>
                                <p className="text-xs text-zinc-500 mt-1">
                                    Inactividad detectada: {preview.dias_inactividad} días
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
                </div>

                <div className="p-5 border-t border-zinc-800 flex justify-end gap-2">
                    <button
                        onClick={onClose}
                        data-testid="preview-cancelar"
                        className="px-4 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700"
                    >
                        Cancelar
                    </button>
                    <button
                        onClick={() => onConfirmar(preview)}
                        disabled={loading || !!error || enviando}
                        data-testid="preview-confirmar"
                        className="px-4 py-2 bg-orange-600 text-white rounded-lg text-sm font-medium hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {enviando ? 'Enviando...' : 'Confirmar envío'}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default PreviewEmailModal;
