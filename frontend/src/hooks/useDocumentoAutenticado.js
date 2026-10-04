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
 * Uso:
 *   const { preview, descargando, descargar } = useDocumentoAutenticado({
 *       previewUrl: id ? `/api/v1/solicitudes/${id}/voucher?inline=1` : '',
 *       nombreFallback: `voucher_${id}`,
 *   });
 *   // descargar() devuelve { ok: true, nombre } o { ok: false, error }:
 *   // cada pantalla decide su propio mensaje (acá no se pinta nada).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';

// Estado inicial de la vista previa (también lo usa el reset al cerrar el modal).
export const PREVIEW_INICIAL = { loading: false, blobUrl: '', error: '', mime: '' };

/**
 * Extrae el mensaje de error de una respuesta blob: con responseType 'blob'
 * axios NO parsea el JSON del error, llega como Blob.
 */
export const detalleDeErrorBlob = async (err) => {
    const d = err?.response?.data;
    if (d instanceof Blob) {
        try {
            return JSON.parse(await d.text())?.detail || 'Error al procesar el archivo';
        } catch {
            // el cuerpo no era JSON
        }
    }
    return d?.detail || err?.message || 'Error al procesar el archivo';
};

export function useDocumentoAutenticado({
    previewUrl = '',
    downloadUrl = '',
    nombreFallback = 'documento',
} = {}) {
    const [preview, setPreview] = useState(PREVIEW_INICIAL);
    const [descargando, setDescargando] = useState(false);
    // El object URL vive en un ref para poder revocarlo al cambiar de documento
    // o al desmontar (si no, cada documento nuevo deja el blob anterior vivo).
    const objectUrlRef = useRef('');

    // ── Vista previa (blob autenticado) ──────────────────────────────────────
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
        (async () => {
            setPreview({ ...PREVIEW_INICIAL, loading: true });
            try {
                const res = await api.get(previewUrl, { responseType: 'blob' });
                if (cancelado) return;
                objectUrlRef.current = URL.createObjectURL(res.data);
                setPreview({
                    loading: false, blobUrl: objectUrlRef.current, error: '',
                    mime: res.data.type || '',
                });
            } catch (err) {
                if (cancelado) return;
                setPreview({
                    loading: false, blobUrl: '', error: await detalleDeErrorBlob(err), mime: '',
                });
            }
        })();

        return () => {
            cancelado = true;
            descartar();
        };
    }, [previewUrl]);

    // ── Descarga forzada (Content-Disposition: attachment) ───────────────────
    const descargar = useCallback(async (urlSobreescrita) => {
        const url = urlSobreescrita || downloadUrl;
        if (!url) return { ok: false, error: 'Sin documento para descargar' };
        setDescargando(true);
        try {
            const res = await api.get(url, { responseType: 'blob' });
            const cd = res.headers?.['content-disposition'] || '';
            const coincide = cd.match(/filename="?([^";]+)"?/i);
            const nombre = coincide ? coincide[1] : nombreFallback;
            const objectUrl = URL.createObjectURL(res.data);
            const a = document.createElement('a');
            a.href = objectUrl;
            a.download = nombre;
            document.body.appendChild(a);
            a.click();
            a.remove();
            // El revoke inmediato puede abortar la descarga en algunos navegadores.
            setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
            return { ok: true, nombre };
        } catch (err) {
            return { ok: false, error: await detalleDeErrorBlob(err) };
        } finally {
            setDescargando(false);
        }
    }, [downloadUrl, nombreFallback]);

    return { preview, descargando, descargar };
}

export default useDocumentoAutenticado;
