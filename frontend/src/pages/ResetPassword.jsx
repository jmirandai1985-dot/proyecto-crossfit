import React, { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import api from '../services/api';

const ResetPassword = () => {
    const [searchParams] = useSearchParams();
    const token = searchParams.get('token') || '';
    const navigate = useNavigate();
    const [password, setPassword] = useState('');
    const [confirm, setConfirm] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [success, setSuccess] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        if (!token) {
            setError('El link es inválido o está incompleto.');
            return;
        }
        if (password.length < 8) {
            setError('La contraseña debe tener al menos 8 caracteres.');
            return;
        }
        if (password !== confirm) {
            setError('Las contraseñas no coinciden.');
            return;
        }
        setLoading(true);
        try {
            await api.post('/api/v1/auth/reset-password-confirm', {
                token,
                nueva_password: password,
            });
            setSuccess(true);
        } catch (err) {
            const detail = err.response?.data?.detail;
            setError(
                Array.isArray(detail)
                    ? detail[0]?.msg || 'Error de validación'
                    : (detail || 'Ocurrió un error al restablecer la contraseña')
            );
        } finally {
            setLoading(false);
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
                <div className="relative bg-[rgba(35,35,35,0.9)] border border-white/[0.12] rounded-lg shadow-[0_8px_32px_rgba(0,0,0,0.7)] p-6 md:p-10">
                    <div className="text-center mb-6">
                        <img
                            src="/imgs/logo.png"
                            alt="Urban Training Box"
                            className="h-[60px] w-auto object-contain mx-auto mb-4"
                        />
                        <h1 className="text-white font-bold text-[20px]">
                            Restablecer Contraseña
                        </h1>
                        {!success && (
                            <p className="text-gray-300 text-[13px] mt-1">
                                Ingresa tu nueva contraseña.
                            </p>
                        )}
                    </div>

                    {success ? (
                        <div className="text-center space-y-4">
                            <div className="bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm">
                                ✅ Contraseña actualizada correctamente.
                            </div>
                            <button
                                onClick={() => navigate('/login')}
                                className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] transition-all duration-200"
                            >
                                Ir a iniciar sesión
                            </button>
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} className="space-y-5">
                            <div>
                                <label htmlFor="rp-pass" className="block text-sm font-medium text-gray-300 mb-2">
                                    Nueva contraseña
                                </label>
                                <input
                                    id="rp-pass"
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    placeholder="Mínimo 8 caracteres"
                                    className="login-input w-full px-4 py-2.5 transition-all"
                                    required
                                />
                            </div>

                            <div>
                                <label htmlFor="rp-confirm" className="block text-sm font-medium text-gray-300 mb-2">
                                    Confirmar contraseña
                                </label>
                                <input
                                    id="rp-confirm"
                                    type="password"
                                    value={confirm}
                                    onChange={(e) => setConfirm(e.target.value)}
                                    placeholder="Repite la contraseña"
                                    className="login-input w-full px-4 py-2.5 transition-all"
                                    required
                                />
                            </div>
                            {error && (
                                <div className="bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                                    {error}
                                </div>
                            )}

                            <button
                                type="submit"
                                disabled={loading}
                                className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] disabled:opacity-50 text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] hover:shadow-[0_0_26px_rgba(255,140,0,0.75)] transition-all duration-200"
                            >
                                {loading ? 'Guardando...' : 'Cambiar contraseña'}
                            </button>
                        </form>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ResetPassword;
