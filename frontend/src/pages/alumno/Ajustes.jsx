import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Ajustes = () => {
    const { usuario_id, token } = useAuth();

    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [mensaje, setMensaje] = useState(null);
    const [formData, setFormData] = useState({
        nombre: '',
        telefono: '',
        correo: '',
        peso_kg: '',
        estatura_cm: '',
        genero: '',
        fecha_nacimiento: '',
    });

    // Estado para cambio de contraseña
    const [passwordData, setPasswordData] = useState({
        password_actual: '',
        nueva_password: '',
        confirmar_password: '',
    });
    const [passwordSaving, setPasswordSaving] = useState(false);
    const [passwordMsg, setPasswordMsg] = useState(null);

    useEffect(() => {
        const fetchPerfil = async () => {
            setLoading(true);
            try {
                const res = await api.get(`/api/v1/usuarios/${usuario_id}`);
                const data = res.data;
                setFormData({
                    nombre: data.nombre || '',
                    telefono: data.telefono || '',
                    correo: data.correo || '',
                    peso_kg: data.peso_kg ? String(data.peso_kg) : '',
                    estatura_cm: data.estatura_cm ? String(data.estatura_cm) : '',
                    genero: data.genero || '',
                    fecha_nacimiento: data.fecha_nacimiento || '',
                });
            } catch (err) {
                console.error('Error fetching perfil:', err);
                setMensaje({ tipo: 'error', texto: 'No se pudo cargar tu perfil' });
            } finally {
                setLoading(false);
            }
        };
        fetchPerfil();
    }, [usuario_id]);

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value });
    };

    const handlePasswordChange = (e) => {
        setPasswordData({ ...passwordData, [e.target.name]: e.target.value });
    };

    // ─── Guardar datos personales ─────────────────────────────────────
    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        setMensaje(null);
        try {
            const payload = {};
            if (formData.nombre) payload.nombre = formData.nombre;
            if (formData.telefono) payload.telefono = formData.telefono;
            if (formData.correo) payload.correo = formData.correo;
            if (formData.peso_kg) payload.peso_kg = parseFloat(formData.peso_kg);
            if (formData.estatura_cm) payload.estatura_cm = parseInt(formData.estatura_cm);
            if (formData.genero) payload.genero = formData.genero;
            if (formData.fecha_nacimiento) payload.fecha_nacimiento = formData.fecha_nacimiento;

            await api.put(`/api/v1/usuarios/${usuario_id}`, payload);
            setMensaje({ tipo: 'exito', texto: 'Datos actualizados exitosamente' });
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al actualizar';
            setMensaje({ tipo: 'error', texto: typeof detalle === 'string' ? detalle : detalle[0]?.msg || 'Error desconocido' });
        } finally {
            setSaving(false);
        }
    };

    // ─── Cambiar contraseña ───────────────────────────────────────────
    const handleCambiarPassword = async (e) => {
        e.preventDefault();
        setPasswordSaving(true);
        setPasswordMsg(null);
        try {
            await api.put('/api/v1/usuarios/cambiar-password', {
                password_actual: passwordData.password_actual,
                nueva_password: passwordData.nueva_password,
                confirmar_password: passwordData.confirmar_password,
            });
            setPasswordMsg({ tipo: 'exito', texto: '✅ Contraseña actualizada exitosamente' });
            setPasswordData({ password_actual: '', nueva_password: '', confirmar_password: '' });
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al cambiar la contraseña';
            setPasswordMsg({ tipo: 'error', texto: `❌ ${detalle}` });
        } finally {
            setPasswordSaving(false);
        }
    };

    return (
        <Layout>
            <div className="max-w-2xl mx-auto space-y-6">
                {/* Título */}
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">⚙️ Ajustes</h1>
                    <p className="text-gray-600 mt-1">Actualiza tus datos personales</p>
                </div>

                {/* Mensajes */}
                {mensaje && (
                    <div className={`p-4 rounded-xl text-sm font-medium ${mensaje.tipo === 'exito'
                        ? 'bg-green-50 border border-green-200 text-green-700'
                        : 'bg-red-50 border border-red-200 text-red-700'
                        }`}>
                        {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                    </div>
                )}

                {/* ─── FORMULARIO DATOS PERSONALES ─────────────────── */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    {loading ? (
                        <div className="flex items-center justify-center py-12">
                            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-emerald-500"></div>
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} className="space-y-5">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Nombre completo</label>
                                    <input type="text" name="nombre" value={formData.nombre} onChange={handleChange} required
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Correo electrónico</label>
                                    <input type="email" name="correo" value={formData.correo} onChange={handleChange} required
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Teléfono</label>
                                    <input type="text" name="telefono" value={formData.telefono} onChange={handleChange} placeholder="+569 1234 5678"
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Peso (kg)</label>
                                    <input type="number" name="peso_kg" value={formData.peso_kg} onChange={handleChange}
                                        placeholder="Ej: 75" min="0" step="0.1"
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Estatura (cm)</label>
                                    <input type="number" name="estatura_cm" value={formData.estatura_cm} onChange={handleChange}
                                        placeholder="Ej: 170" min="50" max="250"
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Género</label>
                                    <select name="genero" value={formData.genero} onChange={handleChange}
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm">
                                        <option value="">Seleccionar...</option>
                                        <option value="M">Masculino</option>
                                        <option value="F">Femenino</option>
                                        <option value="Otro">Otro</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Fecha de nacimiento</label>
                                    <input type="date" name="fecha_nacimiento" value={formData.fecha_nacimiento} onChange={handleChange}
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                            </div>
                            <div className="pt-4 border-t border-gray-100">
                                <button type="submit" disabled={saving}
                                    className="px-6 py-2.5 bg-emerald-500 text-white rounded-xl font-medium text-sm hover:bg-emerald-600 transition-colors disabled:opacity-50">
                                    {saving ? 'Guardando...' : '💾 Guardar Cambios'}
                                </button>
                            </div>
                        </form>
                    )}
                </div>

                {/* ─── CAMBIAR CONTRASEÑA ──────────────────────────── */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-bold text-gray-800 mb-1">🔒 Cambiar Contraseña</h2>
                    <p className="text-sm text-gray-500 mb-5">Actualiza tu contraseña de acceso</p>

                    {passwordMsg && (
                        <div className={`p-4 rounded-xl text-sm font-medium mb-4 ${passwordMsg.tipo === 'exito'
                            ? 'bg-green-50 border border-green-200 text-green-700'
                            : 'bg-red-50 border border-red-200 text-red-700'
                            }`}>
                            {passwordMsg.texto}
                        </div>
                    )}

                    <form onSubmit={handleCambiarPassword} className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Contraseña actual</label>
                            <input type="password" name="password_actual" value={passwordData.password_actual}
                                onChange={handlePasswordChange} required minLength={1}
                                placeholder="Ingresa tu contraseña actual"
                                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Nueva contraseña</label>
                                <input type="password" name="nueva_password" value={passwordData.nueva_password}
                                    onChange={handlePasswordChange} required minLength={6}
                                    placeholder="Mínimo 6 caracteres"
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Confirmar nueva contraseña</label>
                                <input type="password" name="confirmar_password" value={passwordData.confirmar_password}
                                    onChange={handlePasswordChange} required minLength={6}
                                    placeholder="Repite la nueva contraseña"
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                            </div>
                        </div>
                        <div className="pt-2">
                            <button type="submit" disabled={passwordSaving}
                                className="px-6 py-2.5 bg-blue-500 text-white rounded-xl font-medium text-sm hover:bg-blue-600 transition-colors disabled:opacity-50">
                                {passwordSaving ? 'Cambiando...' : '🔑 Cambiar Contraseña'}
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </Layout>
    );
};

export default Ajustes;