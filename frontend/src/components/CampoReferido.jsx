import React, { useState } from 'react';
import { useValidarCodigoReferido } from '../hooks/queries';
import {
    LARGO_MAXIMO_CODIGO, mensajeDeError, normalizarCodigoIngresado,
    validarCodigoIngresado,
} from '../utils/referidos';

/**
 * Campo para que el INVITADO aplique el código de quien lo invitó.
 *
 * Vive en `InvitaYGana` (bloque "¿Te invitó un amigo?"). NO está en el paso de
 * compra (`SolicitarPlan`): el backend ya descuenta el premio ANTES de cobrar
 * —el precio final viaja en `/beneficios/mios` y se congela en la solicitud y en
 * la preferencia de Mercado Pago—, así que el código se aplica una sola vez y el
 * pago no necesita un formulario que no cobra nada. El texto de éxito lo manda el
 * backend (`MENSAJE_REFERIDO_REGISTRADO`): acá no se inventa el estado.
 *
 * `codigoSugerido` (migración 054) viene de `GET /referidos/mi-invitacion`, es
 * decir del link `/landing?inv=<token>` con el que el alumno se registró. Sólo
 * PRELLENA el input: aplicarlo sigue siendo un toque explícito en "Aplicar
 * código", así el consentimiento y la fuente de verdad quedan en el backend.
 *
 * `aplicado`/`onAplicado` permiten que el padre recuerde el resultado cuando
 * este bloque se desmonta.
 *
 * `mostrarTitulo={false}` deja el bloque sin su `<h3>`, para cuando vive dentro
 * de una tarjeta que ya lo rotula (así el texto no se repite dos veces).
 */
const CampoReferido = ({
    aplicado = null, onAplicado, codigoSugerido = '', className = '',
    mostrarTitulo = true,
}) => {
    const [codigo, setCodigo] = useState(
        () => normalizarCodigoIngresado(codigoSugerido));
    // `tocado` evita pisar lo que el alumno ya escribió si la consulta de
    // `mi-invitacion` resuelve DESPUÉS del montaje del campo.
    const [tocado, setTocado] = useState(false);
    const [error, setError] = useState('');
    const [aplicadoLocal, setAplicadoLocal] = useState(null);
    const validarCodigo = useValidarCodigoReferido();

    const resultado = aplicado || aplicadoLocal;
    const sugerido = normalizarCodigoIngresado(codigoSugerido);

    React.useEffect(() => {
        if (tocado || !sugerido) return;
        setCodigo((actual) => actual || sugerido);
    }, [sugerido, tocado]);

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
                    El descuento se aplica al precio de tu plan: lo verás al solicitar el plan y en
                    el checkout de Mercado Pago.
                </p>
            </div>
        );
    }

    return (
        <div
            className={`bg-white border border-gray-200 rounded-xl p-5 shadow-sm ${className}`}
            data-testid="campo-referido"
        >
            {mostrarTitulo && (
                <h3 className="text-base font-bold text-gray-900">🎟️ ¿Tienes un código de invitación?</h3>
            )}
            <p className="text-sm text-gray-600 mt-1">
                Si un amigo te invitó al box, ingrésalo acá <strong>antes de pagar</strong> tu plan:
                el descuento se resta del precio. Sólo puedes usar un código.
            </p>

            {sugerido && (
                <p
                    className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800"
                    data-testid="referido-prellenado"
                >
                    Prellenamos el código de quien te invitó
                    {' '}(<strong className="font-mono">{sugerido}</strong>).
                    Revísalo y toca <strong>Aplicar código</strong> para usarlo.
                </p>
            )}

            <form onSubmit={enviar} className="mt-4 flex flex-col sm:flex-row gap-2">
                <label htmlFor="codigo-referido" className="sr-only">Código de invitación</label>
                <input
                    id="codigo-referido"
                    name="codigo-referido"
                    type="text"
                    value={codigo}
                    onChange={(evento) => {
                        setTocado(true);
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
                El precio con descuento aparece al solicitar tu plan. Si ya pagaste antes de aplicar
                el código, avísale al box para que lo considere.
            </p>
        </div>
    );
};

export default CampoReferido;
