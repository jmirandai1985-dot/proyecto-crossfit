import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { validarAceptaciones } from '../utils/registroAceptaciones';

const RegistroAlumnoNuevo = ({ onClose }) => {
    const navigate = useNavigate();
    const [form, setForm] = useState({
        nombre: '', correo: '', rut: '', sexo: '', peso: '', estatura: '',
        telefono: '', fecha_nacimiento: '',
        acepta_tyc: false, acepta_salud: false,
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState(false);
    // RG-04: cuando el correo con la contraseña temporal NO sale, el backend la
    // devuelve en la respuesta (email_enviado=false) y hay que mostrarla acá.
    const [avisoCorreo, setAvisoCorreo] = useState(null);
    // Consentimientos del alta: checkboxes independientes + modal de lectura.
    const [modalAbierto, setModalAbierto] = useState(false);
    const [errores, setErrores] = useState({});

    const handleChange = (e) => {
        setForm({ ...form, [e.target.name]: e.target.value });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        // Consentimientos obligatorios (bloquean el submit si falta alguno).
        const chequeo = validarAceptaciones({
            acepta_tyc: form.acepta_tyc,
            acepta_salud: form.acepta_salud,
        });
        if (!chequeo.valido) {
            setErrores((prev) => ({ ...prev, ...chequeo.errores }));
            return;
        }

        setLoading(true);
        try {
            const r = await api.post('/api/v1/alumnos/registro/alumno-nuevo', {
                nombre: form.nombre,
                correo: form.correo,
                rut: form.rut,
                sexo: form.sexo,
                peso: parseFloat(form.peso),
                estatura: form.estatura ? parseFloat(form.estatura) : null,
                telefono: form.telefono,
                fecha_nacimiento: form.fecha_nacimiento,
                acepta_tyc: form.acepta_tyc,
                acepta_salud: form.acepta_salud,
            });
            const d = r.data || {};
            setAvisoCorreo(d.email_enviado === false && d.password_provisional
                ? { password: d.password_provisional, mensaje: d.mensaje || d.aviso }
                : null);
            setSuccess(true);
            // Si el correo falló NO redirigimos: el alumno tiene que copiar la
            // contraseña que le mostramos.
            if (d.email_enviado !== false) {
                setTimeout(() => {
                    onClose();
                    navigate('/login');
                }, 3000);
            }
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
                        Completa tus datos y comienza tu clase de prueba hoy
                    </p>
                </div>

                {success ? (
                    avisoCorreo ? (
                        <div data-testid="aviso-password-provisional" className="bg-amber-500/15 border border-amber-500/40 text-amber-200 px-4 py-4 rounded-lg text-sm text-center">
                            ⚠️ <strong>Registro creado, pero no pudimos enviarte el correo.</strong>
                            <p className="mt-2 text-amber-100/90">{avisoCorreo.mensaje}</p>
                            <p className="mt-3 text-xs uppercase tracking-wide text-amber-200/70">Contraseña temporal</p>
                            <p data-testid="password-provisional" className="mt-1 font-mono text-lg font-bold text-white break-all">{avisoCorreo.password}</p>
                            <p className="mt-2 text-amber-200/80">Ingresa con esta contraseña y cambiala en Ajustes.</p>
                        </div>
                    ) : (
                    <div className="bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-4 rounded-lg text-sm text-center">
                        ✅ <strong>¡Perfecto!</strong>
                        <p className="mt-1 text-emerald-200/80">Revisa tu correo para la contraseña temporal. Ya tienes acceso a tu clase de prueba. Redirigiendo al login...</p>
                    </div>
                    )
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
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Sexo *</label>
                                <select name="sexo" value={form.sexo} onChange={handleChange} className={`${inputClass} bg-zinc-800`} required>
                                    <option value="">Seleccionar</option>
                                    <option value="M">Masculino</option>
                                    <option value="F">Femenino</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Peso (kg) *</label>
                                <input name="peso" type="number" step="0.1" min="1" max="400" value={form.peso} onChange={handleChange} placeholder="70" className={inputClass} required />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Estatura (cm)</label>
                                <input name="estatura" type="number" step="1" min="1" value={form.estatura} onChange={handleChange} placeholder="170" className={inputClass} />
                            </div>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Teléfono *</label>
                                <input name="telefono" type="tel" value={form.telefono} onChange={handleChange} placeholder="+56 9 1234 5678" className={inputClass} required />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Fecha de nacimiento *</label>
                                <input name="fecha_nacimiento" type="date" value={form.fecha_nacimiento} onChange={handleChange} className={inputClass} required />
                            </div>
                        </div>
                        <p className="text-gray-500 text-[11px]">
                            * Peso y sexo son obligatorios: los usamos para calcular tu nivel (sin
                            ellos el motor de niveles no puede clasificar tu fuerza ni tu gimnasia).
                        </p>

                        <div className="space-y-3 mt-4">
                            <label className="flex items-start gap-2 text-sm text-zinc-300">
                                <input
                                    type="checkbox"
                                    checked={form.acepta_tyc}
                                    onChange={(e) => {
                                        setForm({ ...form, acepta_tyc: e.target.checked });
                                        setErrores((prev) => ({ ...prev, acepta_tyc: false }));
                                    }}
                                    className="mt-1 accent-[#ff8c00]"
                                />
                                <span>
                                    He leído y acepto los{' '}
                                    <button
                                        type="button"
                                        onClick={() => setModalAbierto(true)}
                                        className="text-[#ff8c00] underline underline-offset-2"
                                    >
                                        Términos y Condiciones y la Política de Tratamiento de Datos Personales
                                    </button>
                                    .
                                </span>
                            </label>
                            {errores?.acepta_tyc && (
                                <p className="text-red-400 text-xs ml-6">Debes aceptar los Términos y Condiciones.</p>
                            )}

                            <label className="flex items-start gap-2 text-sm text-zinc-300">
                                <input
                                    type="checkbox"
                                    checked={form.acepta_salud}
                                    onChange={(e) => {
                                        setForm({ ...form, acepta_salud: e.target.checked });
                                        setErrores((prev) => ({ ...prev, acepta_salud: false }));
                                    }}
                                    className="mt-1 accent-[#ff8c00]"
                                />
                                <span>
                                    Declaro no tener enfermedades, lesiones o condiciones de salud que me
                                    imposibiliten practicar un deporte de alto rendimiento en este
                                    establecimiento, y que informaré al Box de inmediato si esa situación
                                    cambia. Entiendo que es mi responsabilidad consultar a un profesional
                                    de la salud si tengo dudas sobre mi aptitud física para entrenar.
                                </span>
                            </label>
                            {errores?.acepta_salud && (
                                <p className="text-red-400 text-xs ml-6">Debes aceptar la declaración de salud.</p>
                            )}
                        </div>

                        {modalAbierto && (
                            <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
                                 onClick={() => setModalAbierto(false)}>
                                <div className="bg-[#15151c] border border-zinc-700 rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6"
                                     onClick={(e) => e.stopPropagation()}>
                                    <h2 className="text-lg font-bold text-white mb-4">Términos y Condiciones</h2>
                                    <div className="text-sm text-zinc-300 space-y-3">
                                        {/* Contenido de solo lectura — Cline: usar el texto final del doc
                                            "Urban Training Box — Términos y Condiciones + Tratamiento de
                                            Datos Personales" (secciones 1, 2 y 3). Pedir el texto si no
                                            lo tienes a mano en vez de inventarlo. */}
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setModalAbierto(false)}
                                        className="mt-4 bg-[#ff8c00] text-black font-bold py-2 px-4 rounded"
                                    >
                                        Cerrar
                                    </button>
                                </div>
                            </div>
                        )}

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
                            {loading ? 'Creando tu cuenta...' : 'Crear mi cuenta y empezar'}
                        </button>

                        <p className="text-center text-gray-500 text-[11px]">
                            Enviaremos tu contraseña temporal al correo (revisa también SPAM).
                        </p>
                    </form>
                )}
            </div>
        </div>
    );
};

export default RegistroAlumnoNuevo;
