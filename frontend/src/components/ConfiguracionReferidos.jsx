import React, { useEffect, useState } from 'react';
import GestionPromocionesReferidos from './GestionPromocionesReferidos';
import GestionTramosReferidos from './GestionTramosReferidos';
import PendientesPromocionesReferidos from './PendientesPromocionesReferidos';
import TarjetaReferidosMarketing from './TarjetaReferidosMarketing';
import {
    useConfiguracionReferidos, useGuardarConfiguracionReferidos,
} from '../hooks/queries';
import {
    formatearPorcentajeReferido, mensajeDeError, validarPorcentajeReferido,
} from '../utils/referidos';

const CAMPOS = [
    {
        key: 'invitado',
        label: 'Descuento para el invitado',
        ayuda: 'Se aplica a su primera compra pagada, sobre el precio de lista.',
    },
    {
        key: 'invitador',
        label: 'Crédito para quien invita',
        ayuda: 'Se aplica una sola vez en su próxima compra, cuando el invitado compra.',
    },
];

const claseInput = (conError) => `w-full rounded-xl border bg-zinc-950 px-4 py-3 pr-10 text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 ${conError
    ? 'border-red-500/60 focus:border-red-400 focus:ring-red-500/20'
    : 'border-zinc-700 focus:border-orange-500 focus:ring-orange-500/20'}`;

/**
 * Sub-pestaña "Referidos" de Marketing: el admin define los dos porcentajes y
 * apaga/enciende el programa. El GET devuelve los defaults (0 % / inactivo) y
 * `configurada=false` cuando el box todavía no guardó nada; el PUT crea la fila.
 */
