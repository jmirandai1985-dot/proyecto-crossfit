import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';

const RegistroAlumnoNuevo = ({ onClose }) => {
    const navigate = useNavigate();
    const [form, setForm] = useState({
        nombre: '', correo: '', rut: '', sexo: '', peso: '', estatura: '',
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState(false);

    const handleChange = (e) => {
        setForm({ ...form, [e.target.name]: e.target.value });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await api.post('/api/v1/alumnos/registro/alumno-nuevo', {
                nombre: form.nombre,
                correo: form.correo,
                rut: form.rut,
                sexo: form.sexo || null,
                peso: form.peso ? parseFloat(form.peso) : null,
                estatura: form.estatura ? parseFloat(form.estatura) : null,
            });
            setSuccess(true);
            setTimeout(() => {
                onClose();
                navigate('/login');
            }, 3000);
        } catch (err) {
            const detail = err.response?.data?.detail;
            setError(Array.isArray(detail) ? detail[0]?.msg || 'Error de validación' : (detail || 'Ocurrió un error al registrarte'));
        } finally {
            setLoading(false);
        }
    };

    const inputClass = 'w-full px-4 py-2.5 rounded-md bg-white/10 border border-white/15 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#ff8c00]/60 transition-all';

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
            <div
                className="relative w-full max-w-[520px] bg-[rgba(35,35,35,0.97)] border border-white/10 rounded-lg shadow-[0_8px_32px_rgba(0,0,0,0.8)] p-6 md:p-8 max-h-[90vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    onClick={onClose}
                    className="absolute top-3 right-3 text-gray-400 hover:text-white text-2xl leading-none w-8 h-8 rounded hover:bg-white/10 transition-colors"
                    aria-label="Cerrar"
                >&times;</button>

                <div className="text-center mb-6">
                    <img src="/imgs/logo.png" alt="Urban Training Box" className="h-[48px] w-auto object-contain mx-auto mb-3" />
                    <h2 className="text-white font-bold text-[18px]">Registro Alumno Nuevo</h2>
                    <p className="text-gray-400 text-[13px] mt-1">
                        Completa tus datos y el admin revisará tu solicitud
                    </p>
                </div>

                {success ? (
                    <div className="bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-4 rounded-lg text-sm text-center">
                        ✅ <strong>¡Registro exitoso!</strong>
                        <p className="mt-1 text-emerald-200/80">El admin revisará tu solicitud y recibirás tus credenciales por correo. Redirigiendo al login...</p>
                    </div>
                ) : (
                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-1.5">Nombre completo</label>
                            <input name="nombre" value={form.nombre} onChange={handleChange} placeholder="Ej: Juan Pérez" className={inputClass} required />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-1.5">Correo electrónico</label>
                            <input name="correo" type="email" value={form.correo} onChange={handleChange} placeholder="tucorreo@ejemplo.cl" className={inputClass} required />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-1.5">RUT (sin puntos, con guión)</label>
                            <input name="rut" value={form.rut} onChange={handleChange} placeholder="12345678-5" className={inputClass} required />
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Sexo</label>
                                <select name="sexo" value={form.sexo} onChange={handleChange} className={`${inputClass} bg-zinc-800`}>
                                    <option value="">Seleccionar</option>
                                    <option value="M">Masculino</option>
                                    <option value="F">Femenino</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Peso (kg)</label>
                                <input name="peso" type="number" step="0.1" min="1" value={form.peso} onChange={handleChange} placeholder="70" className={inputClass} />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Estatura (cm)</label>
                                <input name="estatura" type="number" step="1" min="1" value={form.estatura} onChange={handleChange} placeholder="170" className={inputClass} />
                            </div>
                        </div>

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
                            {loading ? 'Enviando...' : 'Enviar solicitud'}
                        </button>

                        <p className="text-center text-gray-500 text-[11px]">
                            Tu solicitud será revisada por el administrador del box.
                        </p>
                    </form>
                )}
            </div>
        </div>
    );
};

export default RegistroAlumnoNuevo;
