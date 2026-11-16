import React, { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useCancelarPago, usePago } from '../../hooks/queries';

/**
 * Retorno de Mercado Pago Checkout Pro.
 *
 * ⚠️ Esta pantalla NO activa nada: el plan o el pedido los activa el WEBHOOK.
 * Acá sólo se le pregunta al backend (`GET /pagos/{id}`) hasta que el estado
 * esté resuelto, porque el webhook puede tardar de 1 a 30 segundos. Si el alumno
 * cierra el navegador sin llegar acá, el pago se aplica igual.
 *
 * Mientras el pago siga ABIERTO (`iniciado`/`pendiente`/`en_proceso`) se ofrece
 * "Cancelar": el caso del alumno que vuelve sin haber metido la tarjeta, donde
 * Mercado Pago no generó ningún pago que rechazar (`POST /pagos/{id}/cancelar`
 * cierra la solicitud oculta y libera el guard de intentos en curso). El que NO
 * vuelve lo cierra la expiración automática a los 30 min.
 *
 * La URL es `/alumno/pago/resultado/:pagoId`: Mercado Pago agrega sus propios
 * query params (`collection_id`, `status`, ...) y no se leen a propósito —
 * cualquiera puede visitar esta URL a mano.
 */
const MENSAJES = {
    iniciado: {
        icono: '💳',
        titulo: 'Pago no iniciado',
        detalle: 'Todavía no recibimos ningún aviso de Mercado Pago. Puedes cancelar este intento y volver a intentarlo.',
    },
    aprobado: {
        icono: '✅',
        titulo: '¡Pago aprobado!',
        detalle: 'Mercado Pago confirmó el cobro. Tu compra ya quedó aplicada.',
    },
    pendiente: {
        icono: '⏳',
        titulo: 'Pago pendiente',
        detalle: 'Mercado Pago todavía está procesando el pago. Te avisaremos cuando se confirme.',
    },
    en_proceso: {
        icono: '⏳',
        titulo: 'Pago en revisión',
        detalle: 'Mercado Pago está revisando el pago. Suele resolverse en minutos.',
    },
    rechazado: {
        icono: '❌',
        titulo: 'El pago no se completó',
        detalle: 'Mercado Pago rechazó el cobro. Puedes intentarlo otra vez con otro medio.',
    },
    cancelado: {
        icono: '❌',
        titulo: 'Pago cancelado',
        detalle: 'El pago se canceló y no se cobró nada.',
    },
    reembolsado: {
        icono: '↩️',
        titulo: 'Pago reembolsado',
        detalle: 'Mercado Pago devolvió el dinero. Si tienes dudas, habla con el box.',
    },
    expirado: {
        icono: '⌛',
        titulo: 'El pago venció',
        detalle: 'Pasó demasiado tiempo sin completarse. Puedes volver a intentarlo.',
    },
};


const PagoResultado = () => {
    const { pagoId } = useParams();
    const navigate = useNavigate();
    // 3 s: el webhook tarda segundos. El hook corta el polling cuando el pago
    // queda resuelto (ver `usePago`).
    const pagoQ = usePago(pagoId, { refetchIntervalMs: 3000 });
    const pago = pagoQ.data;
    const cancelarM = useCancelarPago(pagoId);
    const [errorCancelar, setErrorCancelar] = useState('');

    const volverA = pago?.concepto === 'bazar'
        ? '/alumno/bazar' : '/alumno/solicitar-plan';
    const verDestino = pago?.concepto === 'bazar'
        ? '/alumno/mis-pedidos' : '/alumno/dashboard';
    const info = pago ? MENSAJES[pago.estado] : null;
    // Aprobado pero el negocio todavía no se aplicó: el webhook está en camino.
    const activando = pago?.estado === 'aprobado' && !pago.aplicado;
    // Sólo se puede cancelar lo que sigue abierto: `iniciado` (el alumno volvió
    // antes del primer webhook), `pendiente` o `en_proceso`. Si el webhook lo
    // aprobó mientras el alumno volvía, el backend responde 409 y NO deshace el
    // cobro.
    const cancelable = Boolean(
        pago && ['iniciado', 'pendiente', 'en_proceso'].includes(pago.estado));

    const handleCancelar = async () => {
        setErrorCancelar('');
        try {
            await cancelarM.mutateAsync();
            // El backend ya cerró el pago y la solicitud: al volver a planes el
            // guard "ya tienes una solicitud pendiente" no bloquea otra compra.
            navigate(volverA);
        } catch (err) {
            setErrorCancelar(
                err.response?.data?.detail
                || 'No pudimos cancelar el pago. Intenta de nuevo.');
        }
    };

    return (
        <Layout>
            <div className="max-w-lg mx-auto py-10 px-4">
                <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-8 text-center">
                    {pagoQ.isPending && (
                        <>
                            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4" />
                            <p className="text-gray-600">Estamos confirmando tu pago...</p>
                        </>
                    )}

                    {pagoQ.isError && (
                        <>
                            <div className="text-5xl mb-3">⚠️</div>
                            <h1 className="text-xl font-bold text-gray-800 mb-2">
                                No pudimos consultar el pago
                            </h1>
                            <p className="text-sm text-gray-600 mb-6">
                                Si Mercado Pago te cobró, el pago se aplica igual (lo confirma
                                el webhook). Revisa tu plan o tus pedidos en unos minutos.
                            </p>
                        </>
                    )}

                    {pago && (
                        <>
                            <div className="text-6xl mb-4">{info?.icono || '💳'}</div>
                            <h1 className="text-2xl font-bold text-gray-800 mb-2">
                                {info?.titulo || 'Estado del pago'}
                            </h1>
                            <p className="text-sm text-gray-600 mb-1">
                                {info?.detalle || ''}
                            </p>
                            <p className="text-xs text-gray-400 mb-6">
                                Monto: ${Number(pago.monto_clp || 0).toLocaleString('es-CL')}
                                {' · '}Pago #{pago.id}
                            </p>

                            {activando && (
                                <p className="text-sm text-blue-600 bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4"
                                    data-testid="pago-activando">
                                    Estamos activando tu compra. Esto puede tardar unos segundos...
                                </p>
                            )}
                        </>
                    )}

                    <div className="flex flex-col gap-2">
                        {pago?.aplicado && (
                            <Link to={verDestino}
                                className="px-6 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors">
                                Ver mi {pago.concepto === 'bazar' ? 'pedido' : 'plan'}
                            </Link>
                        )}
                        {cancelable && (
                            <button type="button" onClick={handleCancelar}
                                disabled={cancelarM.isPending}
                                data-testid="cancelar-pago"
                                className="px-6 py-3 bg-red-600 text-white rounded-xl hover:bg-red-700 disabled:opacity-60 font-bold text-sm transition-colors">
                                {cancelarM.isPending ? 'Cancelando...' : 'Cancelar pago'}
                            </button>
                        )}
                        {errorCancelar && (
                            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3"
                                data-testid="cancelar-pago-error">
                                {errorCancelar}
                            </p>
                        )}
                        {pago && ['rechazado', 'cancelado', 'expirado'].includes(pago.estado) && (
                            <Link to={volverA}
                                className="px-6 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 font-bold text-sm transition-colors">
                                Intentar de nuevo
                            </Link>
                        )}
                        <Link to="/alumno/dashboard"
                            className="px-6 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors">
                            Volver al inicio
                        </Link>
                    </div>
                </div>
            </div>
        </Layout>
    );
};

export default PagoResultado;
