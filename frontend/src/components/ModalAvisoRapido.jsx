import React, { useEffect, useState } from 'react';
import { usePublicarAvisoRapido } from '../hooks/queries';
import {
    MAX_TEXTO_RAPIDO, avisoRapidoVacio, formatearFechaCorta, hayErrores, hoyISO,
    mensajeDeError, payloadAvisoRapido, tipoDe, tituloRapidoDeTexto,
    validarAvisoRapido,
} from '../utils/avisosMarketing';

const CAMPO = 'w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-amber-500 focus:outline-none';
const ETIQUETA = 'block text-[12px] text-zinc-400 mb-1.5';
const ERROR = 'text-[11.5px] text-red-400 mt-1';

// El aviso rápido del COACH (Gestión de Clases): UNA caja de texto y listo. El tipo
// (`aviso`), la ventana (HOY, día de Chile) y el título los fija el backend
// (`app/services/avisos_marketing.py: payload_aviso_rapido`), así que este modal no
// ofrece tipo, vigencia ni flyer — y no es un olvido: con esos campos a la vista, un
// coach podría publicar una Promoción de un mes o un Evento, que son del admin.
//
// El tope del mensaje y la vista previa salen de `utils/avisosMarketing.js`, la MISMA
// definición que usan el panel de Marketing y el carrusel del alumno.
const ModalAvisoRapido = ({ isOpen, onClose, onSuccess }) => {
    const publicar = usePublicarAvisoRapido();
    const [form, setForm] = useState(avisoRapidoVacio());
    const [errores, setErrores] = useState({});

    useEffect(() => {
        if (!isOpen) return;
        // Se vacía en cada apertura: el aviso es un mensaje NUEVO del día (el backend
        // no permite editar avisos desde acá; publicar dos veces son dos avisos).
        setForm(avisoRapidoVacio());
        setErrores({});
    }, [isOpen]);

    const enviar = async (evento) => {
        evento.preventDefault();
        const encontrados = validarAvisoRapido(form);
        setErrores(encontrados);
        if (hayErrores(encontrados)) return;

        try {
            const aviso = await publicar.mutateAsync(payloadAvisoRapido(form));
            if (onSuccess) onSuccess(aviso);
            onClose();
        } catch (error) {
            console.error('Error publicando el aviso rápido:', error);
            setErrores({ submit: mensajeDeError(error, 'No se pudo publicar el aviso.') });
        }
    };

    if (!isOpen) return null;

    const tipo = tipoDe('aviso');
    const mensaje = form.texto.trim();
    const titulo = tituloRapidoDeTexto(form.texto);

    return (
        <div className="fixed inset-0 bg-black/60 flex items-start sm:items-center justify-center z-50 p-4 overflow-y-auto">
            <div className="w-full max-w-lg my-6 rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl">
                {/* ── Encabezado ── */}
                <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-zinc-800">
                    <div>
                        <h2 className="text-lg font-extrabold text-zinc-100">Aviso rápido</h2>
                        <p className="text-[12px] text-zinc-500 mt-0.5">
                            Aparece hoy en el Inicio de los alumnos.
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
                    {errores.submit && (
                        <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2.5 text-[12.5px] text-red-200">
                            ⚠️ {errores.submit}
                        </div>
                    )}

                    <label className="block">
                        <span className={ETIQUETA}>Mensaje</span>
                        <textarea
                            rows={3}
                            data-testid="aviso-rapido-texto"
                            value={form.texto}
                            maxLength={MAX_TEXTO_RAPIDO}
                            onChange={(e) => setForm({ texto: e.target.value })}
                            placeholder='Ej. "Trae calcetas, hoy hay cuerda"'
                            className={CAMPO}
                        />
                        <span className="block text-[11.5px] text-zinc-600 mt-1">
                            {mensaje.length}/{MAX_TEXTO_RAPIDO} · el título de la tarjeta sale
                            de la primera frase.
                        </span>
                        {errores.texto && <p className={ERROR}>{errores.texto}</p>}
                    </label>

                    {/* ── Cómo se verá en el carrusel del alumno: mismos colores del
                           tipo `aviso` que usan el panel Marketing y el Inicio ── */}
                    <div>
                        <span className={ETIQUETA}>Así lo verán</span>
                        <div
                            className="rounded-xl border p-3"
                            style={{ background: tipo.fondo, borderColor: tipo.acento }}
                            data-testid="aviso-rapido-preview"
                        >
                            <span
                                className="inline-block px-2 py-0.5 rounded text-[10px] font-bold"
                                style={{ background: tipo.tagFondo, color: tipo.tagTexto }}
                            >
                                {tipo.tag}
                            </span>
                            <div className="mt-2 text-[13px] font-bold" style={{ color: tipo.titulo }}>
                                {titulo || 'Aviso del box'}
                            </div>
                            <div className="mt-0.5 text-[11.5px]" style={{ color: tipo.detalle }}>
                                {mensaje || 'Así se verá tu mensaje en el Inicio de los alumnos.'}
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-[11.5px] text-zinc-400">
                        <span aria-hidden="true">🕐</span>
                        Vigente solo hoy ({formatearFechaCorta(hoyISO())}). Mañana desaparece solo.
                    </div>

                    <div className="flex gap-3 pt-1">
                        <button
                            type="button" onClick={onClose} disabled={publicar.isPending}
                            className="flex-1 px-4 py-2.5 rounded-xl border border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-sm font-semibold disabled:opacity-50"
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit" disabled={publicar.isPending}
                            data-testid="publicar-aviso-rapido"
                            className="flex-1 px-4 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-600 text-zinc-900 text-sm font-bold disabled:opacity-50"
                        >
                            {publicar.isPending ? 'Publicando...' : 'Publicar aviso'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ModalAvisoRapido;
