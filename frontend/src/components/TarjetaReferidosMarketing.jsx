import React, { useEffect, useMemo, useState } from 'react';
import {
    useConfiguracionReferidos, useGuardarTarjetaReferidos,
    usePromocionesReferidos, useTarjetaReferidos,
} from '../hooks/queries';
import { TIPO_REFERIDOS } from '../utils/avisosMarketing';
import {
    MAX_CTA_TARJETA, MAX_TEXTO_TARJETA, MAX_TITULO_TARJETA,
    TARJETA_REFERIDOS_POR_DEFECTO, mensajeDeError, textoSugeridoTarjetaReferidos,
    validarTarjetaReferidos,
} from '../utils/referidos';

const CAMPOS = [
    {
        key: 'titulo',
        label: 'Título',
        ayuda: 'El texto grande de la tarjeta.',
        max: MAX_TITULO_TARJETA,
        filas: 1,
    },
    {
        key: 'texto',
        label: 'Texto',
        ayuda: 'Una o dos frases: lo que el alumno lee antes de tocar.',
        max: MAX_TEXTO_TARJETA,
        filas: 3,
    },
    {
        key: 'cta',
        label: 'Botón',
        ayuda: 'La llamada a la acción. El destino siempre es "Invita y Gana".',
        max: MAX_CTA_TARJETA,
        filas: 1,
    },
];

const claseCampo = (conError) => `w-full rounded-xl border bg-zinc-950 px-4 py-3 text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 ${conError
    ? 'border-red-500/60 focus:border-red-400 focus:ring-red-500/20'
    : 'border-zinc-700 focus:border-orange-500 focus:ring-orange-500/20'}`;

/**
 * Editor de la tarjeta FIJA "Invita y Gana" del carrusel "Novedades del box".
 *
 * Es la ÚLTIMA tarjeta del Inicio del alumno y NO es un aviso de la BD de
 * marketing: por eso no aparece en la tabla de avisos ni tiene vigencia, orden o
 * flyer. Vive en su propia tabla (`tarjeta_referidos`, migración 058) y su copy
 * lo lee el alumno en `GET /referidos/tarjeta`.
 *
 * Lo que se puede editar: título, texto y botón (y ocultarla del carrusel). La
 * etiqueta "Trae a un amigo", el dorado y el destino `/alumno/invita-y-gana` son
 * fijos: son el lenguaje visual del carrusel, no copy. Ocultarla NO apaga el
 * programa de referidos ni la pantalla del alumno.
 */
