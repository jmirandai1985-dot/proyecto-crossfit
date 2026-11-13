import React, { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import axios from 'axios';

// Mismo lenguaje visual que Login/RegistroAlumnoNuevo: fondo oscuro con la portada,
// tarjeta translúcida y el naranja de marca (#ff8c00). `login-input` ya vive en
// index.css y es el input compartido del login público: se reusa para no crear un
// tercer estilo de formulario en la app.
const CLASE_INPUT = 'login-input w-full px-4 py-2.5 transition-all';

const FORM_VACIO = {
    nombre: '',
    rut: '',
    correo: '',
    genero: '',
    peso_kg: '',
    estatura_cm: '',
    telefono: '',
    fecha_nacimiento: '',
};

/**
 * Campo con LABEL VISIBLE y enlazado (`htmlFor` + `id`).
 *
 * POR QUÉ EXISTE: el formulario se apoyaba en el `placeholder`, y un
 * `<input type="date">` NO lo muestra (Android abre el calendario sin decir qué
 * fecha pide y parece que estuviera agendando una clase). El label queda SIEMPRE
 * arriba, también en fecha de nacimiento.
 */
const Campo = ({ id, label, hint = '', children }) => (
    <div>
        <label htmlFor={id} className="mb-2 block text-sm font-medium text-zinc-300">
            {label}
        </label>
        {children}
        {hint && <p className="mt-1 text-[11px] leading-snug text-zinc-500">{hint}</p>}
    </div>
);

export default function LandingPage() {
    const [searchParams] = useSearchParams();
    // Link de invitación de un alumno (`/landing?inv=<token>`). El token NO
    // autoriza nada: el backend lo usa sólo para ligar la invitación a la cuenta
    // nueva y poder prellenar el código en la compra. Sin token (o con uno
    // inválido) el alta funciona exactamente igual.
    const tokenInvitacion = (searchParams.get('inv') || '').trim();
    const [formData, setFormData] = useState(FORM_VACIO);
    // Sólo presentación: { tipo: 'ok' | 'error' | 'aviso', texto, password? }.
    // La lógica de envío y sus mensajes son los mismos de siempre.
    const [resultado, setResultado] = useState(null);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData((previo) => ({ ...previo, [name]: value }));
    };

    const validarRUT = (rut) => /^\d{7,8}-[\dkK]$/.test(rut);

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!validarRUT(formData.rut)) {
            setResultado({ tipo: 'error', texto: 'RUT inválido (ej: 12345678-9)' });
            return;
        }

        try {
            const payload = {
                nombre: formData.nombre,
                correo: formData.correo,
                rut: formData.rut,
                sexo: formData.genero,
                peso_kg: parseFloat(formData.peso_kg),
                estatura_cm: parseInt(formData.estatura_cm),
                telefono: formData.telefono,
                fecha_nacimiento: formData.fecha_nacimiento,
            };
            // Sólo se envía si vino en el link: el backend ignora un token inválido o
            // ya usado y NUNCA falla el registro por eso.
            if (tokenInvitacion) payload.token_invitacion = tokenInvitacion;

            const res = await axios.post('/api/v1/alumnos/registro/alumno-nuevo', payload);

            // RG-04: si el envío del correo con la contraseña temporal falló, el backend
            // la devuelve en la respuesta. Hay que mostrarla: si no, el alumno no tiene
            // forma de ingresar y el "revisa tu correo" le mentiría.
            const d = res.data || {};
            if (d.email_enviado === false && d.password_provisional) {
                setResultado({
                    tipo: 'aviso',
                    texto: 'Registro creado, pero no pudimos enviarte el correo. Tu contraseña temporal es:',
                    password: d.password_provisional,
                    nota: 'Ingresa con ella y cámbiala en Ajustes.',
                });
            } else {
                setResultado({
                    tipo: 'ok',
                    texto: '¡Solicitud recibida! Revisa tu correo (incluyendo SPAM).',
                });
            }
            setFormData(FORM_VACIO);
        } catch (error) {
            setResultado({
                tipo: 'error',
                texto: 'Error: ' + (error.response?.data?.detail || 'Intenta de nuevo'),
            });
        }
    };

    return (
        <main className="relative min-h-screen overflow-hidden bg-zinc-950 px-4 py-10 text-zinc-100">
            {/* Portada del box: mismo recurso que el Login, atenuado para que el
                formulario siga siendo el protagonista. Puro Tailwind (sin style). */}
            <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 bg-[url('/imgs/portada.webp')] bg-cover bg-center opacity-20"
            />

            <div className="relative mx-auto flex w-full max-w-[880px] flex-col items-center">
                <header className="mb-8 max-w-[640px] text-center">
                    <img
                        src="/imgs/logo.png"
                        alt="Urban Training Box"
                        className="mx-auto mb-4 h-16 w-auto object-contain"
                    />
                    <h1 className="text-3xl font-extrabold leading-tight text-white md:text-4xl">
                        ¡Bienvenido a Urban Training Box!
                    </h1>
                    <p className="mt-3 text-base text-zinc-300">
                        Transforma tu cuerpo. Supera tus límites.
                    </p>
                    <p className="mt-2 text-sm font-bold text-[#ff8c00]">
                        ¡Felicidades! Acabas de tomar la mejor decisión para tu salud y rendimiento.
                    </p>
                </header>

                {tokenInvitacion && (
                    <div
                        data-testid="aviso-invitacion"
                        className="mb-5 w-full max-w-[560px] rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-200"
                    >
                        Viniste invitado por un alumno del box: completa el formulario y tu
                        código quedará vinculado a tu registro.
                    </div>
                )}

                <form
                    onSubmit={handleSubmit}
                    data-testid="landing-form"
                    className="w-full max-w-[560px] space-y-4 rounded-xl border border-white/10 bg-[rgba(35,35,35,0.94)] p-6 shadow-[0_8px_32px_rgba(0,0,0,0.7)] md:p-9"
                >
                    <Campo id="nombre" label="Nombre completo">
                        <input
                            id="nombre"
                            name="nombre"
                            type="text"
                            autoComplete="name"
                            placeholder="Ej: Juan Pérez"
                            value={formData.nombre}
                            onChange={handleChange}
                            className={CLASE_INPUT}
                            required
                        />
                    </Campo>

                    <Campo id="rut" label="RUT (sin puntos, con guión)" hint="Ej: 12345678-9">
                        <input
                            id="rut"
                            name="rut"
                            type="text"
                            autoComplete="off"
                            placeholder="12345678-9"
                            value={formData.rut}
                            onChange={handleChange}
                            className={CLASE_INPUT}
                            required
                        />
                    </Campo>

                    <Campo id="correo" label="Correo electrónico">
                        <input
                            id="correo"
                            name="correo"
                            type="email"
                            autoComplete="email"
                            placeholder="tucorreo@ejemplo.cl"
                            value={formData.correo}
                            onChange={handleChange}
                            className={CLASE_INPUT}
                            required
                        />
                    </Campo>

                    <Campo id="genero" label="Sexo">
                        <select
                            id="genero"
                            name="genero"
                            value={formData.genero}
                            onChange={handleChange}
                            className={CLASE_INPUT}
                            required
                        >
                            <option value="">Selecciona una opción</option>
                            <option value="M">Masculino</option>
                            <option value="F">Femenino</option>
                        </select>
                    </Campo>

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <Campo id="peso_kg" label="Peso (kg)">
                            <input
                                id="peso_kg"
                                name="peso_kg"
                                type="number"
                                inputMode="decimal"
                                placeholder="Ej: 72.5"
                                value={formData.peso_kg}
                                onChange={handleChange}
                                className={CLASE_INPUT}
                                required
                            />
                        </Campo>
                        <Campo id="estatura_cm" label="Estatura (cm)">
                            <input
                                id="estatura_cm"
                                name="estatura_cm"
                                type="number"
                                inputMode="numeric"
                                placeholder="Ej: 175"
                                value={formData.estatura_cm}
                                onChange={handleChange}
                                className={CLASE_INPUT}
                                required
                            />
                        </Campo>
                    </div>

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <Campo id="telefono" label="Teléfono">
                            <input
                                id="telefono"
                                name="telefono"
                                type="tel"
                                autoComplete="tel"
                                placeholder="+56 9 1234 5678"
                                value={formData.telefono}
                                onChange={handleChange}
                                className={CLASE_INPUT}
                                required
                            />
                        </Campo>
                        <Campo
                            id="fecha_nacimiento"
                            label="Fecha de nacimiento"
                            hint="Solo completa tu ficha; no estás agendando una clase."
                        >
                            {/* SIN placeholder: los type="date" no lo muestran (Android abre
                                el calendario sin contexto). El label de arriba es el texto
                                visible que explica qué fecha se pide. */}
                            <input
                                id="fecha_nacimiento"
                                name="fecha_nacimiento"
                                type="date"
                                autoComplete="bday"
                                value={formData.fecha_nacimiento}
                                onChange={handleChange}
                                className={`${CLASE_INPUT} [color-scheme:dark]`}
                                required
                            />
                        </Campo>
                    </div>

                    <button
                        type="submit"
                        className="w-full rounded-md bg-[#ff8c00] py-3 font-bold text-black shadow-[0_0_18px_rgba(255,140,0,0.45)] transition-all hover:bg-[#ff9e2e] hover:shadow-[0_0_26px_rgba(255,140,0,0.65)] active:scale-[0.99]"
                    >
                        ¡Quiero mi clase de prueba ahora!
                    </button>

                    <p className="text-center text-[11px] text-zinc-500">
                        Enviaremos tu contraseña temporal al correo (revisa también SPAM).
                    </p>
                </form>

                {resultado && (
                    <div
                        role="status"
                        aria-live="polite"
                        data-testid="mensaje-landing"
                        className={`mt-5 w-full max-w-[560px] rounded-lg border px-4 py-3 text-sm ${resultado.tipo === 'ok'
                            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                            : resultado.tipo === 'aviso'
                                ? 'border-amber-500/40 bg-amber-500/10 text-amber-100'
                                : 'border-red-500/30 bg-red-500/10 text-red-200'}`}
                    >
                        <p>{resultado.texto}</p>
                        {resultado.password && (
                            <p className="mt-2 break-all rounded-md bg-black/30 px-3 py-2 font-mono text-base font-bold text-white">
                                {resultado.password}
                            </p>
                        )}
                        {resultado.nota && (
                            <p className="mt-2 text-amber-200/80">{resultado.nota}</p>
                        )}
                    </div>
                )}
            </div>
        </main>
    );
}
