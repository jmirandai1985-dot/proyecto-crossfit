import React, { useMemo, useState } from 'react';
import {
    useDespublicarPromocionReferidos, useEliminarPromocionReferidos,
    useGuardarPromocionReferidos, usePromocionesReferidos, SIN_DATOS,
} from '../hooks/queries';
import {
    TIPOS_PREMIO, etiquetaTipoPremio, formatearValorPremio, mensajeDeError,
    validarPromocionReferido,
} from '../utils/referidos';
import { estadoPublicacion } from '../utils/pendientes';
import ModalPublicarPromocion from './ModalPublicarPromocion';

// Chip de la tarjeta del carrusel: "Sin publicar" / "Publicada" / "Publicación
// vencida". El estado lo decide el backend con el aviso vinculado (migración 056)
// y `estadoPublicacion` sólo compara la fecha de fin.
const CLASES_PUBLICACION = {
    sin_publicar: 'border-zinc-700 bg-zinc-800 text-zinc-400',
    vigente: 'border-orange-500/30 bg-orange-500/10 text-orange-300',
    vencida: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
};

const formatearDia = (valor) => {
    const dia = String(valor ?? '').slice(0, 10);
    if (!dia) return '';
    const [anio, mes, fecha] = dia.split('-');
    return `${fecha}/${mes}/${anio}`;
};

const FORM_VACIO = {
    nombre: '',
    umbral_referidos_convertidos: '3',
    tipo_premio: 'mes_gratis',
    valor_premio: '',
    activo: true,
};

const aFormulario = (promocion) => ({
    nombre: promocion.nombre || '',
    umbral_referidos_convertidos: String(promocion.umbral_referidos_convertidos ?? ''),
    tipo_premio: promocion.tipo_premio || 'mes_gratis',
    valor_premio: promocion.valor_premio == null ? '' : String(promocion.valor_premio),
    activo: Boolean(promocion.activo),
});

const claseInput = (conError) => `w-full rounded-xl border bg-zinc-950 px-4 py-3 text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 ${conError
    ? 'border-red-500/60 focus:border-red-400 focus:ring-red-500/20'
    : 'border-zinc-700 focus:border-orange-500 focus:ring-orange-500/20'}`;

/**
 * CRUD de promociones por volumen (Fase 5). El premio se congela al DETECTAR:
 * editar el umbral o el valor después no cambia un premio ya detectado.
 */
