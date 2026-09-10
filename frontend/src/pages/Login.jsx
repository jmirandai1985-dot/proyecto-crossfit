import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import RegistroAlumnoNuevo from '../components/RegistroAlumnoNuevo';
import ResetContrasena from '../components/ResetContrasena';
import CambiarPasswordInicial from '../components/CambiarPasswordInicial';
import { Eye, EyeOff } from 'lucide-react';

const Login = () => {
    const [correo, setCorreo] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [showRegistro, setShowRegistro] = useState(false);
    const [showReset, setShowReset] = useState(false);
    const [showPassword, setShowPassword] = useState(false);  // toggle "ojito" del campo Contraseña
    // Cambio forzado de contraseña temporal (alumno nuevo)
    const [showCambioPassword, setShowCambioPassword] = useState(false);
    const [accessTokenTemporal, setAccessTokenTemporal] = useState(null);
    const { login } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    // Navega al destino correcto tras autenticar (respeta ?redirect= o state.from).
    const redirigir = (rolUsuario) => {
        const from = location.state?.from
            || new URLSearchParams(location.search).get('redirect');
        if (from && from.startsWith('/')) {
            navigate(from, { replace: true });
            return;
        }
        const dashboardMap = {
            administrador: '/admin/dashboard',
            coach: '/coach/dashboard',
            alumno: '/alumno/dashboard',
        };
        navigate(dashboardMap[rolUsuario] || '/login');
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        const result = await login(correo, password);

        if (result.success) {
            if (result.requiereCambioPassword) {
                // Alumno nuevo con contraseña temporal: abrimos el modal forzado
                // sin persistir la sesión todavía.
                setAccessTokenTemporal(result.accessToken);
                setShowCambioPassword(true);
                setLoading(false);
                return;
            }
            redirigir(result.rol);
        } else {
            setError(result.error);
        }

        setLoading(false);
    };

    // Tras cambiar la contraseña temporal, autenticamos con la nueva (el flag ya
    // estará en false), persistimos la sesión y redirigimos al dashboard.
    const handleCambioExitoso = async (nuevaPassword) => {
        setShowCambioPassword(false);
        setError('');
        setLoading(true);
        const result = await login(correo, nuevaPassword);
        setLoading(false);
        if (result.success) {
            redirigir(result.rol);
        } else {
            setError(result.error || 'No se pudo iniciar sesión. Intenta de nuevo.');
        }
    };

    return (
        <div
            className="relative min-h-screen flex items-center justify-center p-4"
            style={{
                backgroundImage:
                    "linear-gradient(rgba(0,0,0,0.5), rgba(0,0,0,0.6)), url(/imgs/portada.png)",
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                backgroundAttachment: 'fixed',
            }}
        >
            <div className="w-full max-w-[440px]">
                {/* Card / Contenedor del formulario */}
                <div className="relative bg-[rgba(35,35,35,0.9)] border border-white/[0.12] rounded-lg shadow-[0_8px_32px_rgba(0,0,0,0.7)] p-6 md:p-12">
                    {/* Remaches decorativos (esquinas) */}
                    <span className="absolute top-2 left-2 w-2.5 h-2.5 rounded-full bg-white/20" />
                    <span className="absolute top-2 right-2 w-2.5 h-2.5 rounded-full bg-white/20" />
                    <span className="absolute bottom-2 left-2 w-2.5 h-2.5 rounded-full bg-white/20" />
                    <span className="absolute bottom-2 right-2 w-2.5 h-2.5 rounded-full bg-white/20" />

                    {/* Logo e identidad */}
                    <div className="text-center mb-8">
                        <img src="/imgs/logo.png" alt="Urban Training Box"
                            className="h-[60px] w-auto object-contain mx-auto mb-4" />
                        <h1 className="text-white font-bold text-[20px]">Urban Training Box</h1>
                        <p className="text-gray-300 text-[13px] mt-1">Plataforma de Gestión</p>
                    </div>

                    {/* Form */}
                    <form onSubmit={handleSubmit} className="space-y-6">
                        {/* Correo */}
                        <div>
                            <label htmlFor="correo" className="block text-sm font-medium text-gray-300 mb-2">
                                Correo Electrónico
                            </label>
                            <input
                                id="correo"
                                type="email"
                                value={correo}
                                onChange={(e) => setCorreo(e.target.value)}
                                placeholder="Correo Electrónico"
                                className="login-input w-full px-4 py-2.5 transition-all"
                                required
                            />
                        </div>

                        {/* Contraseña */}
                        <div>
                            <label htmlFor="password" className="block text-sm font-medium text-gray-300 mb-2">
                                Contraseña
                            </label>
                            <div className="relative">
                                <input
                                    id="password"
                                    type={showPassword ? 'text' : 'password'}
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    placeholder="••••••••"
                                    className="login-input w-full pl-4 pr-11 py-2.5 transition-all"
                                    required
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPassword((v) => !v)}
                                    aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                                    title={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200 transition-colors"
                                >
                                    {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                                </button>
                            </div>
                        </div>

                        {/* Error Message */}
                        {error && (
                            <div className="bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                                {error}
                            </div>
                        )}

                        {/* Submit Button */}
                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] disabled:opacity-50 text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] hover:shadow-[0_0_26px_rgba(255,140,0,0.75)] transition-all duration-200"
                        >
                            {loading ? 'Ingresando...' : 'Ingresar'}
                        </button>

                        {/* Links opcionales */}
                        <div className="flex flex-col items-center gap-3">
                            <button
                                type="button"
                                onClick={() => setShowReset(true)}
                                className="text-[#ff8c00] hover:text-[#ffb066] transition-colors text-sm"
                            >
                                ¿Olvidaste tu contraseña?
                            </button>
                            <button
                                type="button"
                                onClick={() => setShowRegistro(true)}
                                className="text-[#ff8c00] hover:text-[#ffb066] transition-colors text-sm underline underline-offset-4"
                            >
                                ¿Eres alumno nuevo? Regístrate aquí
                            </button>
                        </div>
                    </form>

                    {/* Footer dentro del card */}
                    <div className="mt-8 pt-6 border-t border-white/10 text-center">
                        <p className="text-white/50 text-[11px]">
                            © 2026 Urban Training Box. Todos los derechos reservados.
                        </p>
                    </div>
                </div>
            </div>

            {showRegistro && <RegistroAlumnoNuevo onClose={() => setShowRegistro(false)} />}
            {showReset && <ResetContrasena onClose={() => setShowReset(false)} />}
            {showCambioPassword && (
                <CambiarPasswordInicial
                    accessToken={accessTokenTemporal}
                    passwordTemporal={password}
                    onSuccess={handleCambioExitoso}
                />
            )}
        </div>
    );
};

export default Login;
