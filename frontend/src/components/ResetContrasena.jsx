import React, { useState } from 'react';
import api from '../services/api';

const ResetContrasena = ({ onClose }) => {
    const [correo, setCorreo] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await api.post('/api/v1/auth/reset-password-request', { correo });
            setSuccess(true);
        } catch (err) {
            const detail = err.response?.data?.detail;
            setError(
                Array.isArray(detail)
                    ? detail[0]?.msg || 'Error de validación'
                    : (detail || 'Ocurrió un error al solicitar el restablecimiento')
            );
        } finally {
            setLoading(false);
        }
    };

    const inputClass = 'w-full px-4 py-2.5 rounded-md bg-white/10 border border-white/15 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#ff8c00]/60 transition-all';

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
            <div
                className="relative w-full max-w-[440px] bg-[rgba(35,35,35,0.97)] border border-white/10 rounded-lg shadow-[0_8px_32px_rgba(0,0,0,0.8)] p-6 md:p-8"
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    onClick={onClose}
                    className="absolute top-3 right-3 text-gray-400 hover:text-white text-2xl leading-none w-8 h-8 rounded hover:bg-white/10 transition-colors"
                    aria-label="Cerrar"
                >&times;</button>

                <div className="text-center mb-6">
                    <img src="/imgs/logo.png" alt="Urban Training Box" className="h-[48px] w-auto object-contain mx-auto mb-3" />
                    <h2 className="text-white font-bold text-[18px]">Restablecer Contraseña</h2>
                    <p className="text-gray-400 text-[13px] mt-1">
                        Ingresa tu correo y te enviaremos un link para recuperar tu cuenta.
                    </p>
                </div>

                {success ? (
                    <div className="text-center space-y-4">
                        <div className="bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm">
                            ✅ Solicitud enviada. Si el correo existe, recibirás las instrucciones para restablecer tu contraseña.
                        </div>
                        <button
                            onClick={onClose}
                            className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] transition-all duration-200"
                        >
                            Cerrar
                        </button>
                    </div>
                ) : (
                    <form onSubmit={handleSubmit} className="space-y-5">
                        <div>
                            <label htmlFor="reset-correo" className="block text-sm font-medium text-gray-300 mb-2">
                                Correo Electrónico
                            </label>
                            <input
                                id="reset-correo"
                                type="email"
                                value={correo}
                                onChange={(e) => setCorreo(e.target.value)}
                                placeholder="Correo Electrónico"
                                className={inputClass}
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
                            {loading ? 'Enviando...' : 'Enviar link reset'}
                        </button>
                    </form>
                )}
            </div>
        </div>
    );
};

export default ResetContrasena;
