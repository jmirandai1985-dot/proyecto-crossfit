import React, { useState } from 'react';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import InvitarPorCorreo from '../../components/InvitarPorCorreo';
// El INVITADO aplica el código de quien lo trajo ACÁ (no en la compra): el
// backend ya descuenta el premio antes de cobrar, así que éste es el único lugar
// donde el código se ingresa.
import CampoReferido from '../../components/CampoReferido';
import { useMiCodigoReferido, useMiInvitacion, useMiProgresoReferidos } from '../../hooks/queries';
import { copiarAlPortapapeles, textoCompartirReferido } from '../../utils/referidos';

const fechaLarga = (valor) => {
    if (!valor) return '';
    const fecha = new Date(valor);
    if (Number.isNaN(fecha.getTime())) return '';
    return new Intl.DateTimeFormat('es-CL', {
        day: 'numeric', month: 'long', year: 'numeric',
    }).format(fecha);
};

/**
 * "Invita y gana": la pantalla del programa de referidos, con los DOS lados.
 * El INVITADOR ve y comparte su código (y puede invitar a un amigo por correo,
 * migración 054); el INVITADO aplica el código de quien lo trajo en el bloque
 * "¿Te invitó un amigo?" (`CampoReferido`).
 *
 * `CampoReferido` vivía en el paso de compra (`SolicitarPlan`) y se fue de ahí
 * cuando el backend empezó a descontar ANTES de cobrar: el precio con descuento
 * ya viaja en `/beneficios/mios` y se congela en la solicitud / en la
 * preferencia de Mercado Pago, así que el código sólo hay que aplicarlo una vez
 * y el pago no necesita un formulario propio.
 *
 * El código propio lo crea el backend al activarse un plan; si el alumno aún
 * no tiene fila, `GET /referidos/mi-codigo` responde 404 y acá se explica sin
 * romper la pantalla ni el resto de la app.
 */
