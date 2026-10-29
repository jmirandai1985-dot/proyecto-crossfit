import React, { useMemo, useState } from 'react';
import {
    useCambiarMotorPremios,
    useDespublicarEscaleraTramos,
    useEliminarTramoReferido,
    useGuardarTramoReferido,
    usePublicarEscaleraTramos,
    useTramosReferidos,
} from '../hooks/queries';
import {
    formatearValorPremio, mensajeDeError, TIPOS_PREMIO, validarPromocionReferido,
} from '../utils/referidos';
import { ventanaPublicacionSugerida, validarPublicacion } from '../utils/pendientes';

const CAMPO = 'w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none';
const ETIQUETA = 'block text-[12px] text-zinc-400 mb-1.5';
const AYUDA = 'text-[11px] text-zinc-500 mt-1';
const BOTON = 'rounded-xl px-4 py-2 text-sm font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
const ERROR = 'text-[11px] text-red-400 mt-1';

const FORM_VACIO = {
    umbral_referidos_convertidos: '',
    tipo_premio: 'descuento_extra',
    valor_premio: '',
    activo: true,
};

const fechaCorta = (valor) => String(valor ?? '').slice(0, 10);

/**
 * "Tramos del invitador" (Parte C) — Marketing → Referidos.
 *
 * La escalera se evalúa al CIERRE DEL CICLO de facturación del alumno y paga UN
 * solo premio (el escalón más alto alcanzado). El backend congela el premio en
 * cada ciclo detectado, así que cambiar un escalón NO reescribe premios ganados.
 *
 * El selector de motor es el interruptor de negocio: con `promociones` sigue
 * pagando la Fase 5 por mes calendario; con `tramos`, la escalera. Los dos
 * motores NO conviven (el backend se salta el box que no le toca).
 */