const ConfiguracionReferidos = () => {
    const configQuery = useConfiguracionReferidos();
    const guardar = useGuardarConfiguracionReferidos();

    const [form, setForm] = useState({ invitado: '0', invitador: '0', activo: false });
    const [errores, setErrores] = useState({});
    const [mensaje, setMensaje] = useState(null);

    useEffect(() => {
        if (!configQuery.data) return;
        setForm({
            invitado: String(configQuery.data.porcentaje_descuento_invitado ?? 0),
            invitador: String(configQuery.data.porcentaje_descuento_invitador ?? 0),
            activo: Boolean(configQuery.data.activo),
        });
    }, [configQuery.data]);

    const cambiar = (campo) => (evento) => {
        const valor = campo === 'activo' ? evento.target.checked : evento.target.value;
        setForm((previo) => ({ ...previo, [campo]: valor }));
        setErrores((previo) => ({ ...previo, [campo]: '' }));
        setMensaje(null);
    };

    const enviar = async (evento) => {
        evento.preventDefault();

        const invitado = validarPorcentajeReferido(form.invitado);
        const invitador = validarPorcentajeReferido(form.invitador);
        const nuevosErrores = {};
        if (!invitado.valido) nuevosErrores.invitado = invitado.error;
        if (!invitador.valido) nuevosErrores.invitador = invitador.error;

        if (Object.keys(nuevosErrores).length > 0) {
            setErrores(nuevosErrores);
            setMensaje(null);
            return;
        }
        setErrores({});

        const confirmacion = [
            `Invitado: ${formatearPorcentajeReferido(invitado.valor)} de descuento`,
            `Invitador: ${formatearPorcentajeReferido(invitador.valor)} de crédito`,
            `Programa: ${form.activo ? 'activo' : 'apagado'}`,
            '',
            '¿Guardar esta configuración de referidos?',
        ].join('\n');
        if (!window.confirm(confirmacion)) return;

        try {
            const data = await guardar.mutateAsync({
                porcentaje_descuento_invitado: invitado.valor,
                porcentaje_descuento_invitador: invitador.valor,
                activo: form.activo,
            });
            setMensaje({
                tipo: 'exito',
                texto: data?.activo
                    ? 'Configuración guardada. El programa de referidos queda activo.'
                    : 'Configuración guardada, pero el programa queda apagado: no se aplicarán descuentos.',
            });
        } catch (err) {
            console.error('Error guardando la configuración de referidos:', err);
            setMensaje({
                tipo: 'error',
                texto: mensajeDeError(err, 'No pudimos guardar la configuración. Intenta nuevamente.'),
            });
        }
    };

    if (configQuery.isPending) {
        return (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-10 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-4 border-orange-500 border-t-transparent"></div>
            </div>
        );
    }

    if (configQuery.isError) {
        return (
            <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-4 text-sm text-red-200">
                <p>⚠️ {mensajeDeError(configQuery.error, 'No pudimos cargar la configuración de referidos.')}</p>
                <button
                    type="button"
                    onClick={() => configQuery.refetch()}
                    className="mt-2 font-semibold underline"
                >
                    Reintentar
                </button>
            </div>
        );
    }

    const config = configQuery.data;
    const vistaInvitado = validarPorcentajeReferido(form.invitado);
    const vistaInvitador = validarPorcentajeReferido(form.invitador);

    return (
        <div className="space-y-5" data-testid="configuracion-referidos">
            <div>
                <h2 className="text-xl font-extrabold text-zinc-100">Referidos e invitaciones</h2>
                <p className="text-sm text-zinc-400 mt-1">
                    Define qué gana el invitado en su primera compra y qué crédito recibe quien
                    lo invita. Los cambios se aplican al confirmar las compras.
                </p>
            </div>

            {config?.configurada === false && (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-[13px] text-amber-200">
                    Todavía no hay una configuración guardada. Se muestran los valores por defecto
                    (0 % e inactivo); al guardar se crea la configuración del box.
                </div>
            )}

            <form onSubmit={enviar} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 sm:p-6">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                    <div>
                        <h3 className="text-base font-extrabold text-zinc-100">Porcentajes del programa</h3>
                        <p className="text-[12.5px] text-zinc-500 mt-1">
                            Entre 0 y 100, con hasta 2 decimales. Un 0 % deja el beneficio sin monto
                            pero mantiene el programa encendido.
                        </p>
                    </div>
                    <label className="inline-flex items-center gap-2 rounded-full border border-zinc-700 bg-zinc-950 px-3.5 py-2 text-sm font-semibold text-zinc-200 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={form.activo}
                            onChange={cambiar('activo')}
                            data-testid="referidos-activo"
                            className="h-4 w-4 accent-orange-500"
                        />
                        Programa activo
                    </label>
                </div>

                <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-5">
                    {CAMPOS.map((campo) => (
                        <div key={campo.key}>
                            <label htmlFor={`referido-${campo.key}`} className="block text-sm font-semibold text-zinc-200">
                                {campo.label}
                            </label>
                            <div className="relative mt-1.5">
                                <input
                                    id={`referido-${campo.key}`}
                                    type="text"
                                    inputMode="decimal"
                                    value={form[campo.key]}
                                    onChange={cambiar(campo.key)}
                                    aria-invalid={Boolean(errores[campo.key])}
                                    aria-describedby={`ayuda-referido-${campo.key}`}
                                    data-testid={`referido-${campo.key}`}
                                    className={claseInput(Boolean(errores[campo.key]))}
                                />
                                <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm font-semibold text-zinc-500">
                                    %
                                </span>
                            </div>
                            <p id={`ayuda-referido-${campo.key}`} className="text-xs text-zinc-500 mt-1.5">
                                {campo.ayuda}
                            </p>
                            {errores[campo.key] && (
                                <p role="alert" className="text-xs text-red-400 mt-1.5">
                                    {errores[campo.key]}
                                </p>
                            )}
                        </div>
                    ))}
                </div>

                <div className="mt-5 rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 text-sm text-zinc-300">
                    <p className="text-[11.5px] font-semibold uppercase tracking-wide text-zinc-500">Vista rápida</p>
                    <p className="mt-2">
                        El invitado recibe <strong className="text-orange-400">
                            {vistaInvitado.valido ? formatearPorcentajeReferido(vistaInvitado.valor) : '—'}
                        </strong> de descuento en su primera compra pagada.
                    </p>
                    <p className="mt-1">
                        Quien invita recibe <strong className="text-orange-400">
                            {vistaInvitador.valido ? formatearPorcentajeReferido(vistaInvitador.valor) : '—'}
                        </strong> de crédito para su próxima compra.
                    </p>
                    {!form.activo && (
                        <p className="mt-2 text-amber-400">
                            El programa está apagado: no se aplicará ningún porcentaje.
                        </p>
                    )}
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
                        data-testid="btn-guardar-referidos"
                        className="rounded-xl bg-orange-500 hover:bg-orange-600 disabled:bg-orange-500/50 disabled:cursor-not-allowed px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-orange-500/25 transition-colors"
                    >
                        {guardar.isPending ? 'Guardando…' : 'Guardar configuración'}
                    </button>
                </div>
            </form>

            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 text-[13px] text-zinc-400">
                <h3 className="text-sm font-bold text-zinc-200">Cómo se mueve el dinero</h3>
                <p className="mt-2">
                    Al confirmar la compra de un invitado, el descuento se calcula sobre el precio
                    de lista y queda registrado en el ingreso del box. El crédito del invitador se
                    crea por separado y se usa una sola vez en su próxima compra.
                </p>
                <p className="mt-2">
                    Apagar el programa no borra las invitaciones ya registradas: evita aplicar
                    beneficios nuevos hasta que lo vuelvas a encender.
                </p>
            </div>

            <GestionPromocionesReferidos />
            {/* Parte C: escalera por ciclo. El motor (`motor_premios`) decide cuál
                de los dos paga; el backend se salta el box del otro motor, así que
                las dos pantallas pueden convivir sin duplicar premios. */}
            <GestionTramosReferidos />
            <PendientesPromocionesReferidos />
            <TarjetaReferidosMarketing />
        </div>
    );
};

export default ConfiguracionReferidos;