const InvitaYGana = () => {
    const { data, isPending, isError, error, refetch } = useMiCodigoReferido();
    // "Tu ciclo" (Parte C): sólo tiene sentido con la pantalla cargada; si el
    // endpoint falla, el bloque no se dibuja y el resto de la pantalla sigue igual.
    const { data: progreso } = useMiProgresoReferidos({ enabled: Boolean(data) });
    // El lado del INVITADO: la invitación de otro alumno que trajo a este usuario
    // (`GET /referidos/mi-invitacion`, 200 con `codigo: null` si no lo invitó
    // nadie). Su `codigo` sólo PRELLENA el campo; aplicarlo sigue siendo un toque
    // explícito en `CampoReferido` (`POST /referidos/validar-codigo`).
    const { data: miInvitacion } = useMiInvitacion();
    // Resultado de aplicar el código: vive en la pantalla para que el bloque de
    // éxito no dependa de que `CampoReferido` siga montado.
    const [codigoAplicado, setCodigoAplicado] = useState(null);
    const [aviso, setAviso] = useState('');

    const codigo = data?.codigo || '';
    const activo = Boolean(data?.activo);
    const sinCodigo = isError && error?.response?.status === 404;

    const copiar = async () => {
        if (!codigo || !activo) return;
        try {
            await copiarAlPortapapeles(codigo);
            setAviso('✅ Código copiado al portapapeles.');
        } catch (err) {
            console.error('Error copiando el código de referido:', err);
            setAviso('❌ No pudimos copiar el código. Mantén presionado sobre él para copiarlo a mano.');
        }
    };

    const compartir = async () => {
        if (!codigo || !activo) return;

        const enlace = `${window.location.origin}/landing`;
        const mensaje = textoCompartirReferido(codigo, enlace);

        try {
            if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
                await navigator.share({ title: 'Invita y gana', text: mensaje });
                setAviso('✅ Invitación compartida.');
                return;
            }
            await copiarAlPortapapeles(mensaje);
            setAviso('✅ Tu navegador no permite compartir directo: copiamos la invitación para que la envíes.');
        } catch (err) {
            if (err?.name === 'AbortError') return;
            console.error('Error compartiendo el código de referido:', err);
            setAviso('❌ No pudimos abrir el menú de compartir. Copia el código y envíalo por tu cuenta.');
        }
    };

    return (
        <Layout>
            <div className="max-w-2xl mx-auto space-y-6">
                <div className="max-md:flex max-md:items-start max-md:gap-2">
                    <BotonVolver />
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">🎁 Invita y gana</h1>
                        <p className="text-gray-600 mt-1">
                            Comparte tu código con un amigo. Cuando compre su primer plan, ambos
                            reciben el beneficio que definió tu box.
                        </p>
                    </div>
                </div>

                {isPending && (
                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 flex items-center justify-center">
                        <div className="animate-spin rounded-full h-8 w-8 border-4 border-emerald-500 border-t-transparent"></div>
                    </div>
                )}

                {sinCodigo && (
                    <div className="bg-amber-50 border border-amber-200 rounded-xl p-5" data-testid="sin-codigo-referido">
                        <h2 className="text-base font-bold text-amber-900">Todavía no tienes un código</h2>
                        <p className="text-sm text-amber-800 mt-1">
                            {typeof error?.response?.data?.detail === 'string'
                                ? error.response.data.detail
                                : 'Tu código se genera cuando el box activa tu plan. Si crees que es un error, consulta con el administrador.'}
                        </p>
                        <button
                            type="button"
                            onClick={() => refetch()}
                            className="mt-3 text-sm font-semibold text-amber-900 underline"
                        >
                            Volver a intentar
                        </button>
                    </div>
                )}

                {isError && !sinCodigo && (
                    <div className="bg-red-50 border border-red-200 rounded-xl p-5">
                        <h2 className="text-base font-bold text-red-800">No pudimos cargar tu código</h2>
                        <p className="text-sm text-red-700 mt-1">
                            Revisa tu conexión e inténtalo de nuevo.
                        </p>
                        <button
                            type="button"
                            onClick={() => refetch()}
                            className="mt-3 text-sm font-semibold text-red-800 underline"
                        >
                            Reintentar
                        </button>
                    </div>
                )}


                {data && (
                    <div className="rounded-2xl bg-gradient-to-br from-emerald-500 via-emerald-600 to-emerald-700 text-white p-6 sm:p-8 shadow-lg shadow-emerald-600/20">
                        <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                                <p className="text-emerald-100 text-[11px] font-bold uppercase tracking-widest">
                                    Tu código de referido
                                </p>
                                <p
                                    data-testid="mi-codigo-referido"
                                    className="mt-2 font-mono text-3xl sm:text-4xl font-black tracking-[0.16em] break-all"
                                >
                                    {codigo}
                                </p>
                            </div>
                            <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${activo
                                ? 'bg-white/20 text-white'
                                : 'bg-amber-300 text-amber-950'}`}
                            >
                                {activo ? 'Activo' : 'Inactivo'}
                            </span>
                        </div>

                        {data.fecha_creacion && (
                            <p className="text-xs text-emerald-100 mt-3">
                                Creado el {fechaLarga(data.fecha_creacion)}
                            </p>
                        )}

                        <div className="mt-5 flex flex-col sm:flex-row gap-2">
                            <button
                                type="button"
                                onClick={copiar}
                                disabled={!activo}
                                data-testid="btn-copiar-codigo"
                                className="rounded-lg bg-white/15 hover:bg-white/25 disabled:opacity-50 disabled:cursor-not-allowed border border-white/30 px-4 py-2.5 text-sm font-bold transition-colors"
                            >
                                📋 Copiar código
                            </button>
                            <button
                                type="button"
                                onClick={compartir}
                                disabled={!activo}
                                data-testid="btn-compartir-codigo"
                                className="rounded-lg bg-white text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2.5 text-sm font-bold transition-colors"
                            >
                                📤 Compartir invitación
                            </button>
                        </div>

                        {!activo && (
                            <p className="mt-3 text-xs text-amber-100">
                                Tu código está inactivo: el box no aceptará invitaciones con él.
                                Consulta con el administrador para reactivarlo.
                            </p>
                        )}

                        {aviso && (
                            <p role="status" className="mt-3 text-sm text-emerald-50">
                                {aviso}
                            </p>
                        )}
                    </div>
                )}

                {/* ── "¿Te invitó un amigo?" (el lado del INVITADO) ──
                    Este campo vivía en el paso de compra (`SolicitarPlan`), dentro
                    de un acordeón que había que abrir ANTES de pagar: si el alumno
                    no lo abría —o pagaba primero— el descuento llegaba tarde. Acá
                    el código se aplica una vez, el precio con descuento aparece en
                    la solicitud y en el checkout de Mercado Pago, y la pantalla de
                    pago queda sin un formulario que no cobra nada. */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-bold text-gray-900">¿Te invitó un amigo?</h2>
                    <p className="text-sm text-gray-600 mt-1">
                        Si alguien te invitó al box, aplica su código <strong>antes de pagar</strong>
                        {' '}tu primer plan: el descuento se resta directo del precio que vas a
                        transferir o pagar online.
                    </p>
                    {miInvitacion?.codigo && (
                        <p className="text-xs text-emerald-700 mt-2" data-testid="invitado-por">
                            Te invitó {miInvitacion.nombre_invitador || 'un alumno del box'}
                            {' '}(código <strong className="font-mono">{miInvitacion.codigo}</strong>).
                        </p>
                    )}
                    <CampoReferido
                        className="mt-4"
                        mostrarTitulo={false}
                        codigoSugerido={miInvitacion?.codigo || ''}
                        aplicado={codigoAplicado}
                        onAplicado={setCodigoAplicado}
                    />
                </div>


                {/* ── "Tu ciclo" (Parte C): progreso por CICLO de facturación ── */}
                {progreso && (progreso.ciclo || (progreso.escalera ?? []).length > 0) && (
                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5"
                        data-testid="mi-ciclo-referidos">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                            <div>
                                <h2 className="text-base font-bold text-gray-900">Tu ciclo de referidos</h2>
                                {progreso.ciclo ? (
                                    <p className="text-sm text-gray-600 mt-1">
                                        Del {fechaLarga(progreso.ciclo.inicio)} al {fechaLarga(progreso.ciclo.fin)}
                                        {' · '}
                                        {progreso.ciclo.dias_restantes === 0
                                            ? 'cierra hoy'
                                            : `quedan ${progreso.ciclo.dias_restantes} días`}
                                    </p>
                                ) : (
                                    <p className="text-sm text-gray-600 mt-1">
                                        {progreso.mensaje || 'Necesitas un plan vigente para que se evalúe tu ciclo.'}
                                    </p>
                                )}
                            </div>
                            {progreso.ciclo && (
                                <span className="rounded-full bg-emerald-50 border border-emerald-200 px-3 py-1 text-[12px] font-bold text-emerald-700">
                                    {progreso.referidos_convertidos}
                                    {progreso.referidos_convertidos === 1 ? ' referido' : ' referidos'}
                                </span>
                            )}
                        </div>

                        {(progreso.escalera ?? []).length > 0 && (
                            <ul className="mt-4 space-y-1.5">
                                {progreso.escalera.map((tramo) => {
                                    const alcanzado = Boolean(progreso.tramo_alcanzado
                                        && progreso.tramo_alcanzado.id === tramo.id);
                                    return (
                                        <li key={tramo.id}
                                            className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm ${alcanzado
                                                ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                                                : 'border-gray-200 text-gray-700'}`}>
                                            <span>
                                                {tramo.umbral_referidos}
                                                {tramo.umbral_referidos === 1 ? ' referido' : ' referidos'}
                                            </span>
                                            <span className="font-semibold">
                                                {alcanzado ? '✅ ' : ''}{tramo.premio_texto}
                                            </span>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}

                        {progreso.ciclo && progreso.siguiente_tramo && (
                            <p className="mt-3 text-sm text-gray-700">
                                Te {progreso.faltan_para_siguiente === 1 ? 'falta' : 'faltan'}{' '}
                                <strong>{progreso.faltan_para_siguiente}</strong>{' '}
                                {progreso.faltan_para_siguiente === 1 ? 'referido' : 'referidos'} para el
                                premio de {progreso.siguiente_tramo.umbral_referidos}
                                {' ('}{progreso.siguiente_tramo.premio_texto}{')'}.
                            </p>
                        )}

                        {progreso.ciclo && !progreso.siguiente_tramo && (
                            <p className="mt-3 text-sm text-emerald-700 font-semibold">
                                ¡Alcanzaste el tramo más alto de la escalera!
                            </p>
                        )}

                        {progreso.premio_pendiente_aplicar && (
                            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
                                Tienes un premio confirmado esperando: se aplicará automáticamente cuando
                                tengas un plan activo.
                            </p>
                        )}
                    </div>
                )}

                {/* Sin código activo no se puede invitar: el backend rechazaría
                    el envío. La tarjeta de arriba ya explica el motivo. */}
                {data?.activo && <InvitarPorCorreo />}

                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-bold text-gray-900">¿Cómo funciona?</h2>
                    <ol className="mt-3 space-y-3 text-sm text-gray-700">
                        <li className="flex gap-3">
                            <span className="shrink-0 w-6 h-6 rounded-full bg-emerald-100 text-emerald-700 text-xs font-bold flex items-center justify-center">1</span>
                            <span>Comparte tu código por WhatsApp o envíale una invitación por correo desde acá.</span>
                        </li>
                        <li className="flex gap-3">
                            <span className="shrink-0 w-6 h-6 rounded-full bg-emerald-100 text-emerald-700 text-xs font-bold flex items-center justify-center">2</span>
                            <span>
                                Tu amigo completa el formulario de la clase de prueba con tu enlace: tu
                                código queda vinculado a su registro y él lo aplica en «Invita y gana»
                                antes de pagar su primer plan.
                            </span>
                        </li>
                        <li className="flex gap-3">
                            <span className="shrink-0 w-6 h-6 rounded-full bg-emerald-100 text-emerald-700 text-xs font-bold flex items-center justify-center">3</span>
                            <span>
                                Cuando el box confirma esa compra, tu amigo recibe su descuento y tú
                                recibes un % de descuento para tu próxima compra.
                            </span>
                        </li>
                    </ol>
                    <p className="text-xs text-gray-500 mt-4">
                        Los porcentajes y la vigencia los define el administrador del box.
                    </p>
                </div>
            </div>
        </Layout>
    );
};

export default InvitaYGana;
