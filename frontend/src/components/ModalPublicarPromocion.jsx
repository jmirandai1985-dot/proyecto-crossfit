import React, { useEffect, useState } from 'react';
import { usePublicarPromocionReferidos } from '../hooks/queries';
import { mensajeDeError } from '../utils/referidos';
import {
    estadoPublicacion, tarjetaSugerida, validarPublicacion, ventanaPublicacionSugerida,
} from '../utils/pendientes';

const CAMPO = 'w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none';
const ETIQUETA = 'block text-[12px] text-zinc-400 mb-1.5';
const AYUDA = 'text-[11px] text-zinc-500 mt-1';

// El backend serializa `vigente_desde/hasta` como `date` ("2026-11-22"): se corta
// a 10 caracteres por si algún día llega con hora. `<input type="date">` sólo
// acepta ese formato.
const fechaCorta = (valor) => String(valor ?? '').slice(0, 10);

function formularioInicial(promocion) {
    const sugerida = tarjetaSugerida(promocion);
    const ventana = ventanaPublicacionSugerida();
    if (promocion?.publicada) {
        // Republicar EDITA la misma tarjeta (backend): se abre con lo que ya está
        // publicado, no con el texto sugerido, para no pisarlo sin querer.
        return {
            titulo: promocion.publicada_titulo || sugerida.titulo,
            texto: promocion.publicada_texto || sugerida.texto,
            vigente_desde: fechaCorta(promocion.publicada_desde) || ventana.vigente_desde,
            vigente_hasta: fechaCorta(promocion.publicada_hasta) || ventana.vigente_hasta,
            fijado_arriba: Boolean(promocion.publicada_fijado_arriba),
        };
    }
    return { ...sugerida, ...ventana, fijado_arriba: false };
}

/**
 * Publica una promoción de referidos en "Novedades del box" del Inicio del alumno.
 *
 * La tarjeta es un `avisos_marketing` VINCULADO (`promocion_id`, migración 056):
 * el backend fija `tipo = promocion` y el vínculo, así que acá sólo se edita lo
 * que ve el alumno (título, texto, ventana y si va fijada arriba). Por eso el
 * mismo modal sirve para publicar y para corregir lo ya publicado.
 */
