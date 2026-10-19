import React, { useState } from 'react';
import { useValidarCodigoReferido } from '../hooks/queries';
import { LARGO_MAXIMO_CODIGO, mensajeDeError, validarCodigoIngresado } from '../utils/referidos';

/**
 * Campo para que el INVITADO aplique el código de quien lo invitó.
 *
 * Se usa en dos lugares con la misma semántica: la pantalla "Invita y gana"
 * del alumno y el paso de compra de `SolicitarPlan`. El texto de éxito lo manda
 * el backend (`MENSAJE_REFERIDO_REGISTRADO`): acá no se inventa el estado.
 *
 * `aplicado`/`onAplicado` permiten que el padre recuerde el resultado cuando
 * este bloque se desmonta (SolicitarPlan cambia de paso y vuelve al pago).
 */
const CampoReferido = ({ aplicado = null, onAplicado, className = '' }) => {
    const [codigo, setCodigo] = useState('');
    const [error, setError] = useState('');
    const [aplicadoLocal, setAplicadoLocal] = useState(null);
    const validarCodigo = useValidarCodigoReferido();

    const resultado = aplicado || aplicadoLocal;

    const enviar = async (evento) => {
        evento.preventDefault();

        const revision = validarCodigoIngresado(codigo);
        if (!revision.valido) {
            setError(revision.error);
            return;
        }

        setError('');
        try {
            const data = await validarCodigo.mutateAsync(revision.codigo);
            setCodigo(revision.codigo);
            setAplicadoLocal(data);
            onAplicado?.(data);
        } catch (err) {
            console.error('Error aplicando el código de referido:', err);
            setError(mensajeDeError(err, 'No pudimos aplicar el código. Revisa que esté bien escrito.'));
        }
    };

    if (resultado) {
        return (
            <div
                className={`bg-green-50 border border-green-200 rounded-xl p-5 ${className}`}
                data-testid="referido-aplicado"
            >
                <h3 className="text-base font-bold text-green-800">✅ Código de invitación aplicado</h3>
                <p className="text-sm text-green-700 mt-1">
                    {resultado.mensaje || 'Tu código quedó registrado.'}
                </p>
                <p className="text-xs text-green-700/80 mt-2">
                    Código: <strong className="font-mono">{resultado.codigo || codigo}</strong>.
                    El descuento se aplica cuando el box confirma tu compra. Si tienes dudas sobre
                    el monto a transferir, consulta con el box.
                </p>
            </div>
        );
    }

    return (
        <div
            className={`bg-white border border-gray-200 rounded-xl p-5 shadow-sm ${className}`}
            data-testid="campo-referido"
        >
            <h3 className="text-base font-bold text-gray-900">🎟️ ¿Tienes un código de invitación?</h3>
            <p className="text-sm text-gray-600 mt-1">
                Si un amigo te invitó al box, ingrésalo acá antes de comprar tu plan.
                Sólo puedes usar un código.
            </p>

            <form onSubmit={enviar} className="mt-4 flex flex-col sm:flex-row gap-2">
                <label htmlFor="codigo-referido" className="sr-only">Código de invitación</label>
                <input
                    id="codigo-referido"
                    name="codigo-referido"
                    type="text"
                    value={codigo}
                    onChange={(evento) => {
                        setCodigo(evento.target.value);
                        if (error) setError('');
                    }}
                    placeholder="Ej: JPERE234"
                    maxLength={LARGO_MAXIMO_CODIGO}
                    autoComplete="off"
                    autoCapitalize="characters"
                    spellCheck={false}
                    aria-invalid={Boolean(error)}
                    aria-describedby={error ? 'error-codigo-referido' : 'ayuda-codigo-referido'}
                    className={`flex-1 min-w-0 rounded-lg border px-4 py-2.5 text-sm font-mono uppercase tracking-wide text-gray-900 placeholder:text-gray-400 placeholder:font-sans placeholder:tracking-normal focus:outline-none focus:ring-2 ${error
                        ? 'border-red-400 focus:ring-red-200'
                        : 'border-gray-300 focus:border-emerald-500 focus:ring-emerald-100'}`}
                />
                <button
                    type="submit"
                    disabled={validarCodigo.isPending}
                    data-testid="btn-aplicar-referido"
                    className="rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 disabled:cursor-not-allowed text-white text-sm font-bold px-5 py-2.5 transition-colors"
                >
                    {validarCodigo.isPending ? 'Aplicando…' : 'Aplicar código'}
                </button>
            </form>

            {error && (
                <p id="error-codigo-referido" role="alert" className="text-sm text-red-600 mt-2">
                    ❌ {error}
                </p>
            )}

            <p id="ayuda-codigo-referido" className="text-xs text-gray-500 mt-2">
                El descuento se calcula cuando el box confirma la compra. Si ya transferiste,
                avísale al box para que lo considere.
            </p>
        </div>
    );
};

export default CampoReferido;