const GestionPromocionesReferidos = () => {
    const promocionesQuery = usePromocionesReferidos();
    const guardar = useGuardarPromocionReferidos();
    const eliminar = useEliminarPromocionReferidos();
    const despublicar = useDespublicarPromocionReferidos();

    const [form, setForm] = useState(FORM_VACIO);
    const [editando, setEditando] = useState(null);
    const [errores, setErrores] = useState({});
    const [mensaje, setMensaje] = useState(null);
    const [ocupadoId, setOcupadoId] = useState(null);
    // Promoción que se está publicando/editando en el carrusel (`null` = modal
    // cerrado). Se guarda la fila entera para que el modal abra con su texto.
    const [publicando, setPublicando] = useState(null);

    const promociones = promocionesQuery.data || SIN_DATOS;
    const tipoSeleccionado = useMemo(
        () => TIPOS_PREMIO.find((opcion) => opcion.id === form.tipo_premio),
        [form.tipo_premio],
    );

    const cambiar = (campo) => (evento) => {
        const valor = campo === 'activo' ? evento.target.checked : evento.target.value;
        setForm((previo) => ({ ...previo, [campo]: valor }));
        setErrores((previo) => ({ ...previo, [campo]: '' }));
        setMensaje(null);
    };

    const limpiar = () => {
        setForm(FORM_VACIO);
        setEditando(null);
        setErrores({});
    };

    const editarPromocion = (promocion) => {
        setEditando(promocion);
        setForm(aFormulario(promocion));
        setErrores({});
        setMensaje(null);
    };

    const enviar = async (evento) => {
        evento.preventDefault();
        const validacion = validarPromocionReferido(form);
        if (!validacion.valido) {
            setErrores(validacion.errores);
            setMensaje(null);
            return;
        }

        const accion = editando ? 'Actualizar' : 'Crear';
        if (!window.confirm(`${accion} la promoción "${validacion.payload.nombre}"?`)) return;

        try {
            await guardar.mutateAsync({
                id: editando?.id,
                payload: validacion.payload,
            });
            setMensaje({
                tipo: 'exito',
                texto: editando ? 'Promoción actualizada.' : 'Promoción creada.',
            });
            limpiar();
        } catch (err) {
            console.error('Error guardando la promoción de referidos:', err);
            setMensaje({
                tipo: 'error',
                texto: mensajeDeError(err, 'No pudimos guardar la promoción.'),
            });
        }
    };

    const borrar = async (promocion) => {
        if (!window.confirm(
            `¿Eliminar la promoción "${promocion.nombre}"? Esta acción no se puede deshacer.`,
        )) return;
        setOcupadoId(promocion.id);
        setMensaje(null);
        try {
            await eliminar.mutateAsync(promocion.id);
            if (editando?.id === promocion.id) limpiar();
            setMensaje({ tipo: 'exito', texto: 'Promoción eliminada.' });
        } catch (err) {
            console.error('Error eliminando la promoción:', err);
            setMensaje({
                tipo: 'error',
                texto: mensajeDeError(err, 'No pudimos eliminar la promoción.'),
            });
        } finally {
            setOcupadoId(null);
        }
    };

    // Quitar la tarjeta del carrusel. El backend BORRA el aviso vinculado: si se
    // vuelve a publicar, arranca una tarjeta nueva con la ventana que se elija.
    const quitarDelCarrusel = async (promocion) => {
        if (!window.confirm(
            `¿Quitar "${promocion.nombre}" del carrusel del alumno?\n\n`
            + 'La promoción sigue activa: sólo deja de anunciarse en el Inicio.',
        )) return;
        setOcupadoId(promocion.id);
        setMensaje(null);
        try {
            await despublicar.mutateAsync(promocion.id);
            setMensaje({ tipo: 'exito', texto: 'Tarjeta quitada del carrusel.' });
        } catch (err) {
            console.error('Error despublicando la promoción:', err);
            setMensaje({
                tipo: 'error',
                texto: mensajeDeError(err, 'No pudimos quitar la tarjeta del carrusel.'),
            });
        } finally {
            setOcupadoId(null);
        }
    };

    if (promocionesQuery.isError) {
        return (
            <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-4 text-sm text-red-200">
                <p>⚠️ {mensajeDeError(promocionesQuery.error, 'No pudimos cargar las promociones.')}</p>
                <button type="button" onClick={() => promocionesQuery.refetch()} className="mt-2 font-semibold underline">
                    Reintentar
                </button>
            </div>
        );
    }

    return (
        <div className="space-y-5" data-testid="gestion-promociones-referidos">
            <div>
                <h3 className="text-base font-extrabold text-zinc-100">Promociones por volumen</h3>
                <p className="text-[12.5px] text-zinc-500 mt-1">
                    Define qué gana un alumno cuando convierte N referidos en el mes. El premio
                    se congela al detectar el umbral; la aplicación es manual.
                </p>
            </div>

            <form onSubmit={enviar} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 sm:p-6">
                <div className="flex items-center justify-between gap-3">
                    <h4 className="text-sm font-bold text-zinc-200">
                        {editando ? `Editando: ${editando.nombre}` : 'Nueva promoción'}
                    </h4>
                    {editando && (
                        <button type="button" onClick={limpiar} className="text-xs font-semibold text-zinc-400 hover:text-zinc-200 underline">
                            Cancelar edición
                        </button>
                    )}
                </div>

                <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label htmlFor="promo-nombre" className="block text-sm font-semibold text-zinc-200">
                            Nombre
                        </label>
                        <input
                            id="promo-nombre"
                            type="text"
                            value={form.nombre}
                            onChange={cambiar('nombre')}
                            placeholder="3 referidos = mes gratis"
                            data-testid="promo-nombre"
                            className={`${claseInput(Boolean(errores.nombre))} mt-1.5`}
                        />
                        {errores.nombre && <p role="alert" className="text-xs text-red-400 mt-1.5">{errores.nombre}</p>}
                    </div>

                    <div>
                        <label htmlFor="promo-umbral" className="block text-sm font-semibold text-zinc-200">
                            Referidos convertidos necesarios
                        </label>
                        <input
                            id="promo-umbral"
                            type="text"
                            inputMode="numeric"
                            value={form.umbral_referidos_convertidos}
                            onChange={cambiar('umbral_referidos_convertidos')}
                            data-testid="promo-umbral"
                            className={`${claseInput(Boolean(errores.umbral_referidos_convertidos))} mt-1.5`}
                        />
                        {errores.umbral_referidos_convertidos && (
                            <p role="alert" className="text-xs text-red-400 mt-1.5">{errores.umbral_referidos_convertidos}</p>
                        )}
                    </div>

                    <div>
                        <label htmlFor="promo-tipo" className="block text-sm font-semibold text-zinc-200">
                            Premio
                        </label>
                        <select
                            id="promo-tipo"
                            value={form.tipo_premio}
                            onChange={cambiar('tipo_premio')}
                            data-testid="promo-tipo"
                            className={`${claseInput(Boolean(errores.tipo_premio))} mt-1.5`}
                        >
                            {TIPOS_PREMIO.map((opcion) => (
                                <option key={opcion.id} value={opcion.id}>{opcion.label}</option>
                            ))}
                        </select>
                        {tipoSeleccionado && (
                            <p className="text-xs text-zinc-500 mt-1.5">{tipoSeleccionado.ayuda}</p>
                        )}
                        {errores.tipo_premio && <p role="alert" className="text-xs text-red-400 mt-1.5">{errores.tipo_premio}</p>}
                    </div>

                    <div>
                        <label htmlFor="promo-valor" className="block text-sm font-semibold text-zinc-200">
                            Valor del premio {tipoSeleccionado?.unidad ? `(${tipoSeleccionado.unidad})` : ''}
                        </label>
                        <input
                            id="promo-valor"
                            type="text"
                            inputMode="decimal"
                            value={form.valor_premio}
                            onChange={cambiar('valor_premio')}
                            disabled={!tipoSeleccionado?.pideValor}
                            placeholder={tipoSeleccionado?.pideValor ? 'Ej. 7' : 'No aplica'}
                            data-testid="promo-valor"
                            className={`${claseInput(Boolean(errores.valor_premio))} mt-1.5 disabled:opacity-50`}
                        />
                        {errores.valor_premio && <p role="alert" className="text-xs text-red-400 mt-1.5">{errores.valor_premio}</p>}
                        {tipoSeleccionado?.pideValor && (
                            <p className="text-xs text-zinc-500 mt-1.5">
                                Vista rápida: {formatearValorPremio(form.tipo_premio, form.valor_premio)}
                            </p>
                        )}
                    </div>
                </div>

                <label className="mt-4 inline-flex items-center gap-2 rounded-full border border-zinc-700 bg-zinc-950 px-3.5 py-2 text-sm font-semibold text-zinc-200 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={form.activo}
                        onChange={cambiar('activo')}
                        data-testid="promo-activo"
                        className="h-4 w-4 accent-orange-500"
                    />
                    Promoción activa
                </label>

                {mensaje && (
                    <div
                        role="status"
                        className={`mt-4 rounded-xl border px-4 py-3 text-sm font-medium ${mensaje.tipo === 'exito'
                            ? 'border-green-500/30 bg-green-500/10 text-green-300'
                            : 'border-red-500/40 bg-red-500/10 text-red-200'}`}
                    >
                        {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                    </div>
                )}

                <div className="mt-4 flex justify-end">
                    <button
                        type="submit"
                        disabled={guardar.isPending}
                        data-testid="btn-guardar-promocion"
                        className="rounded-xl bg-orange-500 hover:bg-orange-600 disabled:bg-orange-500/50 disabled:cursor-not-allowed px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-orange-500/25 transition-colors"
                    >
                        {guardar.isPending ? 'Guardando…' : (editando ? 'Guardar cambios' : 'Crear promoción')}
                    </button>
                </div>
            </form>

            {promocionesQuery.isPending ? (
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 flex justify-center">
                    <div className="animate-spin rounded-full h-7 w-7 border-4 border-orange-500 border-t-transparent"></div>
                </div>
            ) : promociones.length === 0 ? (
                <p className="rounded-2xl border border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
                    Todavía no hay promociones. Crea la primera arriba: mientras no exista una
                    promoción activa, el job diario no detecta ningún umbral.
                </p>
            ) : (
                <div className="overflow-x-auto rounded-2xl border border-zinc-800 bg-zinc-900">
                    <table className="w-full min-w-[900px] text-sm">
                        <thead className="bg-zinc-950/70 text-[11px] uppercase tracking-wide text-zinc-500">
                            <tr>
                                <th className="px-4 py-3 text-left">Promoción</th>
                                <th className="px-4 py-3 text-left">Umbral</th>
                                <th className="px-4 py-3 text-left">Premio</th>
                                <th className="px-4 py-3 text-left">Estado</th>
                                <th className="px-4 py-3 text-left">Carrusel</th>
                                <th className="px-4 py-3 text-right">Acciones</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800">
                            {promociones.map((promocion) => (
                                <tr key={promocion.id} data-testid={`promocion-${promocion.id}`}>
                                    <td className="px-4 py-3">
                                        <p className="font-semibold text-zinc-100">{promocion.nombre}</p>
                                        <p className="text-xs text-zinc-500">{etiquetaTipoPremio(promocion.tipo_premio)}</p>
                                    </td>
                                    <td className="px-4 py-3 text-zinc-300">
                                        {promocion.umbral_referidos_convertidos} referidos / mes
                                    </td>
                                    <td className="px-4 py-3 text-zinc-300">{promocion.premio_texto}</td>
                                    <td className="px-4 py-3">
                                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${promocion.activo
                                            ? 'border-green-500/30 bg-green-500/10 text-green-300'
                                            : 'border-zinc-700 bg-zinc-800 text-zinc-400'}`}>
                                            {promocion.activo ? 'Activa' : 'Apagada'}
                                        </span>
                                        {promocion.detecciones_pendientes > 0 && (
                                            <p className="mt-1 text-[11px] font-semibold text-amber-300">
                                                {promocion.detecciones_pendientes} pendiente(s) de confirmar
                                            </p>
                                        )}
                                    </td>
                                    <td className="px-4 py-3">
                                        <span
                                            data-testid={`promocion-${promocion.id}-carrusel`}
                                            className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${CLASES_PUBLICACION[estadoPublicacion(promocion).clave]}`}
                                        >
                                            {estadoPublicacion(promocion).texto}
                                        </span>
                                        {promocion.publicada && promocion.publicada_hasta && (
                                            <p className="mt-1 text-[11px] text-zinc-500">
                                                Hasta el {formatearDia(promocion.publicada_hasta)}
                                            </p>
                                        )}
                                        <div className="mt-2 flex flex-wrap gap-1.5">
                                            <button
                                                type="button"
                                                onClick={() => setPublicando(promocion)}
                                                disabled={!promocion.activo || ocupadoId === promocion.id}
                                                title={promocion.activo
                                                    ? 'La tarjeta se muestra en el Inicio del alumno'
                                                    : 'Activa la promoción para poder publicarla'}
                                                className="rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1.5 text-[11px] font-bold text-zinc-200 hover:border-orange-500 hover:text-orange-300 disabled:opacity-40"
                                            >
                                                {promocion.publicada ? 'Editar tarjeta' : 'Publicar'}
                                            </button>
                                            {promocion.publicada && (
                                                <button
                                                    type="button"
                                                    onClick={() => quitarDelCarrusel(promocion)}
                                                    disabled={ocupadoId === promocion.id}
                                                    className="rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1.5 text-[11px] font-bold text-zinc-400 hover:border-red-500 hover:text-red-400 disabled:opacity-50"
                                                >
                                                    Quitar
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="flex justify-end gap-2">
                                            <button
                                                type="button"
                                                onClick={() => editarPromocion(promocion)}
                                                className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-xs font-bold text-zinc-200 hover:border-orange-500 hover:text-orange-300"
                                            >
                                                Editar
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => borrar(promocion)}
                                                disabled={ocupadoId === promocion.id}
                                                className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-xs font-bold text-zinc-400 hover:border-red-500 hover:text-red-400 disabled:opacity-50"
                                            >
                                                {ocupadoId === promocion.id ? '…' : 'Eliminar'}
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <ModalPublicarPromocion
                isOpen={Boolean(publicando)}
                promocion={publicando}
                onClose={() => setPublicando(null)}
                onSuccess={() => setMensaje({
                    tipo: 'exito',
                    texto: publicando?.publicada
                        ? 'Tarjeta actualizada en el carrusel.'
                        : 'Promoción publicada en el carrusel.',
                })}
            />
        </div>
    );
};

export default GestionPromocionesReferidos;
