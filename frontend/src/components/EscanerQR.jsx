import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Camera, X } from 'lucide-react';

/**
 * Lector de QR con la CÁMARA del dispositivo (sin librerías externas).
 *
 * POR QUÉ: el botón "Escanear QR" del alumno antes llevaba a una pantalla
 * intermedia (`/asistencia/qr/:publicId`, que ya conocía el `public_id` del box)
 * y sólo registraba la asistencia; NO abría la cámara. Ahora, al montarse este
 * componente, se pide la cámara DE INMEDIATO (`getUserMedia` dispara el permiso
 * ahí mismo) y se lee el QR con la API nativa `BarcodeDetector`. Al leerlo, se
 * extrae el `public_id` y se sigue al check-in existente.
 *
 * Si el navegador no soporta `BarcodeDetector`, la cámara igual se abre y se
 * ofrece un botón de respaldo (`publicIdFallback`). Si falta el permiso, se
 * explica y se ofrece Reintentar (vuelve a pedir el permiso).
 */

// Extrae el public_id del contenido del QR (URL .../asistencia/qr/<id> o id puro).
export const extraerPublicId = (texto) => {
    if (!texto) return null;
    const s = String(texto).trim();
    const m = s.match(/asistencia\/qr\/([A-Za-z0-9_-]+)/i);
    if (m) return m[1];
    if (/^[A-Za-z0-9_-]{6,64}$/.test(s)) return s;
    return null;
};

