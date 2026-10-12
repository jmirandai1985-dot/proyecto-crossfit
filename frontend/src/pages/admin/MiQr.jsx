import React from 'react';
import Layout from '../../components/Layout';
import { useTenantMe } from '../../hooks/queries';

/**
 * "Mi QR" del panel admin: muestra el QR fijo del box (check-in de alumnos)
 * y permite descargarlo/imprimirlo.
 *
 * El QR apunta a /asistencia/qr/{public_id} usando el ORIGEN actual del
 * navegador (así funciona tanto en localhost como accediendo por la IP de
 * la PC desde un celular en la misma red).
 */
const MiQr = () => {
    // Bloque 3 (parte A): `GET /tenants/me` (nombre, subdominio y public_id del box) sale
    // de la caché compartida. Es el ÚNICO consumidor de este endpoint en el front, así que
    // esta pantalla no duplica ninguna llamada.
    const { data, isPending: loading, error: errorQuery } = useTenantMe();
    const error = errorQuery
        ? (errorQuery.response?.data?.detail || 'No se pudo obtener el public_id del box')
        : '';

    const base = (typeof window !== 'undefined' && window.location.origin) || '';
    const qrHref = data
        ? `/api/v1/tenants/${data.public_id}/qr.svg?front=${encodeURIComponent(base)}`
        : '';
    const linkAlumno = data ? `${base}/asistencia/qr/${data.public_id}` : '';

    return (
        <Layout>
            <div className="space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-zinc-100">Mi QR de Asistencia</h1>
                    <p className="text-zinc-400 mt-1">
                        QR fijo del box: el alumno lo escanea y se marca solo si tiene una reserva en curso.
                    </p>
                </div>

                {loading ? (
                    <div className="flex items-center justify-center h-40">
                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
                    </div>
                ) : error ? (
                    <div className="bg-red-500/10 border-l-4 border-red-500 rounded-lg p-4 text-sm text-red-300">{error}</div>
                ) : data ? (
                    <div className="max-w-md">
                        <div className="bg-white rounded-xl p-6 flex flex-col items-center">
                            <img
                                src={qrHref}
                                alt={`QR de ${data.nombre}`}
                                className="w-64 h-64"
                            />
                            <p className="text-sm text-zinc-500 mt-3 break-all text-center">
                                {data.nombre} — {linkAlumno}
                            </p>
                        </div>

                        <div className="mt-4 flex flex-col gap-3">
                            <a
                                href={qrHref}
                                download={`qr-${data.subdomain || data.public_id}.svg`}
                                className="px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-bold text-center"
                            >
                                📥 Descargar QR (SVG)
                            </a>
                            <p className="text-xs text-zinc-500 text-center">
                                Imprimilo y pegalo en la recepción del box. El QR no es secreto: la
                                seguridad del check-in la da el login del alumno.
                            </p>
                        </div>
                    </div>
                ) : null}
            </div>
        </Layout>
    );
};

export default MiQr;
