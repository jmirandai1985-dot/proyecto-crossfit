import React, { useState } from 'react';
import api from '../services/api';

/**
 * Modal BLOQUEANTE de cambio de la contraseña temporal.
 *
 * Se muestra cuando el login devuelve `cambiar_password_al_login === true`.
 * No se puede cerrar: el alumno debe fijar una contraseña definitiva antes de
 * entrar a la plataforma. Al éxito llama a `onSuccess(nuevaPassword)` para que
 * el padre complete la autenticación.
 *
 * Props:
 *  - accessToken: JWT del login con la contraseña temporal (para autenticar el POST).
 *  - passwordTemporal: la contraseña temporal usada en el login (para validar que
 *    la nueva sea distinta).
 *  - onSuccess(nuevaPassword): callback con la nueva contraseña.
 */
const CambiarPasswordInicial = ({ accessToken, passwordTemporal, onSuccess }) => {
    const [nueva, setNueva] = useState('');
    const [confirmar, setConfirmar] = useState('');
    const [mostrar, setMostrar] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const parseError = (err) => {
        const detail = err.response?.data?.detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail) && detail.length > 0) {
            return detail[0]?.msg || 'Datos inválidos';
        }
        return 'No se pudo cambiar la contraseña. Intenta nuevamente.';
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        if (nueva.length < 8) {
            setError('La contraseña debe tener al menos 8 caracteres.');
            return;
        }
        if (nueva !== confirmar) {
            setError('Las contraseñas no coinciden.');
            return;
        }
        if (passwordTemporal && nueva === passwordTemporal) {
            setError('La nueva contraseña no puede ser igual a la temporal.');
            return;
        }

        setLoading(true);
        try {
            // Se usa el alias ASCII del endpoint (mismo handler que
            // /cambiar-contraseña-inicial) para evitar cualquier problema de
            // encoding del carácter 'ñ' en la URL a través de proxies/nginx.
            await api.post(
                '/api/v1/auth/cambiar-password-inicial',
                { nueva_contraseña: nueva },
                { headers: { Authorization: `Bearer ${accessToken}` } }
            );
            onSuccess(nueva);
        } catch (err) {
            setError(parseError(err));
        } finally {
            setLoading(false);
        }
    };

    const inputClass = 'w-full px-4 py-2.5 rounded-md bg-white/10 border border-white/15 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#ff8c00]/60 transition-all';

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
            <div className="relative w-full max-w-[480px] bg-[rgba(35,35,35,0.97)] border border-white/10 rounded-lg shadow-[0_8px_32px_rgba(0,0,0,0.8)] p-6 md:p-8">
                <div className="text-center mb-6">
                    <img src="/imgs/logo.png" alt="Urban Training Box" className="h-[48px] w-auto object-contain mx-auto mb-3" />
                    <h2 className="text-white font-bold text-[18px]">Cambia tu contraseña</h2>
                    <p className="text-gray-400 text-[13px] mt-1">
                        Por seguridad, reemplaza tu contraseña temporal antes de continuar.
                    </p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-1.5">Nueva contraseña</label>
                        <input
                            type={mostrar ? 'text' : 'password'}
                            value={nueva}
                            onChange={(e) => setNueva(e.target.value)}
                            placeholder="Mínimo 8 caracteres"
                            className={inputClass}
                            autoFocus
                            required
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-1.5">Confirmar contraseña</label>
                        <input
                            type={mostrar ? 'text' : 'password'}
                            value={confirmar}
                            onChange={(e) => setConfirmar(e.target.value)}
                            placeholder="Repite la nueva contraseña"
                            className={inputClass}
                            required
                        />
                    </div>

                    <label className="flex items-center gap-2 text-gray-400 text-[13px] cursor-pointer select-none">
                        <input type="checkbox" checked={mostrar} onChange={(e) => setMostrar(e.target.checked)} />
                        Mostrar contraseñas
                    </label>

                    {error && (
                        <div className="bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                            {error}
                        </div>
                    )}

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full bg-[#ff8c00] hover:bg-[#ff9e2e] disabled:opacity-50 text-white font-bold py-3 rounded-md shadow-[0_0_18px_rgba(255,140,0,0.5)] transition-all duration-200"
                    >
                        {loading ? 'Cambiando...' : 'Cambiar contraseña'}
                    </button>
                </form>
            </div>
        </div>
    );
};

export default CambiarPasswordInicial;