const EscanerQR = ({ onCerrar, publicIdFallback = null }) => {
    const navigate = useNavigate();
    const videoRef = useRef(null);
    const streamRef = useRef(null);
    const timerRef = useRef(null);
    const detectorRef = useRef(null);
    const cerradoRef = useRef(false);
    // iniciando | activo | denegado | sin_camara | error
    const [estado, setEstado] = useState('iniciando');
    const [soporte, setSoporte] = useState(true);   // ¿hay BarcodeDetector?
    const [mensaje, setMensaje] = useState('');

    const detener = useCallback(() => {
        cerradoRef.current = true;
        if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
        const s = streamRef.current;
        if (s) { s.getTracks().forEach((t) => t.stop()); streamRef.current = null; }
    }, []);

    const cerrar = useCallback(() => { detener(); onCerrar?.(); }, [detener, onCerrar]);

    const irA = useCallback((publicId) => {
        detener();
        onCerrar?.();
        navigate(`/asistencia/qr/${publicId}`);
    }, [detener, navigate, onCerrar]);

    // Bucle de detección (cada ~250 ms para no saturar).
    const escanear = useCallback(async () => {
        const det = detectorRef.current;
        const video = videoRef.current;
        if (!det || !video || cerradoRef.current) return;
        try {
            const codes = await det.detect(video);
            if (cerradoRef.current) return;
            const raw = codes && codes.length ? codes[0].rawValue : '';
            if (raw) {
                const pid = extraerPublicId(raw);
                if (pid) { irA(pid); return; }
                setMensaje('Ese código no es el QR del box. Apunta al QR oficial.');
            }
        } catch { /* frame aún no listo */ }
        if (!cerradoRef.current) timerRef.current = setTimeout(escanear, 250);
    }, [irA]);

    const iniciar = useCallback(async () => {
        cerradoRef.current = false;
        setMensaje('');
        setEstado('iniciando');
        setSoporte(true);
        if (!navigator.mediaDevices?.getUserMedia) {
            setEstado('error');
            setMensaje('Este navegador no permite abrir la cámara.');
            return;
        }
        try {
            // 1) Pedir la cámara DE INMEDIATO (aquí se dispara el permiso).
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: 'environment' } },
                audio: false,
            });
            streamRef.current = stream;
            if (videoRef.current) {
                videoRef.current.srcObject = stream;
                try { await videoRef.current.play(); } catch { /* autoplay */ }
            }
            setEstado('activo');
            // 2) Lectura del QR: API nativa. Si no está, se avisa (la cámara queda).
            if ('BarcodeDetector' in window) {
                try {
                    detectorRef.current = new window.BarcodeDetector({ formats: ['qr_code'] });
                    timerRef.current = setTimeout(escanear, 250);
                } catch { setSoporte(false); }
            } else {
                setSoporte(false);
            }
        } catch (e) {
            if (e?.name === 'NotAllowedError' || e?.name === 'SecurityError') {
                setEstado('denegado');
                setMensaje('Necesitamos permiso para la cámara. Actívalo en el navegador y vuelve a intentar.');
            } else if (e?.name === 'NotFoundError' || e?.name === 'OverconstrainedError') {
                setEstado('sin_camara');
                setMensaje('No encontramos una cámara en este dispositivo.');
            } else {
                setEstado('error');
                setMensaje('No pudimos abrir la cámara.');
            }
        }
    }, [escanear]);

    useEffect(() => {
        iniciar();
        return () => detener();
        // Sólo al montar/desmontar el overlay.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const reintentar = (estado === 'denegado' || estado === 'error' || estado === 'sin_camara');

    return (
        <div className="fixed inset-0 z-[60] flex flex-col bg-black/95"
            role="dialog" aria-label="Escanear QR" data-testid="escaner-qr">
            <div className="flex items-center justify-between px-4 py-3 text-white"
                style={{ paddingTop: 'env(safe-area-inset-top)' }}>
                <h2 className="text-lg font-bold">Escanear QR</h2>
                <button type="button" onClick={cerrar} aria-label="Cerrar"
                    className="inline-flex items-center justify-center min-h-11 min-w-11 rounded-lg hover:bg-white/10">
                    <X size={24} />
                </button>
            </div>

            <div className="relative flex-1 overflow-hidden">
                <video ref={videoRef} className="h-full w-full object-cover"
                    autoPlay playsInline muted />

                {/* Marco guía (sólo con cámara activa) */}
                {estado === 'activo' && (
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                        <div className="h-64 w-64 max-w-[70vw] rounded-2xl border-4 border-white/80"
                            style={{ boxShadow: '0 0 0 2000px rgba(0,0,0,0.45)' }} />
                    </div>
                )}

                {/* Estados sin cámara: mensaje + Reintentar */}
                {estado !== 'activo' && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center text-white">
                        {estado === 'iniciando' ? (
                            <>
                                <Camera size={40} className="opacity-80" />
                                <p>Abriendo la cámara…</p>
                            </>
                        ) : (
                            <>
                                <Camera size={40} className="text-amber-400" />
                                <p className="font-semibold text-red-300">{mensaje}</p>
                                {reintentar && (
                                    <button type="button" onClick={iniciar}
                                        className="mt-2 inline-flex items-center gap-2 px-5 py-3 rounded-lg bg-orange-500 text-white font-bold hover:bg-orange-600">
                                        <Camera size={18} /> Reintentar
                                    </button>
                                )}
                            </>
                        )}
                    </div>
                )}

                {/* Cámara activa: instrucción + respaldo sin BarcodeDetector */}
                {estado === 'activo' && soporte && (
                    <p className="absolute inset-x-0 bottom-4 text-center text-sm text-white/90">
                        {mensaje || 'Apunta la cámara al QR del box'}
                    </p>
                )}
                {estado === 'activo' && !soporte && (
                    <div className="absolute inset-x-0 bottom-0 bg-black/70 p-4 text-center text-sm text-white">
                        Tu navegador no permite leer el QR automáticamente.
                        {mensaje && <span className="mt-1 block text-amber-300">{mensaje}</span>}
                        {publicIdFallback && (
                            <button type="button" onClick={() => irA(publicIdFallback)}
                                className="mt-3 inline-flex items-center gap-2 px-5 py-3 rounded-lg bg-orange-500 text-white font-bold hover:bg-orange-600">
                                Marcar asistencia igual
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default EscanerQR;

