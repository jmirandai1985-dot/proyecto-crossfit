import React, { useState } from 'react';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import { useAuth } from '../../context/AuthContext';
// Fase 2 (Bloque 1): planes, perfil, datos bancarios, descuento vigente y subida de
// documentos salen de la caché compartida (`hooks/queries.js`), no de un `useEffect` que
// repetía las mismas peticiones en cada montaje.
import {
    useConfiguracionBancaria, useCrearPagoMembresia, useMiPerfil,
    useMisBeneficios, usePagoDisponible, usePlanesActivos, useSolicitarPlan,
    useSubirArchivoPrivado,
} from '../../hooks/queries';
import { fmtFechaChile } from '../../utils/fecha';

const SolicitarPlan = () => {
    const { usuario_id, tenant_id } = useAuth();

    // ─── Datos (React Query) ───────────────────────────────────────────
    // Planes, perfil, datos bancarios y descuento vigente salen de la caché compartida:
    // volver a esta pantalla ya no repite las peticiones que hacía el useEffect.
    const planesQ = usePlanesActivos();
    const perfilQ = useMiPerfil();
    const configQ = useConfiguracionBancaria(tenant_id);

    const perfil = perfilQ.data || null;
    const sexoAlumno = perfil?.genero || null;
    // Aviso "completa tu sexo en Ajustes": sólo cuando el perfil YA llegó sin género (si
    // la consulta falla no se le pide al alumno arreglar algo que no está roto).
    const sinSexo = Boolean(perfil) && !sexoAlumno;

    const planes = React.useMemo(() => planesQ.data || [], [planesQ.data]);

    // ─── F2 + F3b: el descuento que se va a COBRAR en esta compra ──
    // `precios` viene del BACKEND (`/beneficios/mios?plan_ids=...`): la pantalla muestra el
    // precio final, no lo calcula (la aritmética del descuento vive en un solo lugar y es
    // la que se cobra). El backend anuncia ahí el beneficio de Fidelización (F2) o, si no
    // hay, el premio del programa de referidos (F3b): los dos caminos congelan el mismo
    // número en la solicitud y en la preferencia de Mercado Pago. Si esto falla, la
    // pantalla sigue igual, sin descuento anunciado.
    const planIds = planes.map((p) => p.id).join(',');
    const beneficiosQ = useMisBeneficios(planIds);
    const descuento = React.useMemo(() => {
        const datos = beneficiosQ.data;
        if (!datos) return null;
        // `descuento_pct` es F2 (con vencimiento); `descuento_referido_pct` es el premio
        // por invitar. El backend nunca manda los dos a la vez (no se apilan).
        const pct = datos.descuento_pct ?? datos.descuento_referido_pct;
        return pct ? { ...datos, descuento_pct: pct } : null;
    }, [beneficiosQ.data]);

    // Datos bancarios del paso 2 (los guarda un admin en /admin/configuracion).
    const configBancaria = configQ.data?.configurado ? configQ.data : null;

    // Subir los documentos es una ORDEN (devuelve la URL privada) y enviar la solicitud
    // mueve la cola del admin: ninguna de las dos necesita estado local.
    const subirArchivo = useSubirArchivoPrivado();
    const solicitarPlan = useSolicitarPlan();
    const subiendo = subirArchivo.isPending || solicitarPlan.isPending;

    // ─── Pago online (Mercado Pago Checkout Pro) ───────────────────────────
    // Convive con la transferencia: el botón aparece SÓLO si el backend dice que
    // la pasarela está encendida (`GET /pagos/disponibilidad`). La tarjeta nunca
    // pasa por la app: el backend devuelve `init_point` y acá se redirige.
    const pagoDisponibleQ = usePagoDisponible();
    const pagoDisponible = Boolean(pagoDisponibleQ.data?.habilitado);
    const crearPagoOnline = useCrearPagoMembresia();
    // "Yendo a pagar": se queda en true al redirigir (evita el doble clic).
    const [yendoAPagar, setYendoAPagar] = useState(false);

    // ─── Jerarquía de la pantalla (rediseño) ───────────────────────────────
    // Mercado Pago es el camino principal: va primero y siempre abierto. La
    // transferencia se muestra como una fila que se expande (accordion), igual que
    // en el mockup aprobado. `null` = automático: se abre sola SÓLO si la pasarela
    // está apagada, así la pantalla nunca queda sin ningún botón de pago. Si el
    // alumno toca la fila, su elección manda.
    const [transferenciaAbierta, setTransferenciaAbierta] = useState(null);
    // `isPending` = todavía no sabemos si hay pasarela: mientras tanto la fila queda
    // cerrada. Si la consulta FALLA también la abrimos: es preferible ofrecer la
    // transferencia de más que dejar la pantalla sin ningún botón de pago.
    const pasarelaApagada = !pagoDisponibleQ.isPending && !pagoDisponible;
    const transferenciaVisible = transferenciaAbierta !== null
        ? transferenciaAbierta
        : pasarelaApagada;

    // "Cargando" mientras falte el primer dato de las dos consultas del bloque (antes: un
    // `loading` que apagaba el `finally` del fetch).
    const loading = planesQ.isPending || perfilQ.isPending;
    const error = planesQ.isError || perfilQ.isError
        ? 'No se pudieron cargar los planes disponibles.'
        : '';

    // ─── Estado del flujo (1 = elegir plan, 2 = datos pago, 3 = confirmación) ───
    const [paso, setPaso] = useState(1);
    const [planSeleccionado, setPlanSeleccionado] = useState(null);
    const [archivoVoucher, setArchivoVoucher] = useState(null);
    const [archivoCertificado, setArchivoCertificado] = useState(null);
    const [mensajeExito, setMensajeExito] = useState('');
    const [mensajeError, setMensajeError] = useState('');

    // Categoría visible: la propone el sexo del perfil y el alumno la puede cambiar. Se
    // DERIVA de las consultas (antes se sincronizaba con un `setCategoriaSeleccionada`
    // dentro del fetch); si el alumno elige "Todos", su elección manda.
    const [categoriaElegida, setCategoriaElegida] = useState(null);
    const categoriaSeleccionada = categoriaElegida !== null
        ? categoriaElegida
        : (sexoAlumno === 'M' ? 'masculino' : sexoAlumno === 'F' ? 'femenino' : null);

    const planesFiltrados = React.useMemo(() => (
        categoriaSeleccionada
            ? planes.filter((p) => !p.genero || p.genero === categoriaSeleccionada)
            : planes
    ), [categoriaSeleccionada, planes]);

    // Separar planes regulares y de estudiante
    const planesRegulares = planesFiltrados.filter(p => !p.requiere_certificado_estudiante);
    const planesEstudiante = planesFiltrados.filter(p => p.requiere_certificado_estudiante);

    /** Precio final del plan si tiene un descuento vigente (o `null`). */
    const precioConDescuento = (plan) => descuento?.precios?.[String(plan?.id)] || null;

    /**
     * Precio que se cobra hoy por el plan: el que ya calculó el backend (con el
     * beneficio aplicado) o el de lista. Sirve para el CTA de Mercado Pago, que
     * anuncia el monto de la misma fuente que el resumen.
     */
    const precioAPagar = (plan) => precioConDescuento(plan)?.precio_final_clp ?? plan?.precio_clp ?? null;

    /** dd-mm-aaaa de la vigencia del descuento (lo que ve el alumno en el aviso). */
    const vigenciaDescuento = () => {
        if (!descuento?.descuento_hasta) return '';
        return fmtFechaChile(descuento.descuento_hasta);
    };

    /**
     * De dónde sale el descuento que se anuncia: el beneficio de Fidelización (F2) tiene
     * vencimiento; el premio del programa de referidos (F3b) es por la invitación y no
     * caduca. La pantalla dice lo que el backend va a cobrar, no una fecha inventada.
     */
    const motivoDescuento = () => (descuento?.descuento_hasta
        ? `válido hasta el ${vigenciaDescuento()}`
        : 'por tu invitación');

    const handleSeleccionarPlan = (plan) => {
        setPlanSeleccionado(plan);
        setPaso(2);
        setMensajeError('');
    };

    const handleEnviarSolicitud = async () => {
        if (!archivoVoucher) {
            setMensajeError('Debes seleccionar un comprobante de pago.');
            return;
        }
        if (planSeleccionado?.requiere_certificado_estudiante && !archivoCertificado) {
            setMensajeError('Este plan requiere un certificado de estudiante. Debes subirlo.');
            return;
        }
        if (!planSeleccionado) return;

        setMensajeError('');
        try {
            // 1. Subir voucher. privado=1: el comprobante va a la carpeta privada y sólo lo
            // sirve el endpoint autenticado GET /solicitudes/{id}/voucher.
            const voucherUrl = await subirArchivo.mutateAsync(archivoVoucher);

            // 2. Subir certificado (si el plan lo exige). Igual que el voucher: documento
            // sensible, carpeta privada, servido sólo por GET /solicitudes/{id}/certificado.
            let certificadoUrl = '';
            if (planSeleccionado?.requiere_certificado_estudiante && archivoCertificado) {
                certificadoUrl = await subirArchivo.mutateAsync(archivoCertificado);
            }

            // 3. Enviar solicitud
            await solicitarPlan.mutateAsync({
                tenant_id,
                alumno_id: usuario_id,
                plan_id: planSeleccionado.id,
                voucher_url: voucherUrl,
                certificado_estudiante_url: certificadoUrl || null,
            });

            setPaso(3);
            setMensajeExito('✅ Tu solicitud fue enviada, espera la aprobación del administrador.');
        } catch (err) {
            console.error('Error al enviar solicitud:', err);
            setMensajeError(
                err.response?.data?.detail || 'Error al procesar la solicitud. Intenta nuevamente.'
            );
        }
    };

    /**
     * Paga el plan online (Checkout Pro). Crea la solicitud SIN comprobante: el
     * cobro lo prueba Mercado Pago y el webhook activa el plan automáticamente.
     * El certificado de estudiante SÍ se sube antes (es un requisito del plan,
     * no una prueba de pago): al mismo lugar privado que en la transferencia.
     */
    const handlePagarOnline = async () => {
        if (!planSeleccionado) return;
        if (planSeleccionado?.requiere_certificado_estudiante && !archivoCertificado) {
            setMensajeError('Este plan requiere un certificado de estudiante. Debes subirlo.');
            return;
        }
        setMensajeError('');
        setYendoAPagar(true);
        try {
            let certificadoUrl = null;
            if (planSeleccionado?.requiere_certificado_estudiante && archivoCertificado) {
                certificadoUrl = await subirArchivo.mutateAsync(archivoCertificado);
            }
            const pago = await crearPagoOnline.mutateAsync({
                plan_id: planSeleccionado.id,
                certificado_estudiante_url: certificadoUrl,
            });
            // Checkout Pro: se sale a Mercado Pago y se vuelve a
            // /alumno/pago/resultado/<pago_id>. Nada de esto activa el plan: eso
            // lo hace el webhook, no el navegador.
            window.location.href = pago.init_point;
        } catch (err) {
            console.error('Error al iniciar el pago online:', err);
            setMensajeError(
                err.response?.data?.detail
                || 'No se pudo iniciar el pago online. Intenta nuevamente o usa transferencia.'
            );
            setYendoAPagar(false);
        }
    };

    const formatearPrecio = (precio) => {
        if (!precio) return '—';
        return '$' + precio.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    };

    const renderPlanCard = (plan) => {
        const conDescuento = precioConDescuento(plan);
        return (
        <button
            key={plan.id}
            onClick={() => handleSeleccionarPlan(plan)}
            className="bg-white rounded-xl border-2 border-gray-200 p-6 shadow-sm hover:border-emerald-400 hover:shadow-md transition-all text-left group"
        >
            <div className="flex items-center gap-2 mb-3">
                <span className="text-2xl">🏅</span>
                <h3 className="text-lg font-bold text-gray-800 group-hover:text-emerald-600 transition-colors">
                    {plan.nombre}
                </h3>
            </div>
            {conDescuento ? (
                <div className="mb-4" data-testid={`precio-descuento-${plan.id}`}>
                    <p className="text-sm text-gray-400 line-through">
                        {formatearPrecio(conDescuento.precio_lista_clp)}
                    </p>
                    <p className="text-3xl font-bold text-emerald-600">
                        {formatearPrecio(conDescuento.precio_final_clp)}
                    </p>
                    <p className="text-xs font-semibold text-emerald-700">
                        con tu −{descuento.descuento_pct} % de descuento · {motivoDescuento()}
                    </p>
                </div>
            ) : (
                <p className="text-3xl font-bold text-emerald-600 mb-4">
                    {formatearPrecio(plan.precio_clp)}
                </p>
            )}
            <div className="space-y-2 text-sm text-gray-600">
                <div className="flex items-center gap-2">
                    <span className="text-emerald-500">✅</span>
                    <span>
                        {plan.es_ilimitado
                            ? '♾️ Clases ilimitadas'
                            : `📊 ${plan.creditos || plan.clases_por_mes || '—'} créditos`}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-emerald-500">✅</span>
                    <span>📆 Duración: {plan.duracion_dias || 30} días</span>
                </div>
                {plan.requiere_certificado_estudiante && (
                    <div className="flex items-center gap-2 mt-2">
                        <span className="text-amber-500">🎓</span>
                        <span className="text-amber-700 font-semibold">Plan Estudiante</span>
                    </div>
                )}
                {plan.descripcion && (
                    <p className="text-gray-400 italic mt-2 text-xs">{plan.descripcion}</p>
                )}
            </div>
            <div className="mt-5 text-center">
                <span className="inline-block px-6 py-2 bg-emerald-500 text-white rounded-lg text-sm font-bold group-hover:bg-emerald-600 transition-colors">
                    Seleccionar
                </span>
            </div>
        </button>
        );
    };

    // Aviso del descuento que se va a aplicar en esta compra (F2 o referidos): el alumno lo
    // ve ANTES de elegir, con su % y —si el premio vence— su fecha límite.
    const avisoDescuento = descuento && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4"
            data-testid="aviso-descuento">
            <p className="text-emerald-800 font-semibold">
                🎁 Tienes un {descuento.descuento_pct} % de descuento en tu próximo plan
            </p>
            <p className="text-sm text-emerald-700">
                {descuento.descuento_hasta
                    ? `Válido hasta el ${vigenciaDescuento()}.`
                    : 'Por la invitación de un alumno del box.'}
                {' '}Se aplica al solicitar: los precios de abajo ya están con el
                descuento hecho.
            </p>
        </div>
    );

    // ─── Loading ───────────────────────────────────────────────────────
    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500 mx-auto mb-4"></div>
                        <p className="text-gray-500">Cargando planes disponibles...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">

                {/* ─── TÍTULO ─────────────────────────────────────── */}
                <div className="flex items-center gap-3">
                    <BotonVolver />
                    <span className="text-3xl">💳</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Solicitar Plan</h1>
                        <p className="text-sm text-gray-500">Elige el plan que mejor se adapte a ti</p>
                    </div>
                </div>

                {/* ─── ERROR GENERAL ───────────────────────────────── */}
                {error && (
                    <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 font-medium text-sm">
                        ❌ {error}
                    </div>
                )}

                {/* ─── AVISO: SIN SEXO CARGADO ────────────────────── */}
                {paso === 1 && sinSexo && (
                    <div className="p-5 rounded-xl bg-amber-50 border border-amber-200 text-amber-800">
                        <div className="flex items-center gap-3">
                            <span className="text-2xl">⚠️</span>
                            <div>
                                <p className="font-bold text-sm">Completa tu sexo en Ajustes</p>
                                <p className="text-xs text-amber-600 mt-1">
                                    Para sugerirte planes según tu perfil, indica tu sexo en Ajustes.
                                    Mientras tanto, puedes explorar todas las categorías.
                                </p>
                                <a href="/alumno/ajustes" className="inline-block mt-2 text-xs font-bold text-amber-700 underline hover:text-amber-800">
                                    Ir a Ajustes →
                                </a>
                            </div>
                        </div>
                    </div>
                )}

                {/* ══════════════════════════════════════════════════════
                    PASO 1: ELEGIR PLAN
                    ══════════════════════════════════════════════════════ */}
                {paso === 1 && (
                    <>
                        {/* ─── TOGGLE: FEMENINO / MASCULINO / TODOS ── */}
                        <div className="flex gap-2 p-1 bg-gray-100 rounded-xl w-fit mx-auto">
                            <button onClick={() => setCategoriaElegida('femenino')}
                                className={`px-6 py-2.5 rounded-lg text-sm font-bold transition-all ${categoriaSeleccionada === 'femenino'
                                    ? 'bg-pink-500 text-white shadow-md'
                                    : 'text-gray-600 hover:bg-pink-50 hover:text-pink-600'}`}>
                                ♀️ Femeninos
                            </button>
                            <button onClick={() => setCategoriaElegida('masculino')}
                                className={`px-6 py-2.5 rounded-lg text-sm font-bold transition-all ${categoriaSeleccionada === 'masculino'
                                    ? 'bg-blue-500 text-white shadow-md'
                                    : 'text-gray-600 hover:bg-blue-50 hover:text-blue-600'}`}>
                                ♂️ Masculinos
                            </button>
                            <button onClick={() => setCategoriaElegida(null)}
                                className={`px-6 py-2.5 rounded-lg text-sm font-bold transition-all ${categoriaSeleccionada === null
                                    ? 'bg-gray-500 text-white shadow-md'
                                    : 'text-gray-600 hover:bg-gray-200'}`}>
                                Todos
                            </button>
                        </div>

                        {/* ── El descuento vigente, antes de elegir (F2) ── */}
                        {avisoDescuento}

                        {planesRegulares.length === 0 && planesEstudiante.length === 0 && (
                            <div className="col-span-full text-center py-12">
                                <p className="text-gray-400 text-lg mb-2">📋 No hay planes disponibles</p>
                                <p className="text-gray-400 text-sm">Prueba seleccionando otra categoría arriba</p>
                            </div>
                        )}

                        {/* ─── PLANES REGULARES ───────────────────── */}
                        {planesRegulares.length > 0 && (
                            <div>
                                <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-2">
                                    <span>⭐</span> PLANES REGULARES
                                </h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                                    {planesRegulares.map(renderPlanCard)}
                                </div>
                            </div>
                        )}

                        {/* ─── PLANES PARA ESTUDIANTES ────────────── */}
                        {planesEstudiante.length > 0 && (
                            <div className="mt-6">
                                <h3 className="text-sm font-bold text-amber-600 uppercase tracking-wider mb-3 flex items-center gap-2">
                                    <span>🎓</span> PLANES PARA ESTUDIANTES
                                </h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                                    {planesEstudiante.map(renderPlanCard)}
                                </div>
                            </div>
                        )}
                    </>
                )}

                {/* ══════════════════════════════════════════════════════
                    PASO 2: DATOS DE PAGO Y VOUCHER
                    ══════════════════════════════════════════════════════ */}
                {paso === 2 && planSeleccionado && (
                    <div className="space-y-6">
                        {/* Resumen del plan seleccionado */}
                        <div className="bg-emerald-50 rounded-xl border border-emerald-200 p-5">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-xs text-emerald-600 uppercase tracking-wider font-semibold">Plan seleccionado</p>
                                    <h3 className="text-xl font-bold text-gray-800">{planSeleccionado.nombre}</h3>
                                </div>
                                <span className="text-2xl font-bold text-emerald-600">
                                    {precioConDescuento(planSeleccionado) ? (
                                        <>
                                            <span className="text-base text-gray-400 line-through mr-2"
                                                data-testid="resumen-precio-lista">
                                                {formatearPrecio(precioConDescuento(planSeleccionado).precio_lista_clp)}
                                            </span>
                                            {formatearPrecio(precioConDescuento(planSeleccionado).precio_final_clp)}
                                        </>
                                    ) : formatearPrecio(planSeleccionado.precio_clp)}
                                </span>
                            </div>
                            {precioConDescuento(planSeleccionado) && (
                                <p className="mt-2 text-xs font-semibold text-emerald-700"
                                    data-testid="resumen-descuento">
                                    Descuento aplicado: −{descuento.descuento_pct} % · {motivoDescuento()}
                                    {' '}· paga el precio final
                                </p>
                            )}
                        </div>

                        {/* ─── CERTIFICADO DE ESTUDIANTE (requisito del plan) ──
                            Va ANTES de los métodos de pago porque lo exigen los dos:
                            se sube una sola vez y habilita tanto el pago online como
                            la transferencia. */}
                        {planSeleccionado.requiere_certificado_estudiante && (
                            <div className="bg-amber-50 rounded-xl border border-amber-200 p-5 shadow-sm">
                                <h4 className="font-bold text-amber-800 mb-3 flex items-center gap-2">
                                    <span>🎓</span> Certificado de Estudiante
                                </h4>
                                <p className="text-xs text-amber-600 mb-4">
                                    Este plan requiere que acredites tu condición de estudiante.
                                    Sube tu carnet de alumno, certificado de matrícula o cualquier documento que lo acredite.
                                    Formatos: imagen (JPG, PNG) o PDF. Máximo 5 MB.
                                </p>
                                <div className="border-2 border-dashed border-amber-300 rounded-xl p-6 text-center hover:border-amber-500 transition-colors bg-white">
                                    <input type="file" id="certificado-upload" accept="image/*,application/pdf"
                                        onChange={(e) => setArchivoCertificado(e.target.files[0] || null)} className="hidden" />
                                    <label htmlFor="certificado-upload" className="cursor-pointer">
                                        <span className="text-4xl block mb-2">{archivoCertificado ? '📄' : '🎓'}</span>
                                        {archivoCertificado ? (
                                            <div>
                                                <p className="text-sm font-medium text-amber-700">{archivoCertificado.name}</p>
                                                <p className="text-xs text-amber-500 mt-1">{(archivoCertificado.size / 1024 / 1024).toFixed(2)} MB</p>
                                                <p className="text-xs text-amber-600 mt-2">Haz clic para cambiar archivo</p>
                                            </div>
                                        ) : (
                                            <div>
                                                <p className="text-sm font-medium text-amber-700">Haz clic para subir tu certificado</p>
                                                <p className="text-xs text-amber-500 mt-1">Carnet, matrícula o documento similar</p>
                                            </div>
                                        )}
                                    </label>
                                </div>
                            </div>
                        )}

                        {/* ─── MÉTODOS DE PAGO ─── */}
                        <div>
                            <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-1">
                                ¿Cómo quieres pagar?
                            </h3>
                            <p className="text-xs text-gray-400">
                                Elige un método: cada uno tiene su propio botón.
                            </p>
                        </div>

                        {/* ─── 1. MERCADO PAGO (camino principal) ───
                            Primero y con más peso visual: no exige comprobante ni revisión
                            manual (el webhook activa el plan). El bloque sólo existe si el
                            box habilitó la pasarela. */}
                        {/* SKIN: los colores del mockup viajan como valores arbitrarios de
                            Tailwind (`bg-[#1C1B1A]`) porque `src/index.css` reescribe varias
                            paletas con `!important` (y blue-50/blue-200/blue-900 nunca se
                            reescribieron: por eso las tarjetas quedaban celestes acá).
                            El azul #3B5BDB es la marca de Mercado Pago: badge y CTA lo usan. */}
                        {pagoDisponible && (
                            <div className="rounded-xl border-2 border-[#3B5BDB44] bg-[#1C1B1A] p-5 shadow-sm"
                                data-testid="bloque-pago-online">
                                <div className="flex items-start gap-3">
                                    <span className="text-2xl">💳</span>
                                    <div>
                                        <span className="inline-block rounded-full bg-[#3B5BDB] px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-white">
                                            Más rápido
                                        </span>
                                        <h4 className="mt-1 text-base font-bold text-[#F5F4F1]">Pagar con tarjeta</h4>
                                        <p className="text-xs text-[#A8A6A1]">Vía Mercado Pago · activación instantánea</p>
                                    </div>
                                </div>
                                <div className="mt-3 flex flex-wrap gap-2">
                                    <span className="rounded-full border border-[#2A2927] bg-[#141413] px-2.5 py-1 text-[11px] font-semibold text-[#A8A6A1]"><span className="text-[#6FCF6F]">✓</span> Sin comprobante</span>
                                    <span className="rounded-full border border-[#2A2927] bg-[#141413] px-2.5 py-1 text-[11px] font-semibold text-[#A8A6A1]"><span className="text-[#6FCF6F]">✓</span> Débito, crédito o saldo</span>
                                    <span className="rounded-full border border-[#2A2927] bg-[#141413] px-2.5 py-1 text-[11px] font-semibold text-[#A8A6A1]"><span className="text-[#6FCF6F]">✓</span> Activación automática</span>
                                </div>
                                <p className="mt-3 text-xs text-[#A8A6A1]">
                                    Tu plan se activa automáticamente cuando Mercado Pago confirma el pago:
                                    no necesitas subir comprobante ni esperar aprobación.
                                </p>
                                <button type="button"
                                    data-testid="pagar-mercadopago-plan"
                                    onClick={handlePagarOnline}
                                    disabled={yendoAPagar || subiendo || (planSeleccionado.requiere_certificado_estudiante && !archivoCertificado)}
                                    className="mt-4 w-full px-6 py-3.5 bg-[#3B5BDB] text-white rounded-xl hover:bg-[#4F6BE3] font-bold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                    {yendoAPagar
                                        ? 'Redirigiendo a Mercado Pago...'
                                        : (precioAPagar(planSeleccionado)
                                            ? `💳 Pagar ${formatearPrecio(precioAPagar(planSeleccionado))} con Mercado Pago`
                                            : '💳 Pagar con Mercado Pago')}
                                </button>
                                {planSeleccionado.requiere_certificado_estudiante && !archivoCertificado && (
                                    <p className="mt-2 text-center text-xs font-semibold text-amber-700">
                                        Sube tu certificado de estudiante (arriba) para habilitar el pago.
                                    </p>
                                )}
                            </div>
                        )}

                        {/* ─── 2. TRANSFERENCIA (alternativa, colapsada) ───
                            Mismo flujo de siempre (datos bancarios + comprobante + enviar
                            solicitud), pero detrás de una fila que se abre: Mercado Pago es
                            el camino principal. Con la pasarela apagada la fila arranca
                            abierta, así la pantalla nunca queda sin su botón. */}
                        <div className="rounded-xl border border-[#2A2927] bg-[#1C1B1A] overflow-hidden shadow-sm"
                            data-testid="bloque-transferencia">
                            <button type="button"
                                data-testid="toggle-transferencia"
                                aria-expanded={transferenciaVisible}
                                aria-controls="panel-transferencia"
                                onClick={() => setTransferenciaAbierta(!transferenciaVisible)}
                                className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-[#242322] transition-colors">
                                <span className="text-xl">🏦</span>
                                <span className="flex-1">
                                    <span className="block text-sm font-bold text-[#F5F4F1]">Prefiero transferir</span>
                                    <span className="block text-xs text-[#78766F]">
                                        {archivoVoucher
                                            ? 'Comprobante listo: expande para enviar tu solicitud'
                                            : 'Revisión manual: puede tardar hasta 24 h hábiles'}
                                    </span>
                                </span>
                                <span className={`text-[#78766F] transition-transform ${transferenciaVisible ? 'rotate-180' : ''}`}>▾</span>
                            </button>

                            {transferenciaVisible && (
                                <div id="panel-transferencia"
                                    className="border-t border-[#2A2927] bg-[#1C1B1A] px-5 py-5 space-y-4">
                                    <div className="rounded-xl border border-[#2A2927] bg-[#141413] p-5 shadow-sm">
                                        <h4 className="font-bold text-[#E0B83C] mb-3 flex items-center gap-2">
                                            <span>🏦</span> Datos para Transferencia
                                        </h4>
                                        {configBancaria ? (
                                            <div className="space-y-2 text-sm text-[#A8A6A1]">
                                                <p className="font-semibold text-[#A8A6A1]">Transfiere a:</p>
                                                <div className="rounded-lg p-3 border border-[#2A2927] bg-[#1C1B1A] space-y-1.5">
                                                    <p><span className="font-medium text-[#78766F]">Banco:</span> <span className="text-[#7FB0F0]">{configBancaria.banco}</span></p>
                                                    <p><span className="font-medium text-[#78766F]">Tipo de Cuenta:</span> <span className="text-[#7FB0F0]">{configBancaria.tipo_cuenta}</span></p>
                                                    <p><span className="font-medium text-[#78766F]">N° de Cuenta:</span> <span className="font-bold text-[#7FB0F0]">{configBancaria.numero_cuenta}</span></p>
                                                    <p><span className="font-medium text-[#78766F]">RUT:</span> <span className="text-[#7FB0F0]">{configBancaria.rut}</span></p>
                                                    <p><span className="font-medium text-[#78766F]">Email comprobantes:</span> <span className="text-[#7FB0F0]">{configBancaria.email_comprobantes}</span></p>
                                                </div>
                                                <p className="text-xs text-[#78766F] mt-2 italic">
                                                    Luego de transferir, sube el comprobante abajo para que validemos tu pago.
                                                </p>
                                            </div>
                                        ) : (
                                            <div className="text-sm text-[#A8A6A1] rounded-lg p-3 border border-[#2A2927] bg-[#1C1B1A]">
                                                <p>⏳ El box aún no ha configurado sus datos de pago.</p>
                                                <p className="text-xs mt-1">Por favor contacta al administrador para obtener la información de transferencia.</p>
                                            </div>
                                        )}
                                    </div>

                                    {/* ─── SUBIR VOUCHER DE PAGO ─── */}
                                    <div className="rounded-xl border border-[#2A2927] bg-[#1C1B1A] p-5 shadow-sm">
                                        <h4 className="font-bold text-[#F5F4F1] mb-3 flex items-center gap-2">
                                            <span>📎</span> Subir Comprobante de Pago
                                        </h4>
                                        <p className="text-xs text-[#A8A6A1] mb-4">
                                            Formatos aceptados: imagen (JPG, PNG) o PDF. Máximo 5 MB.
                                        </p>
                                        <div className="border-2 border-dashed border-[#2A2927] rounded-xl p-6 text-center hover:border-[#6FCF6F] transition-colors">
                                            <input type="file" id="voucher-upload" accept="image/*,application/pdf"
                                                onChange={(e) => setArchivoVoucher(e.target.files[0] || null)} className="hidden" />
                                            <label htmlFor="voucher-upload" className="cursor-pointer">
                                                <span className="text-4xl block mb-2">{archivoVoucher ? '📄' : '📤'}</span>
                                                {archivoVoucher ? (
                                                    <div>
                                                        <p className="text-sm font-medium text-emerald-600">{archivoVoucher.name}</p>
                                                        <p className="text-xs text-[#78766F] mt-1">{(archivoVoucher.size / 1024 / 1024).toFixed(2)} MB</p>
                                                        <p className="text-xs text-emerald-500 mt-2">Haz clic para cambiar archivo</p>
                                                    </div>
                                                ) : (
                                                    <div>
                                                        <p className="text-sm font-medium text-[#A8A6A1]">Haz clic para seleccionar el comprobante</p>
                                                        <p className="text-xs text-[#78766F] mt-1">o arrastra el archivo aquí</p>
                                                    </div>
                                                )}
                                            </label>
                                        </div>
                                    </div>

                                    {/* El ÚNICO CTA de este método: sube el comprobante y deja la
                                        solicitud pendiente de revisión del box. */}
                                    <button type="button"
                                        data-testid="enviar-solicitud"
                                        onClick={handleEnviarSolicitud}
                                        disabled={subiendo || yendoAPagar || !archivoVoucher || !configBancaria || (planSeleccionado.requiere_certificado_estudiante && !archivoCertificado)}
                                        className="w-full px-6 py-3.5 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                        {subiendo ? 'Enviando solicitud...' : '📎 Subir comprobante de transferencia'}
                                    </button>
                                    <p className="text-center text-xs text-[#78766F]">
                                        Tu solicitud queda pendiente hasta que el box confirme la transferencia.
                                    </p>
                                </div>
                            )}
                        </div>

                        {mensajeError && (
                            <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 font-medium text-sm">
                                ❌ {mensajeError}
                            </div>
                        )}

                        <div className="flex gap-4 pt-2">
                            <button type="button"
                                onClick={() => { setPaso(1); setPlanSeleccionado(null); setMensajeError(''); }}
                                className="px-6 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors"
                                disabled={subiendo || yendoAPagar}>
                                ← Volver
                            </button>
                        </div>
                    </div>
                )}

                {/* ══════════════════════════════════════════════════════
                    PASO 3: CONFIRMACIÓN
                    ══════════════════════════════════════════════════════ */}
                {paso === 3 && (
                    <div className="text-center py-12">
                        <div className="text-6xl mb-6">✅</div>
                        <h2 className="text-2xl font-bold text-gray-800 mb-3">¡Solicitud Enviada!</h2>
                        <p className="text-gray-600 mb-8 max-w-md mx-auto">{mensajeExito}</p>
                        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 max-w-md mx-auto text-left text-sm text-gray-700 space-y-2">
                            <p className="font-semibold text-emerald-800">📋 ¿Qué sigue?</p>
                            <p>1. El administrador revisará tu solicitud y comprobante.</p>
                            <p>2. Una vez aprobado, tu plan se activará automáticamente.</p>
                            <p>3. Recibirás una notificación cuando esté listo.</p>
                            <p className="text-xs text-gray-400 italic mt-2">Este proceso puede tomar hasta 24 horas hábiles.</p>
                        </div>
                        <a href="/alumno/dashboard"
                            className="inline-block mt-8 px-8 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors">
                            Volver al Inicio
                        </a>
                    </div>
                )}

            </div>
        </Layout>
    );
};

export default SolicitarPlan;