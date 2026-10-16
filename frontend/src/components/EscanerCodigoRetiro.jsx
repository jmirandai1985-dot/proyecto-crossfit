import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, Keyboard, X } from 'lucide-react';

/**
 * Lector del CÓDIGO DE RETIRO con la CÁMARA del dispositivo (sin librerías externas).
 *
 * POR QUÉ EXISTE: el mesón del Bazar cerraba la entrega escribiendo el código a mano
 * (`UB-4827`). El alumno ya lo muestra como QR desde `MisPedidos` —el backend lo genera con
 * `segno` en `GET /pedidos/{id}/qr.svg`, y su contenido es SÓLO el código, no una URL—, así
 * que acá se lee ESE QR con la API nativa `BarcodeDetector` y el texto vuelve por `onLeer`.
 *
 * DIFERENCIA CON `EscanerQR` (la asistencia del alumno): aquel extrae un `public_id` y
 * NAVEGA a `/asistencia/qr/{id}`. Este no navega a ninguna parte: entrega el texto leído y el
 * mesón sigue con el MISMO flujo que si lo hubiera escrito (el `ModalEntregarPedido`
 * completa su input y dispara la entrega). Por eso son dos componentes y no uno con props.
 *
 * Si el navegador no soporta `BarcodeDetector`, la cámara igual se abre y se ofrece volver al
 * TECLADO (el input manual nunca se saca). Si falta el permiso, se explica y se ofrece
 * Reintentar (vuelve a pedir la cámara).
 */
const EscanerCodigoRetiro = ({ onLeer, onCerrar }) => {
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

    // Bucle de detección (~250 ms). Al primer texto legible se corta y se devuelve.
    const escanear = useCallback(async () => {
        const det = detectorRef.current;
        const video = videoRef.current;
        if (!det || !video || cerradoRef.current) return;
        try {
            const codes = await det.detect(video);
            if (cerradoRef.current) return;
            const raw = codes && codes.length ? codes[0].rawValue : '';
            if (raw && String(raw).trim()) {
                detener();
                onLeer?.(String(raw).trim());
                return;
            }
        } catch { /* frame aún no listo */ }
        if (!cerradoRef.current) timerRef.current = setTimeout(escanear, 250);
    }, [detener, onLeer]);

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
            // 1) Permiso + cámara trasera de inmediato.
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: 'environment' } },
                audio: false,
            });
            streamRef.current = stream;
            if (videoRef.current) {
                videoRef.current.srcObject = stream;
                await videoRef.current.play().catch(() => {});
            }
            // 2) Con la cámara viva: ¿hay detector nativo?
            if ('BarcodeDetector' in window) {
                // Algunos navegadores exigen el constructor sin filtro de formatos: si el
                // filtro no es aceptado, se cae al detector genérico.
                try {
                    detectorRef.current = new window.BarcodeDetector({ formats: ['qr_code'] });
                } catch {
                    detectorRef.current = new window.BarcodeDetector();
                }
                setEstado('activo');
                escanear();
            } else {
                setSoporte(false);
                setEstado('activo');   // la cámara se ve igual; se ofrece el teclado
            }
        } catch (e) {
            const nombre = e?.name || '';
            if (nombre === 'NotAllowedError' || nombre === 'SecurityError') {
                setEstado('denegado');
                setMensaje('Falta el permiso de cámara. Habilítalo y reintenta, o escribe el código.');
            } else if (nombre === 'NotFoundError' || nombre === 'OverconstrainedError') {
                setEstado('sin_camara');
                setMensaje('No encontré una cámara en este dispositivo. Escribe el código.');
            } else {
                setEstado('error');
                setMensaje('No se pudo abrir la cámara. Escribe el código a mano.');
            }
        }
    }, [escanear]);

    useEffect(() => {
        iniciar();
        return () => detener();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const reintentar = (estado === 'denegado' || estado === 'error' || estado === 'sin_camara');

    return (
        <div className="fixed inset-0 z-[70] flex flex-col bg-black/95"
            role="dialog" aria-label="Escanear código de retiro" data-testid="escaner-codigo-retiro">
            <div className="flex items-center justify-between px-4 py-3 text-white"
                style={{ paddingTop: 'env(safe-area-inset-top)' }}>
                <h2 className="text-lg font-bold">Escanear código</h2>
                <button type="button" onClick={cerrar} aria-label="Cerrar"
                    className="inline-flex items-center justify-center min-h-11 min-w-11 rounded-lg hover:bg-white/10">
                    <X size={24} />
                </button>
            </div>

            <div className="relative flex-1 overflow-hidden">
                <video ref={videoRef} className="h-full w-full object-cover"
                    autoPlay playsInline muted />

                {estado === 'activo' && (
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                        <div className="h-64 w-64 max-w-[70vw] rounded-2xl border-4 border-white/80"
                            style={{ boxShadow: '0 0 0 2000px rgba(0,0,0,0.45)' }} />
                    </div>
                )}

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

                {estado === 'activo' && soporte && (
                    <p className="absolute inset-x-0 bottom-4 text-center text-sm text-white/90">
                        {mensaje || 'Apunta la cámara al QR del alumno (su código de retiro)'}
                    </p>
                )}
                {estado === 'activo' && !soporte && (
                    <div className="absolute inset-x-0 bottom-0 bg-black/70 p-4 text-center text-sm text-white">
                        Tu navegador no permite leer el QR automáticamente.
                        {mensaje && <span className="mt-1 block text-amber-300">{mensaje}</span>}
                    </div>
                )}
            </div>

            {/* El input manual NUNCA se saca: este botón vuelve al formulario. */}
            <div className="border-t border-white/10 p-4">
                <button type="button" onClick={cerrar}
                    data-testid="escaner-volver-teclado"
                    className="mx-auto flex items-center gap-2 rounded-xl border border-white/25 px-5 py-3 text-sm font-semibold text-white hover:bg-white/10">
                    <Keyboard size={18} /> Escribir el código a mano
                </button>
            </div>
        </div>
    );
};

export default EscanerCodigoRetiro;

