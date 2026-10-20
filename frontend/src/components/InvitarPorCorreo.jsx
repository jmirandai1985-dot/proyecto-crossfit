import React, { useState } from 'react';
import { useInvitarAlumno } from '../hooks/queries';
import { copiarAlPortapapeles, mensajeDeError } from '../utils/referidos';

// Mismo tope que `invitaciones.correo_prospecto` (varchar(150)) y que el schema
// `InvitarAlumnoRequest` del backend.
const LARGO_MAXIMO_CORREO = 150;

// Chequeo de FORMA para no gastar un request: el backend valida con EmailStr y
// además aplica las reglas de negocio (correo propio, ya usuario, duplicado).
const CORREO_VALIDO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Invitación por CORREO de un alumno a un amigo (migración 054).
 *
 * El backend guarda la invitación con el código del alumno y un token opaco, y
 * manda el correo con el link `/landing?inv=<token>`. Ese link es el que liga
 * al amigo con su invitador cuando completa el Día de Prueba: por eso acá se
 * muestra el enlace y se puede copiar (reenviar el MISMO link no genera otra
 * invitación ni consume el cupo diario).
 *
 * El mensaje de error es el del backend (`mensajeDeError`): el límite de 5 por
 * día, el bloqueo de 7 días y el "ya es usuario del box" se explican con SUS
 * palabras, no con un texto inventado en la pantalla.
 */
const InvitarPorCorreo = ({ className = '' }) => {
    const [correo, setCorreo] = useState('');
    const [error, setError] = useState('');
    const [aviso, setAviso] = useState('');
    const [enviada, setEnviada] = useState(null);
    const invitar = useInvitarAlumno();

    const enviar = async (evento) => {
        evento.preventDefault();

        const limpio = correo.trim().toLowerCase();
        if (!limpio) {
            setError('Ingresa el correo de tu amigo.');
            return;
        }
        if (limpio.length > LARGO_MAXIMO_CORREO || !CORREO_VALIDO.test(limpio)) {
            setError('Ingresa un correo válido (ej: amigo@correo.cl).');
            return;
        }

        setError('');
        setAviso('');
        try {
            const data = await invitar.mutateAsync(limpio);
            setEnviada(data);
            setCorreo('');
        } catch (err) {
            console.error('Error enviando la invitación de referido:', err);
            setError(mensajeDeError(
                err, 'No pudimos enviar la invitación. Inténtalo de nuevo.'));
        }
    };

    const copiarEnlace = async () => {
        if (!enviada?.enlace) return;
        try {
            await copiarAlPortapapeles(enviada.enlace);
            setAviso('✅ Enlace copiado: puedes reenviarlo por WhatsApp o correo.');
        } catch (err) {
            console.error('Error copiando el enlace de invitación:', err);
            setAviso('❌ No pudimos copiar el enlace. Selecciónalo y cópialo a mano.');
        }
    };

    return (
        <div
            className={`bg-white border border-gray-200 rounded-xl p-5 shadow-sm ${className}`}
            data-testid="invitar-por-correo"
        >
            <h2 className="text-base font-bold text-gray-900">✉️ Invita por correo</h2>
            <p className="text-sm text-gray-600 mt-1">
                Escríbele a tu amigo y le llegará una invitación con tu código y un enlace
                directo al formulario de la clase de prueba.
            </p>

            <form onSubmit={enviar} className="mt-4 flex flex-col sm:flex-row gap-2">
                <label htmlFor="correo-amigo" className="sr-only">Correo de tu amigo</label>
                <input
                    id="correo-amigo"
                    name="correo-amigo"
                    type="email"
                    value={correo}
                    onChange={(evento) => {
                        setCorreo(evento.target.value);
                        if (error) setError('');
                    }}
                    placeholder="amigo@correo.cl"
                    maxLength={LARGO_MAXIMO_CORREO}
                    autoComplete="email"
                    spellCheck={false}
                    aria-invalid={Boolean(error)}
                    aria-describedby={error ? 'error-correo-amigo' : 'ayuda-correo-amigo'}
                    className={`flex-1 min-w-0 rounded-lg border px-4 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 ${error
                        ? 'border-red-400 focus:ring-red-200'
                        : 'border-gray-300 focus:border-emerald-500 focus:ring-emerald-100'}`}
                />
                <button
                    type="submit"
                    disabled={invitar.isPending}
                    data-testid="btn-invitar-correo"
                    className="rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 disabled:cursor-not-allowed text-white text-sm font-bold px-5 py-2.5 transition-colors"
                >
                    {invitar.isPending ? 'Enviando…' : 'Enviar invitación'}
                </button>
            </form>

            {error && (
                <p id="error-correo-amigo" role="alert" className="text-sm text-red-600 mt-2">
                    ❌ {error}
                </p>
            )}

            <p id="ayuda-correo-amigo" className="text-xs text-gray-500 mt-2">
                Hasta 5 invitaciones por día y una sola vez al mismo correo cada 7 días.
                Si tu amigo no lo recibe, pídele revisar la carpeta de SPAM.
            </p>

            {enviada && (
                <div
                    className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4"
                    data-testid="invitacion-enviada"
                >
                    <p className="text-sm font-semibold text-emerald-800">
                        ✅ Invitación enviada a {enviada.correo_prospecto}
                    </p>
                    <p className="mt-1 break-all text-xs text-emerald-700">
                        {enviada.enlace}
                    </p>
                    <button
                        type="button"
                        onClick={copiarEnlace}
                        data-testid="btn-copiar-enlace"
                        className="mt-3 rounded-lg border border-emerald-300 bg-white px-4 py-2 text-xs font-bold text-emerald-700 transition-colors hover:bg-emerald-100"
                    >
                        📋 Copiar enlace
                    </button>
                    {aviso && (
                        <p role="status" className="mt-2 text-xs text-emerald-800">
                            {aviso}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
};

export default InvitarPorCorreo;

