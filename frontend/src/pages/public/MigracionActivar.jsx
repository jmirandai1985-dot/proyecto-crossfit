import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api from '../../services/api';

// Pantalla pública a la que llega el alumno migrado desde BoxMagic
// (`/migracion/activar?token=...`, link del correo masivo de activación).
//
// Dos pasos, como el backend:
//   1. al cargar, `GET /activacion/validar-token` valida el link y devuelve nombre y
//      correo (sólo lectura): si no sirve, NO se muestra el formulario;
//   2. al enviar, `POST /activacion/completar` crea la cuenta real del alumno.
//
// Los textos viven acá porque los usan el aviso de link vencido, el bloqueo del botón
// y el manejo de los errores del backend.
const API_BASE = '/api/v1/migracion-boxmagic/activacion';
const MIN_PASSWORD = 8;
const MENSAJE_LINK_INVALIDO =
    'Este enlace ya no es válido o expiró. Contacta al box para obtener uno nuevo.';

const MigracionActivar = () => {
    const [searchParams] = useSearchParams();
    const token = searchParams.get('token') || '';
    const navigate = useNavigate();

    // Validación del link. El estado inicial YA sale del token: si la URL llegó sin
    // `?token=`, el aviso de link inválido aparece en el primer render (sin un
    // setState dentro del efecto).
    const [validando, setValidando] = useState(Boolean(token));
    const [alumno, setAlumno] = useState(null);        // {nombre, correo}
    const [linkInvalido, setLinkInvalido] = useState(!token);
    const [listo, setListo] = useState(false);         // cuenta creada

    // Formulario (sólo los campos que el alumno completa)
    const [password, setPassword] = useState('');
    const [confirm, setConfirm] = useState('');
    const [rut, setRut] = useState('');
    const [fechaNacimiento, setFechaNacimiento] = useState('');
    const [estatura, setEstatura] = useState('');
    const [peso, setPeso] = useState('');
    const [aceptaTyc, setAceptaTyc] = useState(false);
    const [aceptaSalud, setAceptaSalud] = useState(false);

    // Errores: por campo (se muestran pegados al input) y general (arriba del botón)
    const [errorPassword, setErrorPassword] = useState('');
    const [errorConfirm, setErrorConfirm] = useState('');
    const [errorGeneral, setErrorGeneral] = useState('');
    const [enviando, setEnviando] = useState(false);

    useEffect(() => {
        if (!token) return undefined;

        let cancelado = false;

        const validar = async () => {
            try {
                const { data } = await api.get(`${API_BASE}/validar-token`, {
                    params: { token },
                });
                if (!cancelado) setAlumno(data);
            } catch {
                // 404 (inexistente / vencido / ya usado): mismo aviso, sin formulario.
                if (!cancelado) setLinkInvalido(true);
            } finally {
                if (!cancelado) setValidando(false);
            }
        };

        void validar();  // fire-and-forget: el catch de `validar` marca el link como inválido
        return () => { cancelado = true; };
    }, [token]);

    const formularioIncompleto = !password || !confirm || !aceptaTyc || !aceptaSalud;

    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorPassword('');
        setErrorConfirm('');
        setErrorGeneral('');

        if (password.length < MIN_PASSWORD) {
            setErrorPassword(`La contraseña debe tener al menos ${MIN_PASSWORD} caracteres.`);
            return;
        }
        if (password !== confirm) {
            setErrorConfirm('Las contraseñas no coinciden.');
            return;
        }
        if (!aceptaTyc || !aceptaSalud) {
            setErrorGeneral('Debes aceptar los dos consentimientos para activar tu cuenta.');
            return;
        }

        setEnviando(true);
        try {
            await api.post(`${API_BASE}/completar`, {
                token,
                password,
                password_confirm: confirm,
                rut: rut.trim() || null,
                fecha_nacimiento: fechaNacimiento || null,
                estatura: estatura ? Number(estatura) : null,
                peso: peso ? Number(peso) : null,
                acepta_tyc: aceptaTyc,
                acepta_salud: aceptaSalud,
            });
            setListo(true);
        } catch (err) {
            const status = err.response?.status;
            const detail = err.response?.data?.detail;

            if (status === 404) {
                // El link dejó de servir entre la validación y el envío.
                setLinkInvalido(true);
            } else if (status === 409) {
                setErrorGeneral(typeof detail === 'string'
                    ? detail
                    : 'Ya existe una cuenta con este correo.');
            } else if (status === 422 && Array.isArray(detail)) {
                // Pydantic devuelve una lista: se pega cada mensaje en su campo.
                detail.forEach((item) => {
                    const campo = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : '';
                    const mensaje = String(item.msg || '').replace(/^Value error,\s*/i, '');
                    if (campo === 'password') {
                        setErrorPassword(mensaje);
                    } else if (campo === 'password_confirm' || /no coinciden/i.test(mensaje)) {
                        setErrorConfirm(mensaje);
                    } else {
                        setErrorGeneral(mensaje);
                    }
                });
            } else {
                setErrorGeneral(typeof detail === 'string'
                    ? detail
                    : 'No pudimos activar tu cuenta. Intenta de nuevo.');
            }
        } finally {
            setEnviando(false);
        }
    };

    return (
        <div
            className="relative min-h-screen flex items-center justify-center p-4"
            style={{
                backgroundImage:
                    "linear-gradient(rgba(0,0,0,0.5), rgba(0,0,0,0.6)), url(/imgs/portada.webp)",
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                backgroundAttachment: 'fixed',
            }}
        >
            <div className="w-full max-w-[440px]">
                <div className="relative bg-[rgba(35,35,35,0.9)] border border-white/[0.12] rounded-lg shadow-[0_8px_32px_rgba(0,0,0,0.7)] p-6 md:p-10">
                    <div className="text-center mb-6">
                        <img
                            src="/imgs/logo.png"
                            alt="Urban Training Box"
                            className="h-[60px] w-auto object-contain mx-auto mb-4"
                        />
                        <h1 className="text-white font-bold text-[20px]">Activa tu cuenta</h1>
                        {!listo && !linkInvalido && (
                            <p className="text-gray-300 text-[13px] mt-1">
                                Elige tu contraseña y completa tus datos para volver a entrenar.
                            </p>
                        )}
                    </div>

                    {validando ? (
                        <div className="flex justify-center py-10" data-testid="migracion-validando">
                            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#ff8c00]" />
                        </div>
                    ) : linkInvalido ? (
                        <div className="space-y-5">
                            <div
                                data-testid="migracion-link-invalido"
                                className="bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm"
                            >
                                {MENSAJE_LINK_INVALIDO}
                            </div>
                            <button
                                type="button"
                                onClick={() => navigate('/login')}
                                className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] transition-all duration-200"
                            >
                                Ir al login
                            </button>
                        </div>
                    ) : listo ? (
                        <div className="text-center space-y-4">
                            <div
                                data-testid="migracion-activada"
                                className="bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm"
                            >
                                ¡Tu cuenta está lista! Ya puedes iniciar sesión.
                            </div>
                            <button
                                type="button"
                                onClick={() => navigate('/login')}
                                className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] hover:shadow-[0_0_26px_rgba(255,140,0,0.75)] transition-all duration-200"
                            >
                                Ir al login
                            </button>
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} className="space-y-4">
                            {/* Identidad del padrón: se muestra, no se edita acá. */}
                            <div>
                                <label htmlFor="ma-nombre" className="block text-sm font-medium text-gray-300 mb-2">
                                    Nombre
                                </label>
                                <input
                                    id="ma-nombre"
                                    type="text"
                                    value={alumno?.nombre || ''}
                                    readOnly
                                    className="login-input w-full px-4 py-2.5 cursor-not-allowed opacity-80"
                                />
                            </div>

                            <div>
                                <label htmlFor="ma-correo" className="block text-sm font-medium text-gray-300 mb-2">
                                    Correo electrónico
                                </label>
                                <input
                                    id="ma-correo"
                                    type="email"
                                    value={alumno?.correo || ''}
                                    readOnly
                                    className="login-input w-full px-4 py-2.5 cursor-not-allowed opacity-80"
                                />
                            </div>

                            <div>
                                <label htmlFor="ma-pass" className="block text-sm font-medium text-gray-300 mb-2">
                                    Contraseña
                                </label>
                                <input
                                    id="ma-pass"
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    placeholder={`Mínimo ${MIN_PASSWORD} caracteres`}
                                    className="login-input w-full px-4 py-2.5 transition-all"
                                    required
                                />
                                {errorPassword && (
                                    <p className="text-red-300 text-xs mt-1.5" data-testid="error-password">
                                        {errorPassword}
                                    </p>
                                )}
                            </div>

                            <div>
                                <label htmlFor="ma-pass2" className="block text-sm font-medium text-gray-300 mb-2">
                                    Confirmar contraseña
                                </label>
                                <input
                                    id="ma-pass2"
                                    type="password"
                                    value={confirm}
                                    onChange={(e) => setConfirm(e.target.value)}
                                    placeholder="Repite la contraseña"
                                    className="login-input w-full px-4 py-2.5 transition-all"
                                    required
                                />
                                {errorConfirm && (
                                    <p className="text-red-300 text-xs mt-1.5" data-testid="error-confirm">
                                        {errorConfirm}
                                    </p>
                                )}
                            </div>

                            {/* Datos opcionales: el padrón no los trae del Excel. */}
                            <div>
                                <label htmlFor="ma-rut" className="block text-sm font-medium text-gray-300 mb-2">
                                    RUT <span className="text-gray-500 font-normal">(opcional)</span>
                                </label>
                                <input
                                    id="ma-rut"
                                    type="text"
                                    value={rut}
                                    onChange={(e) => setRut(e.target.value)}
                                    placeholder="12.345.678-9"
                                    maxLength={12}
                                    className="login-input w-full px-4 py-2.5 transition-all"
                                />
                            </div>

                            <div>
                                <label htmlFor="ma-fecha" className="block text-sm font-medium text-gray-300 mb-2">
                                    Fecha de nacimiento <span className="text-gray-500 font-normal">(opcional)</span>
                                </label>
                                <input
                                    id="ma-fecha"
                                    type="date"
                                    value={fechaNacimiento}
                                    onChange={(e) => setFechaNacimiento(e.target.value)}
                                    className="login-input w-full px-4 py-2.5 transition-all"
                                />
                            </div>

                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label htmlFor="ma-estatura" className="block text-sm font-medium text-gray-300 mb-2">
                                        Estatura (cm)
                                    </label>
                                    <input
                                        id="ma-estatura"
                                        type="number"
                                        inputMode="decimal"
                                        min="0"
                                        max="300"
                                        step="1"
                                        value={estatura}
                                        onChange={(e) => setEstatura(e.target.value)}
                                        placeholder="170"
                                        className="login-input w-full px-4 py-2.5 transition-all"
                                    />
                                </div>
                                <div>
                                    <label htmlFor="ma-peso" className="block text-sm font-medium text-gray-300 mb-2">
                                        Peso (kg)
                                    </label>
                                    <input
                                        id="ma-peso"
                                        type="number"
                                        inputMode="decimal"
                                        min="0"
                                        max="400"
                                        step="0.1"
                                        value={peso}
                                        onChange={(e) => setPeso(e.target.value)}
                                        placeholder="70"
                                        className="login-input w-full px-4 py-2.5 transition-all"
                                    />
                                </div>
                            </div>

                            {/* Consentimientos OBLIGATORIOS del alta (los dos) */}
                            <label htmlFor="ma-tyc" className="flex items-start gap-3 text-[13px] text-gray-300 cursor-pointer">
                                <input
                                    id="ma-tyc"
                                    type="checkbox"
                                    checked={aceptaTyc}
                                    onChange={(e) => setAceptaTyc(e.target.checked)}
                                    className="mt-0.5 h-4 w-4 shrink-0 accent-[#ff8c00]"
                                />
                                <span>
                                    He leído y acepto los Términos y Condiciones y la Política de
                                    Tratamiento de Datos Personales.
                                </span>
                            </label>

                            <label htmlFor="ma-salud" className="flex items-start gap-3 text-[13px] text-gray-300 cursor-pointer">
                                <input
                                    id="ma-salud"
                                    type="checkbox"
                                    checked={aceptaSalud}
                                    onChange={(e) => setAceptaSalud(e.target.checked)}
                                    className="mt-0.5 h-4 w-4 shrink-0 accent-[#ff8c00]"
                                />
                                <span>
                                    Declaro no tener enfermedades, lesiones o condiciones de salud que
                                    me imposibiliten practicar un deporte de alto rendimiento, y que
                                    informaré al box si esa situación cambia.
                                </span>
                            </label>

                            {errorGeneral && (
                                <div
                                    data-testid="error-general"
                                    className="bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm"
                                >
                                    {errorGeneral}
                                </div>
                            )}

                            <button
                                type="submit"
                                disabled={formularioIncompleto || enviando}
                                className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] hover:shadow-[0_0_26px_rgba(255,140,0,0.75)] transition-all duration-200"
                            >
                                {enviando ? 'Activando...' : 'Activar mi cuenta'}
                            </button>
                        </form>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MigracionActivar;
