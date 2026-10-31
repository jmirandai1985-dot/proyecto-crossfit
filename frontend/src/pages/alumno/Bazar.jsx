import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import AvisoCarga from '../../components/AvisoCarga';
import BotonVolver from '../../components/BotonVolver';
// Fase 2 (Bloque 3): subir el comprobante es una mutación de la caché compartida (el
// MISMO hook que usa Solicitar plan), no un `api.post` a mano dentro de la pantalla.
import {
    useConfiguracionBancaria, useCrearPagoBazar, useCrearPedidoBazar,
    usePagoDisponible, useProductos, useSubirArchivoPrivado,
} from '../../hooks/queries';
import ImagenProducto from '../../components/ImagenProducto';
import GaleriaProducto from '../../components/GaleriaProducto';

const Bazar = () => {
    const { usuario_id, tenant_id } = useAuth();
    const [paso, setPaso] = useState(1); // 1=catálogo, 2=pago
    const [productoSeleccionado, setProductoSeleccionado] = useState(null);
    const [cantidad, setCantidad] = useState(1);
    const [archivoVoucher, setArchivoVoucher] = useState(null);
    const [mensaje, setMensaje] = useState({ type: '', text: '' });

    // Catálogo y datos de transferencia en la caché de React Query (Fase 2): el
    // catálogo comparte queryKey con el Inicio y Mis pedidos del alumno.
    const productosQ = useProductos({ activo: true });
    const configQ = useConfiguracionBancaria(tenant_id);
    const crearPedido = useCrearPedidoBazar();
    // Subir el comprobante es una ORDEN: devuelve la URL privada del archivo subido.
    const subirArchivo = useSubirArchivoPrivado();
    // "Ocupado" derivado de las dos mutaciones del envío (antes: un useState que había
    // que apagar en el `finally`).
    const subiendo = subirArchivo.isPending || crearPedido.isPending;
    // ─── Pago online (Mercado Pago Checkout Pro) ───────────────────────────
    // Convive con la transferencia. El botón sólo aparece si el backend tiene la
    // pasarela encendida; la tarjeta nunca pasa por la app (sólo `init_point`).
    const pagoDisponibleQ = usePagoDisponible();
    const pagoDisponible = Boolean(pagoDisponibleQ.data?.habilitado);
    const crearPagoOnline = useCrearPagoBazar();
    const [yendoAPagar, setYendoAPagar] = useState(false);
    const productos = productosQ.data || [];
    const configBancaria = configQ.data?.configurado ? configQ.data : null;
    const loading = productosQ.isLoading || configQ.isLoading;
    // P1: si falla la carga, se avisa con banner + Reintentar (antes quedaba
    // "El box aún no publicó productos" como si el catálogo estuviera vacío).
    const erroresCarga = [];
    if (productosQ.isError) erroresCarga.push('productos');
    if (configQ.isError) erroresCarga.push('datos de transferencia');
    const cargarTodo = () => { productosQ.refetch(); configQ.refetch(); };

    // ── Deep link desde la Tienda del Inicio: /alumno/bazar?producto=<id> ────────
    // Tocar la tarjeta de un producto tiene que llevar DIRECTO al paso de pago de ESE
    // producto (antes la tarjeta no hacía nada). Se aplica UNA vez por id: volver al
    // catálogo no reabre el paso 2. No exige datos bancarios para entrar: si faltan, el
    // paso 2 ya muestra el aviso y el botón de enviar queda deshabilitado.
    const [searchParams] = useSearchParams();
    const productoPedido = Number(searchParams.get('producto'));
    const deepLinkAplicado = useRef(null);
    useEffect(() => {
        if (!productoPedido || deepLinkAplicado.current === productoPedido) return;
        const elegido = productos.find((p) => p.id === productoPedido);
        if (!elegido) return;   // puede estar despublicado o fuera del catálogo
        deepLinkAplicado.current = productoPedido;
        if ((elegido.stock ?? 0) <= 0) {
            setMensaje({ type: 'error', text: `${elegido.nombre} está agotado.` });
            return;
        }
        setProductoSeleccionado(elegido);
        setCantidad(1);
        setPaso(2);
        setMensaje({ type: '', text: '' });
    }, [productoPedido, productos]);

    const handleComprar = (producto) => {
        // Sin datos bancarios no hay transferencia posible; con el pago online
        // habilitado el alumno puede comprar igual (no sube comprobante).
        if (!configBancaria && !pagoDisponible) return;
        setProductoSeleccionado(producto);
        setCantidad(1);
        setPaso(2);
        setMensaje({ type: '', text: '' });
    };

    const handleEnviarPedido = async () => {
        if (!configBancaria) {
            setMensaje({
                type: 'error',
                text: 'El box todavía no cargó los datos de transferencia: no se puede enviar el pedido.',
            });
            return;
        }
        if (!archivoVoucher) {
            setMensaje({ type: 'error', text: 'Debes seleccionar un comprobante de pago.' });
            return;
        }
        setMensaje({ type: '', text: '' });
        try {
            // El hook sube el archivo con `privado=1` (carpeta privada, la que corresponde
            // al comprobante de un pedido) y devuelve la URL que el pedido guarda.
            const voucherUrl = await subirArchivo.mutateAsync(archivoVoucher);

            await crearPedido.mutateAsync({
                tenant_id,
                alumno_id: usuario_id,
                producto_id: productoSeleccionado.id,
                cantidad,
                estado: 'pendiente',
                voucher_url: voucherUrl,
            });
            setMensaje({ type: 'success', text: 'Pedido realizado exitosamente. El admin lo revisará.' });
            setPaso(3);
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al procesar pedido.';
            setMensaje({ type: 'error', text: detalle });
        }
    };

    /**
     * Paga el pedido online (Checkout Pro). El pedido se crea en `pendiente` y
     * el stock se reserva igual que en la transferencia; Mercado Pago confirma
     * el cobro y el webhook lo pasa a `validado` (con código de retiro). Si el
     * pago no llega en 30 minutos, el pedido se rechaza y el stock vuelve.
     */
    const handlePagarOnline = async () => {
        if (!productoSeleccionado) return;
        setMensaje({ type: '', text: '' });
        setYendoAPagar(true);
        try {
            const pago = await crearPagoOnline.mutateAsync({
                producto_id: productoSeleccionado.id,
                cantidad,
            });
            window.location.href = pago.init_point;
        } catch (err) {
            setMensaje({
                type: 'error',
                text: err.response?.data?.detail
                    || 'No se pudo iniciar el pago online. Intenta nuevamente o usa transferencia.',
            });
            setYendoAPagar(false);
        }
    };

    if (loading) return (
        <Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>
    );

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">
                <div className="flex items-center gap-3">
                    <BotonVolver />
                    <span className="text-3xl">🛍️</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Bazar</h1>
                        <p className="text-sm text-gray-500">Productos disponibles</p>
                    </div>
                </div>

                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

                {/* P2/I3: sin datos de transferencia no se puede comprar (el pedido exige el
                    comprobante de la transferencia). Antes el Bazar escondía el bloque de datos
                    bancarios y dejaba llegar hasta "Enviar Pedido" sin destino al que transferir. */}
                {paso === 1 && !configBancaria && erroresCarga.length === 0 && (
                    <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800"
                        data-testid="bazar-sin-datos-bancarios">
                        ⚠️ El box <strong>todavía no cargó los datos de transferencia</strong>, así que
                        los pedidos quedan deshabilitados. Contacta al administrador.
                    </div>
                )}

                {paso === 1 && mensaje.text && (
                    <div className={`mb-4 rounded-xl border px-4 py-3 text-sm font-medium ${mensaje.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-red-50 border-red-200 text-red-700'}`}
                        role="alert">
                        {mensaje.type === 'success' ? '✅' : '❌'} {mensaje.text}
                    </div>
                )}

                {paso === 1 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {productos.length === 0 && erroresCarga.length === 0 ? (
                            <div className="col-span-full text-center py-12">
                                <p className="text-gray-400 text-lg">📦 El box aún no publicó productos</p>
                            </div>
                        ) : productos.map(p => (
                            <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md transition-all">
                                {/* Foto del producto si el box la subió; sin foto —o si la
                                    foto no carga— queda el ícono de siempre. */}
                                <ImagenProducto
                                    url={p.imagen_url}
                                    alt={p.nombre}
                                    className="w-full h-40 object-cover rounded-lg mb-3 border border-gray-100"
                                    respaldo={<span className="text-4xl block mb-3">🛍️</span>}
                                />
                                <h3 className="font-bold text-gray-800">{p.nombre}</h3>
                                {p.descripcion && <p className="text-xs text-gray-400 mt-1">{p.descripcion}</p>}
                                <p className="text-2xl font-bold text-emerald-600 mt-3">${(p.precio || 0).toLocaleString('es-CL')}</p>
                                <p className="text-xs text-gray-400 mt-1">Stock: {p.stock} unidades</p>
                                {p.stock > 0 ? (
                                    <button onClick={() => handleComprar(p)} disabled={!configBancaria}
                                        className="mt-4 w-full py-2.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                        Comprar
                                    </button>
                                ) : (
                                    <p className="mt-4 text-center text-sm text-red-500 font-medium">Agotado</p>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                {paso === 2 && productoSeleccionado && (
                    <div className="space-y-6 max-w-lg mx-auto">
                        <div className="bg-emerald-50 rounded-xl border border-emerald-200 overflow-hidden">
                            {/* Galería del producto: portada + miniaturas + visor con zoom,
                                flechas y swipe. Las tarjetas del catálogo siguen mostrando
                                sólo la portada (`imagen_url`). */}
                            <GaleriaProducto
                                imagenes={productoSeleccionado.imagenes}
                                urlPrincipal={productoSeleccionado.imagen_url}
                                nombre={productoSeleccionado.nombre}
                                className="bg-gray-100 p-2"
                            />
                            <div className="p-5 pt-3">
                                <p className="text-xs text-emerald-600 uppercase font-semibold">Producto seleccionado</p>
                                <h3 className="text-xl font-bold text-gray-800">{productoSeleccionado.nombre}</h3>
                                <p className="text-lg font-bold text-emerald-600">${(productoSeleccionado.precio * cantidad).toLocaleString('es-CL')}</p>
                            </div>
                        </div>

                        <div className="flex items-center gap-3 bg-white rounded-xl border p-4">
                            <label className="text-sm font-medium text-gray-700">Cantidad:</label>
                            <select value={cantidad} onChange={e => setCantidad(Number(e.target.value))}
                                className="px-3 py-2 border rounded-lg text-sm">
                                {[...Array(Math.min(productoSeleccionado.stock, 10)).keys()].map(i =>
                                    <option key={i + 1} value={i + 1}>{i + 1}</option>
                                )}
                            </select>
                            <span className="text-xs text-gray-400">Stock disponible: {productoSeleccionado.stock}</span>
                        </div>

                        {/* I3: el bloque va SIEMPRE, con el mismo fallback que SolicitarPlan.
                            Sin datos cargados, antes no se renderizaba nada y el alumno subía el
                            comprobante sin saber a qué cuenta transferir. */}
                        <div className="bg-blue-50 rounded-xl border border-blue-200 p-5">
                            <h4 className="font-bold text-blue-800 mb-3">🏦 Datos para Transferencia</h4>
                            {configBancaria ? (
                                <div className="bg-white rounded-lg p-3 border border-blue-100 space-y-1.5 text-sm">
                                    <p><span className="font-medium text-gray-600">Banco:</span> {configBancaria.banco}</p>
                                    <p><span className="font-medium text-gray-600">Tipo:</span> {configBancaria.tipo_cuenta}</p>
                                    <p><span className="font-medium text-gray-600">N° Cuenta:</span> <span className="font-bold text-blue-800">{configBancaria.numero_cuenta}</span></p>
                                    <p><span className="font-medium text-gray-600">RUT:</span> {configBancaria.rut}</p>
                                </div>
                            ) : (
                                <div className="text-sm text-blue-600 bg-white rounded-lg p-3 border border-blue-100"
                                    data-testid="bazar-datos-bancarios-faltantes">
                                    <p>⏳ El box aún no ha configurado sus datos de pago.</p>
                                    <p className="text-xs mt-1">Por favor contacta al administrador para obtener la información de transferencia.</p>
                                </div>
                            )}
                        </div>

                        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                            <h4 className="font-bold text-gray-800 mb-3">📎 Subir Comprobante de Pago</h4>
                            <div className="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center hover:border-emerald-400 transition-colors">
                                <input type="file" id="voucher-bazar" accept="image/*,application/pdf"
                                    onChange={e => setArchivoVoucher(e.target.files[0] || null)} className="hidden" />
                                <label htmlFor="voucher-bazar" className="cursor-pointer">
                                    <span className="text-4xl block mb-2">{archivoVoucher ? '📄' : '📤'}</span>
                                    <p className="text-sm text-gray-600">{archivoVoucher ? archivoVoucher.name : 'Haz clic para seleccionar'}</p>
                                </label>
                            </div>
                        </div>

                        {/* ─── PAGO ONLINE (Mercado Pago) ───
                            Alternativa a la transferencia: sin comprobante, el
                            pedido se valida solo cuando Mercado Pago confirma
                            el cobro. El stock se reserva igual al crear. */}
                        {pagoDisponible && (
                            <div className="bg-blue-50 rounded-xl border border-blue-200 p-5"
                                data-testid="bazar-pago-online">
                                <h4 className="font-bold text-blue-900 mb-2 flex items-center gap-2">
                                    <span>💳</span> Pagar online con Mercado Pago
                                </h4>
                                <p className="text-xs text-blue-700 mb-4">
                                    Tarjeta, débito o dinero en cuenta. Tu pedido queda
                                    confirmado automáticamente y te damos el código de retiro;
                                    no necesitas subir comprobante.
                                </p>
                                <button type="button"
                                    data-testid="pagar-mercadopago-bazar"
                                    onClick={handlePagarOnline}
                                    disabled={yendoAPagar || subiendo}
                                    className="w-full px-6 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 font-bold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                    {yendoAPagar ? 'Redirigiendo a Mercado Pago...' : '💳 Pagar con Mercado Pago'}
                                </button>
                            </div>
                        )}

                        {mensaje.text && (
                            <div className={`p-4 rounded-xl border text-sm font-medium ${mensaje.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-red-50 border-red-200 text-red-700'}`}>
                                {mensaje.type === 'success' ? '✅' : '❌'} {mensaje.text}
                            </div>
                        )}

                        <div className="flex gap-4">
                            <button onClick={() => { setPaso(1); setMensaje({ type: '', text: '' }); }}
                                className="px-6 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm">
                                ← Volver
                            </button>
                            <button onClick={handleEnviarPedido} disabled={subiendo || !archivoVoucher || !configBancaria}
                                className="flex-1 px-6 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm disabled:opacity-50">
                                {subiendo ? 'Procesando...' : '✅ Enviar Pedido'}
                            </button>
                        </div>
                    </div>
                )}

                {paso === 3 && (
                    <div className="text-center py-12">
                        <div className="text-6xl mb-6">✅</div>
                        <h2 className="text-2xl font-bold text-gray-800 mb-3">¡Pedido Enviado!</h2>
                        <p className="text-gray-600 mb-4">{mensaje.text}</p>
                        <a href="/alumno/mis-pedidos" className="inline-block px-8 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm">
                            Ver Mis Pedidos
                        </a>
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default Bazar;