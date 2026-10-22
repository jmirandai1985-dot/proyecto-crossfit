/**
 * useDocumentoAutenticado — vista previa y descarga de documentos PRIVADOS.
 *
 * POR QUÉ EXISTE: los comprobantes de pago (voucher de un plan, certificado de
 * estudiante, comprobante de un pedido del Bazar) NO se pueden abrir por su URL
 * pública: /static/uploads/... lo sirve StaticFiles SIN token. El panel los pide
 * CON el token (responseType: 'blob') al endpoint autenticado y muestra el blob.
 *
 * Esta lógica (pedir el blob + object URL + revoke + detalle del error + forzar
 * la descarga con el nombre del Content-Disposition) estaba duplicada en el
 * Dashboard y en Pendientes; acá vive una sola vez.
 *
 * EL PLAZO NO ES OPCIONAL (bug de PROD: "Revisar comprobante" colgado): acá se
 * pedía el blob con `api.get(...)` a secas y el cliente axios NO tiene timeout, así
 * que una petición sin desenlace dejaba `loading` en `true` PARA SIEMPRE: la hoja
 * mostraba "Cargando el comprobante…" sin error y sin forma de reintentar, y el
 * admin no podía revisar el pago del alumno. Es el MISMO caso que ya se corrigió en
 * el aviso de retiro (utils/avisoRetiro.js): por eso el mensaje del reloj es el
 * MISMO (`MSG_TIMEOUT`) y la detección de "sin desenlace" también (`esTimeout`).
 * Ahora la petición corre contra un reloj de `PREVIEW_TIMEOUT_MS`: al vencer se
 * aborta de verdad (AbortController), `loading` SIEMPRE termina en `false` y la
 * pantalla decide cómo mostrar el motivo + su botón Reintentar (`reintentar()`).
 *
 * Uso:
 *   const { preview, descargando, descargar, reintentar } = useDocumentoAutenticado({
 *       previewUrl: id ? `/api/v1/solicitudes/${id}/voucher?inline=1` : '',
 *       nombreFallback: `voucher_${id}`,
 *   });
 *   // descargar() devuelve { ok: true, nombre } o { ok: false, error }:
 *   // cada pantalla decide su propio mensaje (acá no se pinta nada).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';
import { AVISO_TIMEOUT_MS, MSG_TIMEOUT, esTimeout } from '../utils/avisoRetiro';
// La descarga (axios con token -> blob -> URL objeto -> revoke) vive en un
// helper sin DOM para poder probarla aislada; acá sólo se maneja el estado.
import {
    descargarDocumentoAutenticado,
    detalleDeErrorBlob,
} from '../utils/descargaAutenticada';

// Se reexporta para no romper imports existentes del hook.
export { detalleDeErrorBlob };

// Estado inicial de la vista previa (también lo usa el reset al cerrar el modal).
export const PREVIEW_INICIAL = { loading: false, blobUrl: '', error: '', mime: '' };

/** Plazo máximo de la vista previa (el MISMO reloj que el aviso de retiro). */
export const PREVIEW_TIMEOUT_MS = AVISO_TIMEOUT_MS;

export function useDocumentoAutenticado({
    previewUrl = '',
    downloadUrl = '',
    nombreFallback = 'documento',
    timeoutMs = PREVIEW_TIMEOUT_MS,
} = {}) {
    const [preview, setPreview] = useState(PREVIEW_INICIAL);
    const [descargando, setDescargando] = useState(false);
    // `reintento` es la palanca de Reintentar: cambiarla vuelve a correr el efecto.
    const [reintento, setReintento] = useState(0);
    // El object URL vive en un ref para poder revocarlo al cambiar de documento
    // o al desmontar (si no, cada documento nuevo deja el blob anterior vivo).
    const objectUrlRef = useRef('');

    // ── Vista previa (blob autenticado, SIEMPRE con plazo) ───────────────────
    useEffect(() => {
        const descartar = () => {
            if (objectUrlRef.current) {
                URL.revokeObjectURL(objectUrlRef.current);
                objectUrlRef.current = '';
            }
        };
        descartar();
        setPreview(PREVIEW_INICIAL);
        if (!previewUrl) return undefined;

        let cancelado = false;
        // El reloj no sólo avisa: CORTA la conexión (si no, el request sigue vivo).
        const control = new AbortController();
        let reloj;
        const expiro = new Promise((_, rechazar) => {
            reloj = setTimeout(() => {
                const err = new Error('timeout');
                err.timeout = true;
                control.abort();
                rechazar(err);
            }, timeoutMs);
        });

        (async () => {
            setPreview({ ...PREVIEW_INICIAL, loading: true });
            try {
                const res = await Promise.race([
                    api.get(previewUrl, { responseType: 'blob', signal: control.signal }),
                    expiro,
                ]);
                if (cancelado) return;
                objectUrlRef.current = URL.createObjectURL(res.data);
                setPreview({
                    loading: false, blobUrl: objectUrlRef.current, error: '',
                    mime: res.data.type || '',
                });
            } catch (err) {
                if (cancelado) return;
                setPreview({
                    loading: false, blobUrl: '', mime: '',
                    error: esTimeout(err) ? MSG_TIMEOUT : await detalleDeErrorBlob(err),
                });
            } finally {
                clearTimeout(reloj);
            }
        })();

        return () => {
            cancelado = true;
            clearTimeout(reloj);
            control.abort();
            descartar();
        };
    }, [previewUrl, reintento, timeoutMs]);

    /** Reintentar la vista previa (el GET no tiene efectos: repetirlo es seguro). */
    const reintentar = useCallback(() => setReintento((n) => n + 1), []);

    // ── Descarga forzada (Content-Disposition: attachment) ───────────────────
    // La dispara el usuario con su botón, que ya muestra "Descargando…": NO lleva
    // reloj a propósito (un voucher de 5 MB en datos móviles es legítimamente lento
    // y abortarlo sería peor que esperar). El helper pide el archivo con axios
    // (token) y revoca la URL objeto; acá sólo se maneja `descargando`.
    const descargar = useCallback(async (urlSobreescrita) => {
        const url = urlSobreescrita || downloadUrl;
        if (!url) return { ok: false, error: 'Sin documento para descargar' };
        setDescargando(true);
        try {
            return await descargarDocumentoAutenticado({
                cliente: api, url, nombreFallback,
            });
        } finally {
            setDescargando(false);
        }
    }, [downloadUrl, nombreFallback]);

    return { preview, descargando, descargar, reintentar };
}

export default useDocumentoAutenticado;
