import React, { useEffect, useState } from 'react';
import { useGuardarAvisoMarketing, useQuitarFlyerAviso } from '../hooks/queries';
import IconoTipoAviso from './IconoTipoAviso';
import { CLASES_CAPA } from '../utils/capas';
import { urlArchivo } from '../utils/imagen';
import {
    TIPOS_EDITABLES, avisoVacio, aFormulario, validarAviso,
    hayErrores, construirFormData, payloadEdicion, mensajeDeError, tinteDeAcento,
} from '../utils/avisosMarketing';

const CAMPO = 'w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none';
const ETIQUETA = 'block text-[12px] text-zinc-400 mb-1.5';
const ERROR = 'text-[11.5px] text-red-400 mt-1';

const ModalAvisoMarketing = ({ isOpen, onClose, onSuccess, avisoEditar }) => {
    const esEdicion = !!avisoEditar;
    const guardar = useGuardarAvisoMarketing();
    const quitarFlyer = useQuitarFlyerAviso();
    const [form, setForm] = useState(avisoVacio());
    const [errores, setErrores] = useState({});
    const [flyer, setFlyer] = useState(null);
    const [preview, setPreview] = useState(null);
    // "Quitar imagen" en edición: marca que el flyer actual se borre. Se resetea
    // cada vez que el modal se abre (igual que en el modal de productos).
    const [borrarFlyer, setBorrarFlyer] = useState(false);

    useEffect(() => {
        if (!isOpen) return;
        // `avisoEditar` (y no un booleano derivado) para que el efecto se rearme
        // cuando el aviso cambia: el modal se reusa entre editar y crear.
        setForm(avisoEditar ? aFormulario(avisoEditar) : avisoVacio());
        setErrores({});
        setFlyer(null);
        setPreview(null);
        setBorrarFlyer(false);
    }, [isOpen, avisoEditar]);

    const cambiar = (campo, valor) => {
        setForm((previo) => ({ ...previo, [campo]: valor }));
    };

    const elegirFlyer = (evento) => {
        const archivo = evento.target.files?.[0];
        if (!archivo) {
            setFlyer(null);
            setPreview(null);
            return;
        }
        setFlyer(archivo);
        setBorrarFlyer(false);
        const lector = new FileReader();
        lector.onloadend = () => setPreview(lector.result);
        lector.readAsDataURL(archivo);
    };

    const enviar = async (evento) => {
        evento.preventDefault();
        const encontrados = validarAviso(form);
        setErrores(encontrados);
        if (hayErrores(encontrados)) return;

        try {
            if (esEdicion) {
                // El PUT es JSON y reemplaza los campos; el flyer viaja aparte.
                await guardar.mutateAsync({
                    id: avisoEditar.id,
                    payload: payloadEdicion(form),
                    imagen: flyer,
                });
                if (borrarFlyer && !flyer && avisoEditar.imagen_url) {
                    await quitarFlyer.mutateAsync(avisoEditar.id);
                }
            } else {
                await guardar.mutateAsync({ formData: construirFormData(form, flyer) });
            }
            if (onSuccess) onSuccess();
            onClose();
        } catch (error) {
            console.error('Error guardando aviso:', error);
            setErrores({ submit: mensajeDeError(error) });
        }
    };

    if (!isOpen) return null;

    return (
        <div className={`fixed inset-0 bg-black/60 flex items-start sm:items-center justify-center p-4 overflow-y-auto ${CLASES_CAPA.modalAviso}`}>
            <div className="w-full max-w-lg my-6 rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl">
                {/* ── Encabezado ── */}
                <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-zinc-800">
                    <div>
                        <h2 className="text-lg font-extrabold text-zinc-100">
                            {esEdicion ? 'Editar aviso' : 'Nuevo aviso'}
                        </h2>
                        <p className="text-[12px] text-zinc-500 mt-0.5">
                            Se muestra en el carrusel "Novedades del box" del Inicio del alumno.
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

                    {/* ── Tipo: la tarjeta toma automáticamente su color ── */}
                    <div>
                        <span className={ETIQUETA}>Tipo de aviso</span>
                        <div className="flex flex-wrap gap-2">
                            {TIPOS_EDITABLES.map((tipo) => {
                                const activo = form.tipo === tipo.id;
                                return (
                                    <button
                                        key={tipo.id}
                                        type="button"
                                        onClick={() => cambiar('tipo', tipo.id)}
                                        style={activo
                                            ? { borderColor: tipo.acento, backgroundColor: tinteDeAcento(tipo.acento) }
                                            : undefined}
                                        className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border-2 text-[12.5px] font-semibold transition-colors ${activo
                                            ? 'text-white'
                                            : 'border-zinc-800 bg-zinc-900 text-zinc-400 hover:text-zinc-200'}`}
                                        aria-pressed={activo}
                                    >
                                        <span style={{ color: activo ? '#fff' : tipo.acento }}>
                                            <IconoTipoAviso tipo={tipo.id} />
                                        </span>
                                        {tipo.label}
                                    </button>
                                );
                            })}
                        </div>
                        {errores.tipo && <p className={ERROR}>{errores.tipo}</p>}
                    </div>

                    {/* ── Título y texto ── */}
                    <label className="block">
                        <span className={ETIQUETA}>Título</span>
                        <input
                            type="text" value={form.titulo} maxLength={160}
                            onChange={(e) => cambiar('titulo', e.target.value)}
                            placeholder="Trae un amigo este mes" className={CAMPO}
                        />
                        {errores.titulo && <p className={ERROR}>{errores.titulo}</p>}
                    </label>

                    <label className="block">
                        <span className={ETIQUETA}>Texto</span>
                        <textarea
                            rows={3} value={form.texto}
                            onChange={(e) => cambiar('texto', e.target.value)}
                            placeholder="Tú y tu invitado reciben 20% de descuento en su primera clase juntos."
                            className={CAMPO}
                        />
                        {errores.texto && <p className={ERROR}>{errores.texto}</p>}
                    </label>

                    {/* ── Campos que dependen del tipo (el mockup los muestra así) ── */}
                    {form.tipo === 'colaboracion' && (
                        <label className="block">
                            <span className={ETIQUETA}>Nombre del aliado</span>
                            <input
                                type="text" value={form.nombre_aliado} maxLength={150}
                                onChange={(e) => cambiar('nombre_aliado', e.target.value)}
                                placeholder="NUTRI MAIPÚ" className={CAMPO}
                            />
                            {errores.nombre_aliado && <p className={ERROR}>{errores.nombre_aliado}</p>}
                        </label>
                    )}

                    {form.tipo === 'evento' && (
                        <label className="block">
                            <span className={ETIQUETA}>Fecha del evento</span>
                            <input
                                type="date" value={form.fecha_evento}
                                onChange={(e) => cambiar('fecha_evento', e.target.value)}
                                className={CAMPO}
                            />
                            {errores.fecha_evento && <p className={ERROR}>{errores.fecha_evento}</p>}
                        </label>
                    )}

                    {/* ── Flyer opcional ── */}
                    <div>
                        <span className={ETIQUETA}>Imagen / flyer (opcional)</span>
                        <label className="block border-2 border-dashed border-zinc-800 rounded-lg px-4 py-3.5 text-center text-[12px] text-zinc-500 hover:border-zinc-700 cursor-pointer">
                            {flyer || (esEdicion && avisoEditar?.imagen_url && !borrarFlyer)
                                ? 'Cambiar imagen (JPG, PNG, WEBP · máx 5 MB)'
                                : '+ Subir imagen — si no subes una, se usa el color del tipo'}
                            <input
                                type="file" accept="image/png,image/jpeg,image/webp,image/gif"
                                onChange={elegirFlyer} className="hidden"
                            />
                        </label>
                        {(preview || (esEdicion && avisoEditar?.imagen_url && !borrarFlyer)) && (
                            <div className="mt-2 flex items-center gap-3">
                                <img
                                    src={preview || urlArchivo(avisoEditar.imagen_url)}
                                    alt="Flyer del aviso"
                                    className="h-20 w-20 object-cover rounded-lg border border-zinc-800"
                                />
                                <button
                                    type="button"
                                    onClick={() => { setFlyer(null); setPreview(null); setBorrarFlyer(true); }}
                                    className="text-[12px] text-red-400 hover:text-red-300 underline"
                                >
                                    Quitar imagen
                                </button>
                            </div>
                        )}
                    </div>

                    {/* ── Vigencia: SIEMPRE obligatoria (dos días de calendario) ── */}
                    <div>
                        <div className="flex gap-3">
                            <label className="flex-1 block">
                                <span className={ETIQUETA}>Vigente desde</span>
                                <input
                                    type="date" value={form.vigente_desde}
                                    onChange={(e) => cambiar('vigente_desde', e.target.value)}
                                    className={CAMPO}
                                />
                            </label>
                            <label className="flex-1 block">
                                <span className={ETIQUETA}>Vigente hasta</span>
                                <input
                                    type="date" value={form.vigente_hasta}
                                    onChange={(e) => cambiar('vigente_hasta', e.target.value)}
                                    className={CAMPO}
                                />
                            </label>
                        </div>
                        <p className="text-[11.5px] text-zinc-600 mt-1">
                            El último día se muestra completo. Fuera de esta ventana el aviso no
                            aparece en el Inicio del alumno.
                        </p>
                        {errores.vigencia && <p className={ERROR}>{errores.vigencia}</p>}
                    </div>

                    <label className="flex items-center gap-2.5 text-[12.5px] text-zinc-300">
                        <input
                            type="checkbox" checked={form.fijado_arriba}
                            onChange={(e) => cambiar('fijado_arriba', e.target.checked)}
                            className="w-4 h-4 rounded accent-orange-500"
                        />
                        Fijar arriba del carrusel
                    </label>

                    <div className="flex gap-3 pt-1">
                        <button
                            type="button" onClick={onClose} disabled={guardar.isPending}
                            className="flex-1 px-4 py-2.5 rounded-xl border border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-sm font-semibold disabled:opacity-50"
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit" disabled={guardar.isPending}
                            className="flex-1 px-4 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-bold disabled:opacity-50"
                        >
                            {guardar.isPending
                                ? 'Guardando...'
                                : (esEdicion ? 'Guardar cambios' : 'Crear aviso')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ModalAvisoMarketing;