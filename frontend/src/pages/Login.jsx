import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const Login = () => {
    const [correo, setCorreo] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { login } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        const result = await login(correo, password);

        if (result.success) {
            // Redirigir según rol
            const dashboardMap = {
                administrador: '/admin/dashboard',
                coach: '/coach/dashboard',
                alumno: '/alumno/dashboard',
            };
            navigate(dashboardMap[result.rol]);
        } else {
            setError(result.error);
        }

        setLoading(false);
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
                            <input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                placeholder="••••••••"
                                className="login-input w-full px-4 py-2.5 transition-all"
                                required
                            />
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
                        <div className="flex items-center justify-center">
                            <a href="#" onClick={(e) => e.preventDefault()}
                                className="text-[#ff8c00] hover:text-[#ffb066] transition-colors text-sm">
                                ¿Olvidaste tu contraseña?
                            </a>
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
        </div>
    );
};

export default Login;
