import React, { useState } from 'react';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import InvitarPorCorreo from '../../components/InvitarPorCorreo';
import { useMiCodigoReferido } from '../../hooks/queries';
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
 * "Invita y gana": el alumno ve y comparte su código, y puede invitar a un
 * amigo por CORREO (migración 054). El componente `CampoReferido` ya no vive
 * acá: el código de otra persona se aplica en la compra (`SolicitarPlan`), no
 * en la pantalla del invitador.
 *
 * El código propio lo crea el backend al activarse un plan; si el alumno aún
 * no tiene fila, `GET /referidos/mi-codigo` responde 404 y acá se explica sin
 * romper la pantalla ni el resto de la app.
 */
const InvitaYGana = () => {
    const { data, isPending, isError, error, refetch } = useMiCodigoReferido();
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
                                código queda vinculado a su registro y lo confirma al comprar su primer plan.
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