const ModalPublicarPromocion = ({ isOpen, onClose, promocion, onSuccess }) => {
    const publicar = usePublicarPromocionReferidos();
    const [form, setForm] = useState(() => formularioInicial(promocion));
    const [errores, setErrores] = useState([]);
    const [errorEnvio, setErrorEnvio] = useState('');

    useEffect(() => {
        if (!isOpen) return;
        setForm(formularioInicial(promocion));
        setErrores([]);
        setErrorEnvio('');
    }, [isOpen, promocion]);

    if (!isOpen) return null;

    const yaPublicada = Boolean(promocion?.publicada);
    const estado = estadoPublicacion(promocion);
    const sugerida = tarjetaSugerida(promocion);
    const enviando = publicar.isPending;
    const cambiar = (campo, valor) => setForm((previo) => ({ ...previo, [campo]: valor }));
    const restaurarSugerida = () => setForm((previo) => ({
        ...previo, titulo: sugerida.titulo, texto: sugerida.texto,
    }));

    const enviar = async (evento) => {
        evento.preventDefault();
        const encontrados = validarPublicacion(form);
        setErrores(encontrados);
        setErrorEnvio('');
        if (encontrados.length > 0) return;
        try {
            const resultado = await publicar.mutateAsync({
                promocionId: promocion.id,
                payload: {
                    titulo: form.titulo.trim(),
                    texto: form.texto.trim(),
                    vigente_desde: form.vigente_desde,
                    vigente_hasta: form.vigente_hasta,
                    fijado_arriba: Boolean(form.fijado_arriba),
                },
            });
            if (onSuccess) onSuccess(resultado);
            onClose();
        } catch (error) {
            console.error('Error publicando la promoción:', error);
            setErrorEnvio(mensajeDeError(error, 'No pudimos publicar la promoción en el carrusel.'));
        }
    };


    return (
        <div className="fixed inset-0 bg-black/60 flex items-start sm:items-center justify-center z-50 p-4 overflow-y-auto">
            <div className="w-full max-w-lg my-6 rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl">
                {/* ── Encabezado ── */}
                <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-zinc-800">
                    <div>
                        <h2 className="text-lg font-extrabold text-zinc-100">
                            {yaPublicada ? 'Editar tarjeta publicada' : 'Publicar en el carrusel'}
                        </h2>
                        <p className="text-[12px] text-zinc-500 mt-0.5">
                            Sale en "Novedades del box" del Inicio del alumno y la toca para ir a Invita y gana.
                        </p>
                    </div>
                    <button
                        type="button" onClick={onClose} aria-label="Cerrar"
                        className="w-8 h-8 rounded-lg border border-zinc-800 text-zinc-400 hover:text-zinc-100 hover:border-zinc-700"
                    >
                        ✕
                    </button>
                </div>

                <form onSubmit={enviar} className="p-5 space-y-4">
                    {/* ── Contexto: qué promoción anuncia la tarjeta ── */}
                    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-3.5 py-3">
                        <p className="text-sm font-bold text-zinc-100">
                            {promocion?.nombre || 'Promoción de referidos'}
                        </p>
                        <p className="text-[12px] text-zinc-400 mt-1">
                            {promocion?.premio_texto || 'Premio sin configurar'}
                            {promocion?.umbral_referidos_convertidos
                                ? ` · se gana con ${promocion.umbral_referidos_convertidos} referidos convertidos`
                                : ''}
                        </p>
                        <p className="text-[11px] text-zinc-500 mt-1">
                            Esta tarjeta no configura el premio: eso se edita en la misma fila de la promoción.
                        </p>
                    </div>

                    {errorEnvio && (
                        <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2.5 text-[12.5px] text-red-200">
                            ⚠️ {errorEnvio}
                        </div>
                    )}
                    {errores.length > 0 && (
                        <ul className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2.5 text-[12.5px] text-red-200 space-y-1">
                            {errores.map((mensaje) => <li key={mensaje}>• {mensaje}</li>)}
                        </ul>
                    )}

                    {/* ── Título ── */}
                    <div>
                        <div className="flex items-baseline justify-between gap-2">
                            <label htmlFor="promo-titulo" className={ETIQUETA}>Título de la tarjeta</label>
                            <span className="text-[11px] text-zinc-600">{form.titulo.length}/150</span>
                        </div>
                        <input
                            id="promo-titulo" type="text" value={form.titulo} maxLength={150}
                            onChange={(e) => cambiar('titulo', e.target.value)}
                            placeholder="Ej: Invita y gana un mes gratis"
                            className={CAMPO}
                        />
                    </div>

                    {/* ── Texto ── */}
                    <div>
                        <div className="flex items-baseline justify-between gap-2">
                            <label htmlFor="promo-texto" className={ETIQUETA}>Texto</label>
                            <span className="text-[11px] text-zinc-600">{form.texto.length}/1000</span>
                        </div>
                        <textarea
                            id="promo-texto" rows={4} value={form.texto} maxLength={1000}
                            onChange={(e) => cambiar('texto', e.target.value)}
                            placeholder="Contale al alumno qué gana y con cuántos referidos."
                            className={`${CAMPO} resize-y`}
                        />
                        <div className="flex items-center justify-between gap-2 mt-1">
                            <p className={AYUDA}>El premio y el umbral los toma de la promoción; editalos ahí si cambian.</p>
                            <button
                                type="button" onClick={restaurarSugerida}
                                className="shrink-0 text-[11px] font-semibold text-zinc-400 hover:text-orange-400 underline"
                            >
                                Usar texto sugerido
                            </button>
                        </div>
                    </div>

                    {/* ── Ventana de publicación ── */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label htmlFor="promo-desde" className={ETIQUETA}>Se muestra desde</label>
                            <input
                                id="promo-desde" type="date" value={form.vigente_desde}
                                onChange={(e) => cambiar('vigente_desde', e.target.value)}
                                className={CAMPO}
                            />
                        </div>
                        <div>
                            <label htmlFor="promo-hasta" className={ETIQUETA}>Hasta</label>
                            <input
                                id="promo-hasta" type="date" value={form.vigente_hasta}
                                onChange={(e) => cambiar('vigente_hasta', e.target.value)}
                                className={CAMPO}
                            />
                        </div>
                    </div>

                    <label className="flex items-start gap-2.5 rounded-xl border border-zinc-800 bg-zinc-900/40 px-3 py-2.5 cursor-pointer">
                        <input
                            type="checkbox" checked={Boolean(form.fijado_arriba)}
                            onChange={(e) => cambiar('fijado_arriba', e.target.checked)}
                            className="mt-0.5 h-4 w-4 accent-orange-500"
                        />
                        <span className="text-[12.5px] text-zinc-300">
                            Fijar arriba del carrusel
                            <span className="block text-[11px] text-zinc-500 mt-0.5">
                                Queda primero en "Novedades del box", por encima de los otros avisos.
                            </span>
                        </span>
                    </label>

                    {yaPublicada && (
                        <p className={AYUDA}>
                            Estado actual: <span className="text-zinc-300 font-semibold">{estado.texto}</span>.
                            {' '}Guardar cambios EDITA esta misma tarjeta: conserva su flyer y su fecha de creación.
                        </p>
                    )}

                    {/* ── Acciones ── */}
                    <div className="flex flex-wrap justify-end gap-2 pt-1">
                        <button
                            type="button" onClick={onClose} disabled={enviando}
                            className="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-xs font-bold text-zinc-300 hover:border-zinc-600 disabled:opacity-50"
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit" disabled={enviando}
                            className="rounded-lg bg-orange-500 px-4 py-2 text-xs font-bold text-white hover:bg-orange-600 disabled:bg-orange-500/50"
                        >
                            {enviando
                                ? 'Guardando…'
                                : yaPublicada ? 'Guardar cambios' : 'Publicar en el carrusel'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ModalPublicarPromocion;