const TarjetaReferidosMarketing = () => {
    const tarjetaQuery = useTarjetaReferidos();
    const guardar = useGuardarTarjetaReferidos();
    // Los otros dos datos sólo alimentan "Usar texto sugerido": el texto depende
    // de lo que el box REALMENTE ofrece (porcentaje del invitado y promociones).
    const configQuery = useConfiguracionReferidos();
    const promosQuery = usePromocionesReferidos();

    const [form, setForm] = useState({
        titulo: TARJETA_REFERIDOS_POR_DEFECTO.titulo,
        texto: TARJETA_REFERIDOS_POR_DEFECTO.texto,
        cta: TARJETA_REFERIDOS_POR_DEFECTO.cta,
        visible: true,
    });
    const [errores, setErrores] = useState({});
    const [mensaje, setMensaje] = useState(null);

    // El GET devuelve el copy EFECTIVO (defaults resueltos), así que el admin
    // siempre ve lo mismo que el alumno. Al guardar, un texto igual al default
    // viaja como `null` (ver `validarTarjetaReferidos`): no se congela.
    useEffect(() => {
        const data = tarjetaQuery.data;
        if (!data) return;
        setForm({
            titulo: data.titulo ?? TARJETA_REFERIDOS_POR_DEFECTO.titulo,
            texto: data.texto ?? TARJETA_REFERIDOS_POR_DEFECTO.texto,
            cta: data.cta ?? TARJETA_REFERIDOS_POR_DEFECTO.cta,
            visible: data.visible !== false,
        });
    }, [tarjetaQuery.data]);

    const cambiar = (campo) => (evento) => {
        const valor = campo === 'visible' ? evento.target.checked : evento.target.value;
        setForm((previo) => ({ ...previo, [campo]: valor }));
        setErrores((previo) => ({ ...previo, [campo]: '' }));
        setMensaje(null);
    };

    const activas = useMemo(
        () => (Array.isArray(promosQuery.data) ? promosQuery.data : [])
            .filter((promo) => promo && promo.activo !== false),
        [promosQuery.data]);

    const sugerir = () => {
        const sugerido = textoSugeridoTarjetaReferidos({
            configuracion: configQuery.data,
            promociones: promosQuery.data,
        });
        setForm((previo) => ({ ...previo, ...sugerido }));
        setErrores({});
        setMensaje(null);
    };

    // Deja los campos con el texto por defecto: al guardar viajan como `null`
    // (= "usar el default"), que es exactamente lo que se ve en la vista previa.
    const restablecer = () => {
        setForm((previo) => ({ ...previo, ...TARJETA_REFERIDOS_POR_DEFECTO }));
        setErrores({});
        setMensaje({
            tipo: 'exito',
            texto: 'Texto por defecto cargado. Guardá para aplicarlo en el carrusel.',
        });
    };

    const enviar = async (evento) => {
        evento.preventDefault();

        const { valido, errores: nuevosErrores, payload } = validarTarjetaReferidos(form);
        if (!valido) {
            setErrores(nuevosErrores);
            setMensaje(null);
            return;
        }
        setErrores({});

        try {
            const data = await guardar.mutateAsync(payload);
            setMensaje({
                tipo: 'exito',
                texto: data?.visible
                    ? 'Tarjeta guardada. Ya se muestra en el carrusel de los alumnos.'
                    : 'Tarjeta guardada. No se mostrará en el carrusel (el programa sigue funcionando).',
            });
        } catch (err) {
            console.error('Error guardando la tarjeta de referidos:', err);
            setMensaje({
                tipo: 'error',
                texto: mensajeDeError(err, 'No pudimos guardar la tarjeta. Intenta nuevamente.'),
            });
        }
    };

    if (tarjetaQuery.isPending) return null;

    if (tarjetaQuery.isError) {
        return (
            <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-4 text-sm text-red-200">
                <p>⚠️ {mensajeDeError(tarjetaQuery.error, 'No pudimos cargar la tarjeta del carrusel.')}</p>
                <button type="button" onClick={() => tarjetaQuery.refetch()}
                    className="mt-2 font-semibold underline">
                    Reintentar
                </button>
            </div>
        );
    }

    const personalizada = Boolean(tarjetaQuery.data?.personalizada);
    const vista = {
        titulo: form.titulo.trim() || TARJETA_REFERIDOS_POR_DEFECTO.titulo,
        texto: form.texto.trim() || TARJETA_REFERIDOS_POR_DEFECTO.texto,
        cta: form.cta.trim() || TARJETA_REFERIDOS_POR_DEFECTO.cta,
    };

    return (
        <form onSubmit={enviar} data-testid="tarjeta-referidos"
            className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 sm:p-6">
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                <div>
                    <h3 className="text-base font-extrabold text-zinc-100">
                        Tarjeta fija “Invita y Gana”
                    </h3>
                    <p className="text-[12.5px] text-zinc-500 mt-1">
                        Es la última tarjeta del carrusel del alumno y siempre abre Invita y Gana.
                        No es un aviso: no tiene vigencia, orden ni flyer.
                    </p>
                </div>
                <label className="inline-flex items-center gap-2 rounded-full border border-zinc-700 bg-zinc-950 px-3.5 py-2 text-sm font-semibold text-zinc-200 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={form.visible}
                        onChange={cambiar('visible')}
                        data-testid="tarjeta-referidos-visible"
                        className="h-4 w-4 accent-orange-500"
                    />
                    Mostrar en el carrusel
                </label>
            </div>

            {!form.visible && (
                <p className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-[13px] text-amber-200">
                    La tarjeta no se mostrará en el carrusel. El programa de referidos y la
                    pantalla “Invita y Gana” siguen funcionando normalmente.
                </p>
            )}

            <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-5">
                {CAMPOS.map((campo) => (
                    <div key={campo.key} className={campo.key === 'texto' ? 'md:col-span-2' : ''}>
                        <div className="flex items-baseline justify-between gap-3">
                            <label htmlFor={`tarjeta-${campo.key}`}
                                className="block text-sm font-semibold text-zinc-200">
                                {campo.label}
                            </label>
                            <span className="text-[11.5px] tabular-nums text-zinc-500">
                                {String(form[campo.key] ?? '').length}/{campo.max}
                            </span>
                        </div>
                        {campo.filas > 1 ? (
                            <textarea
                                id={`tarjeta-${campo.key}`}
                                rows={campo.filas}
                                value={form[campo.key]}
                                onChange={cambiar(campo.key)}
                                placeholder={TARJETA_REFERIDOS_POR_DEFECTO[campo.key]}
                                aria-invalid={Boolean(errores[campo.key])}
                                data-testid={`tarjeta-referidos-${campo.key}`}
                                className={`mt-1.5 ${claseCampo(Boolean(errores[campo.key]))}`}
                            />
                        ) : (
                            <input
                                id={`tarjeta-${campo.key}`}
                                type="text"
                                value={form[campo.key]}
                                onChange={cambiar(campo.key)}
                                placeholder={TARJETA_REFERIDOS_POR_DEFECTO[campo.key]}
                                aria-invalid={Boolean(errores[campo.key])}
                                data-testid={`tarjeta-referidos-${campo.key}`}
                                className={`mt-1.5 ${claseCampo(Boolean(errores[campo.key]))}`}
                            />
                        )}
                        <p className="text-xs text-zinc-500 mt-1.5">{campo.ayuda}</p>
                        {errores[campo.key] && (
                            <p role="alert" className="text-xs text-red-400 mt-1.5">
                                {errores[campo.key]}
                            </p>
                        )}
                    </div>
                ))}
            </div>

            <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-5">
                <div>
                    <p className="text-[11.5px] font-semibold uppercase tracking-wide text-zinc-500">
                        Vista previa
                    </p>
                    <div className="mt-2 rounded-2xl border border-zinc-800 p-4"
                        style={{ background: TIPO_REFERIDOS.fondo }}
                        data-testid="tarjeta-referidos-preview">
                        <span className="inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-extrabold uppercase tracking-wide"
                            style={{ background: TIPO_REFERIDOS.tagFondo, color: TIPO_REFERIDOS.tagTexto }}>
                            {TIPO_REFERIDOS.tag}
                        </span>
                        <p className="mt-3 text-lg font-black leading-tight"
                            style={{ color: TIPO_REFERIDOS.titulo }}>
                            {vista.titulo}
                        </p>
                        <p className="mt-1 text-[13px] leading-snug text-zinc-300">{vista.texto}</p>
                        <span className="mt-3 inline-flex items-center gap-1 text-[13px] font-bold"
                            style={{ color: TIPO_REFERIDOS.detalle }}>
                            {vista.cta} ›
                        </span>
                    </div>
                </div>

                <div className="text-[12.5px] text-zinc-400">
                    <p className="text-[11.5px] font-semibold uppercase tracking-wide text-zinc-500">
                        Estado del texto
                    </p>
                    <p className="mt-2" data-testid="tarjeta-referidos-estado">
                        {personalizada
                            ? 'Texto personalizado: el carrusel muestra lo que escribió el box.'
                            : 'Texto por defecto: el carrusel usa el copy genérico del sistema.'}
                    </p>
                    <p className="mt-2">
                        Un campo vacío (o el texto por defecto tal cual) se guarda como “usar el
                        default”, así ese campo sigue recibiendo las mejoras del copy genérico.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                        <button
                            type="button"
                            onClick={sugerir}
                            data-testid="btn-sugerir-tarjeta-referidos"
                            className="rounded-xl border border-zinc-700 bg-zinc-950 px-3.5 py-2 text-[12.5px] font-semibold text-zinc-200 hover:border-orange-500/60 hover:text-orange-300 transition-colors"
                        >
                            Usar texto sugerido
                        </button>
                        <button
                            type="button"
                            onClick={restablecer}
                            data-testid="btn-restablecer-tarjeta-referidos"
                            className="rounded-xl border border-zinc-800 bg-zinc-950 px-3.5 py-2 text-[12.5px] font-semibold text-zinc-400 hover:text-zinc-200 transition-colors"
                        >
                            Restablecer
                        </button>
                    </div>
                    {activas.length > 1 && (
                        <p className="mt-2 text-[11.5px] text-amber-300/90">
                            Hay {activas.length} promociones activas: el texto sugerido no nombra
                            premios para no prometer uno solo.
                        </p>
                    )}
                </div>
            </div>

            {mensaje && (
                <div
                    role="status"
                    className={`mt-5 rounded-xl border px-4 py-3 text-sm font-medium ${mensaje.tipo === 'exito'
                        ? 'border-green-500/30 bg-green-500/10 text-green-300'
                        : 'border-red-500/40 bg-red-500/10 text-red-200'}`}
                >
                    {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                </div>
            )}

            <div className="mt-5 flex justify-end">
                <button
                    type="submit"
                    disabled={guardar.isPending}
                    data-testid="btn-guardar-tarjeta-referidos"
                    className="rounded-xl bg-orange-500 hover:bg-orange-600 disabled:bg-orange-500/50 disabled:cursor-not-allowed px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-orange-500/25 transition-colors"
                >
                    {guardar.isPending ? 'Guardando…' : 'Guardar tarjeta'}
                </button>
            </div>
        </form>
    );
};

export default TarjetaReferidosMarketing;