const GestionTramosReferidos = () => {
    const { data, isPending, isError, error } = useTramosReferidos();
    const guardar = useGuardarTramoReferido();
    const eliminar = useEliminarTramoReferido();
    const cambiarMotor = useCambiarMotorPremios();
    const publicar = usePublicarEscaleraTramos();
    const despublicar = useDespublicarEscaleraTramos();

    const [modal, setModal] = useState(null);       // null | { tramo }
    const [form, setForm] = useState(FORM_VACIO);
    const [errores, setErrores] = useState({});
    const [mensaje, setMensaje] = useState(null);

    const [modalPublicar, setModalPublicar] = useState(false);
    const [formPublicar, setFormPublicar] = useState(() => ({
        titulo: 'Invita y gana', texto: '', ...ventanaPublicacionSugerida(), fijado_arriba: false,
    }));
    const [erroresPublicar, setErroresPublicar] = useState([]);

    const tramos = data?.tramos ?? [];
    const escalera = data?.escalera ?? [];
    const motor = data?.motor ?? 'promociones';
    const activos = useMemo(() => tramos.filter((tramo) => tramo.activo), [tramos]);
    const advertencias = data?.advertencias ?? [];

    const aviso = (tipo, texto) => setMensaje({ tipo, texto });

    const abrirNuevo = () => {
        const siguiente = (activos.at(-1)?.umbral_referidos ?? 0) + 1;
        setForm({ ...FORM_VACIO, umbral_referidos_convertidos: String(siguiente) });
        setErrores({});
        setModal({ tramo: null });
    };

    const abrirEditar = (tramo) => {
        setForm({
            umbral_referidos_convertidos: String(tramo.umbral_referidos),
            tipo_premio: tramo.tipo_premio,
            valor_premio: tramo.valor_premio ?? '',
            activo: Boolean(tramo.activo),
        });
        setErrores({});
        setModal({ tramo });
    };

    const cerrarModal = () => {
        if (guardar.isPending) return;
        setModal(null);
        setErrores({});
    };

    /**
     * Reusa `validarPromocionReferido` (la MISMA validación de la Fase 5) con un
     * nombre sintético: acá el escalón no tiene nombre, lo identifica el umbral.
     * Así el cliente y el backend no pueden discrepar en el valor del premio.
     */
    const validar = (valores) => {
        const resultado = validarPromocionReferido({
            nombre: `Escalón ${valores.umbral_referidos_convertidos || ''}`.trim(),
            umbral_referidos_convertidos: valores.umbral_referidos_convertidos,
            tipo_premio: valores.tipo_premio,
            valor_premio: valores.valor_premio,
            activo: valores.activo,
        });
        if (!resultado.valido) return { valido: false, errores: resultado.errores };
        return {
            valido: true,
            errores: {},
            payload: {
                umbral_referidos: resultado.payload.umbral_referidos_convertidos,
                tipo_premio: resultado.payload.tipo_premio,
                valor_premio: resultado.payload.valor_premio,
                activo: resultado.payload.activo,
            },
        };
    };

    const enviar = async (evento) => {
        evento.preventDefault();
        const resultado = validar(form);
        if (!resultado.valido) {
            setErrores(resultado.errores);
            return;
        }
        try {
            await guardar.mutateAsync({ id: modal?.tramo?.id, payload: resultado.payload });
            aviso('exito', modal?.tramo ? 'Tramo actualizado.' : 'Tramo agregado a la escalera.');
            setModal(null);
        } catch (err) {
            aviso('error', mensajeDeError(err, 'No pudimos guardar el tramo.'));
        }
    };

    const borrar = async (tramo) => {
        if (!window.confirm(`¿Borrar el tramo de ${tramo.umbral_referidos} referidos?`)) return;
        try {
            await eliminar.mutateAsync(tramo.id);
            aviso('exito', 'Tramo borrado.');
        } catch (err) {
            aviso('error', mensajeDeError(
                err, 'No pudimos borrar el tramo: si ya generó premios, apágalo.'));
        }
    };

    const cambiar = async (nuevoMotor) => {
        if (nuevoMotor === motor) return;
        const texto = nuevoMotor === 'tramos'
            ? 'El motor de tramos evalúa al cierre del ciclo del alumno y deja de pagar las promociones por mes calendario. ¿Continuar?'
            : 'Volver a promociones por umbral deja de evaluar la escalera de tramos. Los premios ya detectados se conservan. ¿Continuar?';
        if (!window.confirm(texto)) return;
        try {
            await cambiarMotor.mutateAsync(nuevoMotor);
            aviso('exito', nuevoMotor === 'tramos'
                ? 'Motor de tramos activado.'
                : 'Volviste al motor de promociones por umbral.');
        } catch (err) {
            aviso('error', mensajeDeError(err, 'No pudimos cambiar el motor de premios.'));
        }
    };

    const abrirPublicar = () => {
        const ventana = ventanaPublicacionSugerida();
        setFormPublicar({
            titulo: data?.publicada_titulo || 'Invita y gana',
            texto: data?.publicada_texto || '',
            vigente_desde: fechaCorta(data?.publicada_desde) || ventana.vigente_desde,
            vigente_hasta: fechaCorta(data?.publicada_hasta) || ventana.vigente_hasta,
            fijado_arriba: Boolean(data?.publicada_fijado_arriba),
        });
        setErroresPublicar({});
        setModalPublicar(true);
    };

    const enviarPublicacion = async (evento) => {
        evento.preventDefault();
        // `validarPublicacion` devuelve la LISTA de errores (mismas reglas que
        // `PublicarPromocionRequest`): `[]` = se puede enviar.
        const listaErrores = validarPublicacion(formPublicar);
        if (listaErrores.length > 0) {
            setErroresPublicar(listaErrores);
            return;
        }
        try {
            await publicar.mutateAsync({
                titulo: formPublicar.titulo,
                texto: formPublicar.texto,
                vigente_desde: formPublicar.vigente_desde,
                vigente_hasta: formPublicar.vigente_hasta,
                fijado_arriba: Boolean(formPublicar.fijado_arriba),
            });
            aviso('exito', 'Escalera publicada en el carrusel del alumno.');
            setModalPublicar(false);
        } catch (err) {
            aviso('error', mensajeDeError(err, 'No pudimos publicar la escalera.'));
        }
    };

    const quitarPublicacion = async () => {
        if (!window.confirm('¿Quitar la tarjeta de la escalera del carrusel?')) return;
        try {
            await despublicar.mutateAsync();
            aviso('exito', 'La tarjeta salió del carrusel. Los tramos siguen activos.');
        } catch (err) {
            aviso('error', mensajeDeError(err, 'No pudimos despublicar la escalera.'));
        }
    };

    if (isPending) {
        return (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 text-sm text-zinc-400">
                Cargando la escalera de tramos…
            </div>
        );
    }

    if (isError) {
        return (
            <div className="bg-zinc-900 border border-red-500/40 rounded-2xl p-5 text-sm text-red-200">
                {mensajeDeError(error, 'No pudimos cargar la escalera de tramos.')}
            </div>
        );
    }

    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5"
            data-testid="gestion-tramos-referidos">
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                <div>
                    <h2 className="text-lg font-extrabold text-zinc-100">Tramos del invitador</h2>
                    <p className="text-sm text-zinc-400 mt-1">
                        Escalera por <strong>ciclo de facturación</strong> del alumno: al cerrar su plan se paga
                        UN solo premio, el escalón más alto que alcanzó con sus referidos convertidos.
                    </p>
                </div>
                <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={abrirNuevo}
                        data-testid="btn-nuevo-tramo"
                        className={`${BOTON} bg-orange-500 hover:bg-orange-600 text-white`}>
                        + Nuevo tramo
                    </button>
                    {data?.publicada ? (
                        <button type="button" onClick={quitarPublicacion}
                            disabled={despublicar.isPending}
                            className={`${BOTON} border border-zinc-700 text-zinc-300 hover:bg-zinc-800`}>
                            Despublicar
                        </button>
                    ) : (
                        <button type="button" onClick={abrirPublicar}
                            disabled={activos.length === 0}
                            data-testid="btn-publicar-escalera"
                            className={`${BOTON} border border-zinc-700 text-zinc-300 hover:bg-zinc-800`}>
                            Publicar en el carrusel
                        </button>
                    )}
                </div>
            </div>

            {/* ── Selector de motor: el interruptor de negocio ── */}
            <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
                <p className="text-[12px] font-bold text-zinc-300">Motor de premios del invitador</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {[
                        {
                            id: 'promociones',
                            titulo: 'Promociones por umbral',
                            detalle: 'Mes calendario (Fase 5): varias promociones y umbrales acumulables.',
                        },
                        {
                            id: 'tramos',
                            titulo: 'Tramos por ciclo',
                            detalle: 'Ciclo de facturación: un solo premio, el escalón más alto.',
                        },
                    ].map((opcion) => (
                        <button
                            key={opcion.id}
                            type="button"
                            onClick={() => cambiar(opcion.id)}
                            disabled={cambiarMotor.isPending}
                            aria-pressed={motor === opcion.id}
                            className={`rounded-xl border p-3 text-left transition-colors ${motor === opcion.id
                                ? 'border-orange-500/60 bg-orange-500/10'
                                : 'border-zinc-800 hover:border-zinc-700'}`}
                        >
                            <span className="block text-sm font-bold text-zinc-100">
                                {motor === opcion.id ? '● ' : '○ '}{opcion.titulo}
                            </span>
                            <span className="block text-[11px] text-zinc-400 mt-1">{opcion.detalle}</span>
                        </button>
                    ))}
                </div>
                <p className={`${AYUDA} mt-2`}>
                    Sólo un motor evalúa por box: cambiar de motor no reescribe los premios ya detectados.
                </p>
            </div>

            {mensaje && (
                <div role="status" className={`mt-4 rounded-xl border px-4 py-3 text-sm font-medium ${mensaje.tipo === 'exito'
                    ? 'border-green-500/30 bg-green-500/10 text-green-300'
                    : 'border-red-500/40 bg-red-500/10 text-red-200'}`}>
                    {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                </div>
            )}
            {advertencias.length > 0 && (
                <ul className="mt-4 space-y-1">
                    {advertencias.map((texto) => (
                        <li key={texto}
                            className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-200">
                            ⚠️ {texto}
                        </li>
                    ))}
                </ul>
            )}

            <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
                <p className="text-[12px] font-bold text-zinc-300">Vista previa — así lo lee el alumno</p>
                {escalera.length === 0 ? (
                    <p className="mt-2 text-[12px] text-zinc-500">
                        Todavía no hay escalones activos: el alumno no verá ninguna escalera.
                    </p>
                ) : (
                    <ul className="mt-2 flex flex-wrap gap-2">
                        {escalera.map((paso) => (
                            <li key={paso}
                                className="rounded-full border border-orange-500/30 bg-orange-500/10 px-3 py-1 text-[12px] font-semibold text-orange-200">
                                {paso}
                            </li>
                        ))}
                    </ul>
                )}
            </div>

            <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                            <th className="py-2 pr-3">Referidos en el ciclo</th>
                            <th className="py-2 pr-3">Premio</th>
                            <th className="py-2 pr-3">Pendientes</th>
                            <th className="py-2 pr-3">Estado</th>
                            <th className="py-2">Acciones</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tramos.length === 0 && (
                            <tr>
                                <td colSpan={5} className="py-6 text-center text-zinc-500">
                                    La escalera está vacía. Agrega el primer escalón para empezar.
                                </td>
                            </tr>
                        )}
                        {tramos.map((tramo) => (
                            <tr key={tramo.id} data-testid={`tramo-${tramo.id}`}
                                className="border-t border-zinc-800">
                                <td className="py-2.5 pr-3 font-bold text-zinc-100">
                                    {tramo.umbral_referidos}
                                    <span className="ml-1 text-[11px] font-normal text-zinc-500">
                                        {tramo.umbral_referidos === 1 ? 'referido' : 'referidos'}
                                    </span>
                                </td>
                                <td className="py-2.5 pr-3 text-zinc-300">
                                    {tramo.premio_texto
                                        || formatearValorPremio(tramo.tipo_premio, tramo.valor_premio)}
                                </td>
                                <td className="py-2.5 pr-3">
                                    {tramo.premios_pendientes > 0 ? (
                                        <span className="rounded-full bg-orange-500/15 px-2 py-0.5 text-[11px] font-bold text-orange-300">
                                            {tramo.premios_pendientes}
                                        </span>
                                    ) : (
                                        <span className="text-zinc-600">—</span>
                                    )}
                                </td>
                                <td className="py-2.5 pr-3">
                                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${tramo.activo
                                        ? 'bg-green-500/15 text-green-300'
                                        : 'bg-zinc-700/40 text-zinc-400'}`}>
                                        {tramo.activo ? 'Activo' : 'Apagado'}
                                    </span>
                                </td>
                                <td className="py-2.5">
                                    <div className="flex gap-2">
                                        <button type="button" onClick={() => abrirEditar(tramo)}
                                            className="text-[12px] font-bold text-orange-300 hover:text-orange-200">
                                            Editar
                                        </button>
                                        <button type="button" onClick={() => borrar(tramo)}
                                            className="text-[12px] font-bold text-zinc-400 hover:text-red-300">
                                            Borrar
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {/* ── Modal alta/edición de un escalón ── */}
            {modal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
                    role="dialog" aria-modal="true">
                    <form onSubmit={enviar}
                        className="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
                        <h3 className="text-lg font-extrabold text-zinc-100">
                            {modal.tramo ? 'Editar tramo' : 'Nuevo tramo'}
                        </h3>
                        <p className="text-[12px] text-zinc-400 mt-1">
                            El premio se paga al cierre del ciclo del alumno. Un escalón por cantidad de
                            referidos: no puede haber dos premios en el mismo número.
                        </p>

                        <div className="mt-4">
                            <label className={ETIQUETA} htmlFor="tramo-umbral">Referidos convertidos en el ciclo</label>
                            <input
                                id="tramo-umbral"
                                type="number"
                                min="1"
                                step="1"
                                inputMode="numeric"
                                className={CAMPO}
                                value={form.umbral_referidos_convertidos}
                                onChange={(e) => setForm({ ...form, umbral_referidos_convertidos: e.target.value })}
                            />
                            {errores.umbral_referidos_convertidos && (
                                <p className={ERROR}>{errores.umbral_referidos_convertidos}</p>
                            )}
                        </div>

                        <div className="mt-3">
                            <label className={ETIQUETA} htmlFor="tramo-tipo">Premio</label>
                            <select
                                id="tramo-tipo"
                                className={CAMPO}
                                value={form.tipo_premio}
                                onChange={(e) => setForm({ ...form, tipo_premio: e.target.value })}
                            >
                                {TIPOS_PREMIO.map((opcion) => (
                                    <option key={opcion.id} value={opcion.id}>{opcion.label}</option>
                                ))}
                            </select>
                            <p className={AYUDA}>
                                {TIPOS_PREMIO.find((opcion) => opcion.id === form.tipo_premio)?.ayuda}
                            </p>
                            {errores.tipo_premio && <p className={ERROR}>{errores.tipo_premio}</p>}
                        </div>

                        {form.tipo_premio !== 'mes_gratis' && (
                            <div className="mt-3">
                                <label className={ETIQUETA} htmlFor="tramo-valor">
                                    {form.tipo_premio === 'dias_gratis' ? 'Días' : 'Porcentaje'}
                                </label>
                                <input
                                    id="tramo-valor"
                                    type="number"
                                    min="0"
                                    step={form.tipo_premio === 'dias_gratis' ? '1' : '0.01'}
                                    className={CAMPO}
                                    value={form.valor_premio}
                                    onChange={(e) => setForm({ ...form, valor_premio: e.target.value })}
                                />
                                {errores.valor_premio && <p className={ERROR}>{errores.valor_premio}</p>}
                            </div>
                        )}

                        <label className="mt-4 flex items-center gap-2 text-[12px] text-zinc-300">
                            <input
                                type="checkbox"
                                checked={form.activo}
                                onChange={(e) => setForm({ ...form, activo: e.target.checked })}
                            />
                            Tramo activo (los apagados no compiten)
                        </label>

                        <p className={`${AYUDA} mt-3`}>
                            Vista previa: {formatearValorPremio(form.tipo_premio, form.valor_premio)}
                        </p>

                        <div className="mt-5 flex justify-end gap-2">
                            <button type="button" onClick={cerrarModal} disabled={guardar.isPending}
                                className={`${BOTON} border border-zinc-700 text-zinc-300 hover:bg-zinc-800`}>
                                Cancelar
                            </button>
                            <button type="submit" disabled={guardar.isPending}
                                data-testid="btn-guardar-tramo"
                                className={`${BOTON} bg-orange-500 hover:bg-orange-600 text-white`}>
                                {guardar.isPending ? 'Guardando…' : 'Guardar tramo'}
                            </button>
                        </div>
                    </form>
                </div>
            )}
            {/* ── Modal de publicación: la tarjeta anuncia la ESCALERA completa ── */}
            {modalPublicar && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
                    role="dialog" aria-modal="true">
                    <form onSubmit={enviarPublicacion}
                        className="w-full max-w-lg bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
                        <h3 className="text-lg font-extrabold text-zinc-100">Publicar la escalera</h3>
                        <p className="text-[12px] text-zinc-400 mt-1">
                            La tarjeta del carrusel muestra la escalera <strong>completa</strong>: el
                            backend agrega los escalones activos al final del texto, así no puede quedar
                            anunciando una escalera vieja.
                        </p>

                        <div className="mt-4">
                            <label className={ETIQUETA} htmlFor="pub-titulo">Título</label>
                            <input id="pub-titulo" className={CAMPO} maxLength={150}
                                value={formPublicar.titulo}
                                onChange={(e) => setFormPublicar({ ...formPublicar, titulo: e.target.value })} />
                        </div>

                        <div className="mt-3">
                            <label className={ETIQUETA} htmlFor="pub-texto">Texto</label>
                            <textarea id="pub-texto" className={`${CAMPO} min-h-[90px]`} maxLength={900}
                                value={formPublicar.texto}
                                onChange={(e) => setFormPublicar({ ...formPublicar, texto: e.target.value })} />
                            <p className={AYUDA}>
                                Se agrega al final: {escalera.length > 0 ? escalera.join(' · ') : '—'}
                            </p>
                        </div>

                        <div className="mt-3 grid gap-3 sm:grid-cols-2">
                            <div>
                                <label className={ETIQUETA} htmlFor="pub-desde">Vigente desde</label>
                                <input id="pub-desde" type="date" className={CAMPO}
                                    value={formPublicar.vigente_desde}
                                    onChange={(e) => setFormPublicar({ ...formPublicar, vigente_desde: e.target.value })} />
                            </div>
                            <div>
                                <label className={ETIQUETA} htmlFor="pub-hasta">Vigente hasta</label>
                                <input id="pub-hasta" type="date" className={CAMPO}
                                    value={formPublicar.vigente_hasta}
                                    onChange={(e) => setFormPublicar({ ...formPublicar, vigente_hasta: e.target.value })} />
                            </div>
                        </div>

                        <label className="mt-4 flex items-center gap-2 text-[12px] text-zinc-300">
                            <input type="checkbox"
                                checked={formPublicar.fijado_arriba}
                                onChange={(e) => setFormPublicar({ ...formPublicar, fijado_arriba: e.target.checked })} />
                            Fijar arriba en el carrusel
                        </label>

                        {erroresPublicar.length > 0 && (
                            <ul className="mt-3 space-y-1">
                                {erroresPublicar.map((texto) => (
                                    <li key={texto} className="text-[12px] text-red-400">• {texto}</li>
                                ))}
                            </ul>
                        )}

                        <div className="mt-5 flex justify-end gap-2">
                            <button type="button" onClick={() => setModalPublicar(false)}
                                disabled={publicar.isPending}
                                className={`${BOTON} border border-zinc-700 text-zinc-300 hover:bg-zinc-800`}>
                                Cancelar
                            </button>
                            <button type="submit" disabled={publicar.isPending || activos.length === 0}
                                data-testid="btn-confirmar-publicacion"
                                className={`${BOTON} bg-orange-500 hover:bg-orange-600 text-white`}>
                                {publicar.isPending ? 'Publicando…' : (data?.publicada ? 'Guardar cambios' : 'Publicar')}
                            </button>
                        </div>
                    </form>
                </div>
            )}
        </div>
    );
};

export default GestionTramosReferidos;


