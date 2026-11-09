import React, { useEffect, useRef, useState } from 'react';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import AvisoCarga from '../../components/AvisoCarga';
import { useAuth } from '../../context/AuthContext';
// Fase 2 (Bloque 3): el perfil sale de la caché compartida `['alumnos','me']` (la misma
// que usa Solicitar plan) y los dos formularios guardan con mutaciones. Antes eran un
// `useEffect` + `api.get`/`api.put` a mano, con los `loading`/`saving` de estado espejo.
import { useCambiarPassword, useGuardarMiPerfil, useMiPerfil } from '../../hooks/queries';

const Ajustes = () => {
    const { usuario_id } = useAuth();

    const perfilQ = useMiPerfil();
    const guardarPerfil = useGuardarMiPerfil();
    const cambiarPassword = useCambiarPassword();

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
    const [passwordMsg, setPasswordMsg] = useState(null);

    // El formulario se rellena UNA vez por alumno, cuando llega la primera respuesta: un
    // refetch en segundo plano (volver a la pestaña, la invalidación que dispara el
    // propio guardado) no debe pisar lo que el alumno está escribiendo.
    const rellenadoPara = useRef(null);
    useEffect(() => {
        const data = perfilQ.data;
        if (!data || rellenadoPara.current === usuario_id) return;
        rellenadoPara.current = usuario_id;
        setFormData({
            nombre: data.nombre || '',
            telefono: data.telefono || '',
            correo: data.correo || '',
            peso_kg: data.peso_kg ? String(data.peso_kg) : '',
            estatura_cm: data.estatura_cm ? String(data.estatura_cm) : '',
            genero: data.genero || '',
            fecha_nacimiento: data.fecha_nacimiento || '',
        });
    }, [perfilQ.data, usuario_id]);

    // P1 (igual que el resto de las pantallas del alumno): si la carga falla se avisa con
    // banner + Reintentar. Antes el error sólo iba a `console.error` y a un cartel, y los
    // campos quedaban vacíos como si el alumno no tuviera datos.
    const erroresCarga = perfilQ.isError ? ['tu perfil'] : [];
    const cargarTodo = () => perfilQ.refetch();

    // Los tres "ocupado" salen de las consultas/mutaciones (antes: tres useState espejo
    // que había que apagar en cada `finally`).
    const loading = perfilQ.isPending;
    const saving = guardarPerfil.isPending;
    const passwordSaving = cambiarPassword.isPending;

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value });
    };

    const handlePasswordChange = (e) => {
        setPasswordData({ ...passwordData, [e.target.name]: e.target.value });
    };

    // ─── Guardar datos personales ─────────────────────────────────────
    const handleSubmit = async (e) => {
        e.preventDefault();
        setMensaje(null);
        try {
            // ── N-1: sólo se envían los campos que el alumno autogestiona. ──
            // `nombre` es de SOLO LECTURA (lo modifica el box) y los demás datos
            // de la ficha (correo, fecha de nacimiento) también: no van en el
            // payload para no sugerir que se pueden cambiar desde acá.
            // D2: `genero` se puede COMPLETAR una vez si está vacío (es obligatorio para
            // calcular el nivel). Si ya tiene valor, el backend responde 409 y lo corrige el box.
            const payload = {};
            if (formData.telefono) payload.telefono = formData.telefono;
            if (formData.peso_kg) payload.peso_kg = parseFloat(formData.peso_kg);
            if (formData.estatura_cm) payload.estatura_cm = parseInt(formData.estatura_cm);
            if (formData.genero && !perfilQ.data?.genero) payload.genero = formData.genero;

            await guardarPerfil.mutateAsync(payload);
            setMensaje({ tipo: 'exito', texto: 'Datos actualizados exitosamente' });
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al actualizar';
            setMensaje({ tipo: 'error', texto: typeof detalle === 'string' ? detalle : detalle[0]?.msg || 'Error desconocido' });
        }
    };

    // ─── Cambiar contraseña ───────────────────────────────────────────
    const handleCambiarPassword = async (e) => {
        e.preventDefault();
        setPasswordMsg(null);
        try {
            await cambiarPassword.mutateAsync({
                password_actual: passwordData.password_actual,
                nueva_password: passwordData.nueva_password,
                confirmar_password: passwordData.confirmar_password,
            });
            setPasswordMsg({ tipo: 'exito', texto: '✅ Contraseña actualizada exitosamente' });
            setPasswordData({ password_actual: '', nueva_password: '', confirmar_password: '' });
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al cambiar la contraseña';
            setPasswordMsg({ tipo: 'error', texto: `❌ ${detalle}` });
        }
    };

    return (
        <Layout>
            <div className="max-w-2xl mx-auto space-y-6">
                {/* Título */}
                <div className="max-md:flex max-md:items-start max-md:gap-2">
                    <BotonVolver />
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">⚙️ Ajustes</h1>
                        <p className="text-gray-600 mt-1">Actualiza tus datos de contacto y medidas. El resto de tu ficha (nombre, correo, género y fecha de nacimiento) lo administra el box.</p>
                    </div>
                </div>

                {/* P1: carga fallida visible + Reintentar (antes el fallo del fetch dejaba
                    el formulario vacío, como si el alumno no tuviera datos). */}
                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

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
                                {/* ── N-1: dato de la FICHA → sólo lectura ── */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Nombre completo</label>
                                    <input type="text" name="nombre" value={formData.nombre} readOnly
                                        aria-readonly="true"
                                        className="w-full px-3 py-2.5 border border-gray-200 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed text-sm" />
                                    <p className="text-xs text-gray-500 mt-1">Solo el box puede modificar tu nombre</p>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Correo electrónico</label>
                                    <input type="email" name="correo" value={formData.correo} readOnly
                                        aria-readonly="true"
                                        className="w-full px-3 py-2.5 border border-gray-200 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed text-sm" />
                                    <p className="text-xs text-gray-500 mt-1">Solo el box puede modificar tu correo</p>
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
                                    <select name="genero" value={formData.genero}
                                        onChange={handleChange}
                                        disabled={Boolean(perfilQ.data?.genero)}
                                        className={`w-full px-3 py-2.5 border rounded-lg text-sm ${perfilQ.data?.genero
                                            ? 'border-gray-200 bg-gray-50 text-gray-500 cursor-not-allowed'
                                            : 'border-gray-300 focus:ring-2 focus:ring-emerald-500 focus:border-transparent'}`}>
                                        <option value="">Seleccionar...</option>
                                        <option value="M">Masculino</option>
                                        <option value="F">Femenino</option>
                                    </select>
                                    <p className="text-xs text-gray-500 mt-1">
                                        {perfilQ.data?.genero
                                            ? 'Solo el box puede modificar este dato'
                                            : 'Completalo para que podamos calcular tu nivel; después solo lo corrige el box'}
                                    </p>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Fecha de nacimiento</label>
                                    <input type="date" name="fecha_nacimiento" value={formData.fecha_nacimiento} readOnly
                                        aria-readonly="true"
                                        className="w-full px-3 py-2.5 border border-gray-200 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed text-sm" />
                                    <p className="text-xs text-gray-500 mt-1">Solo el box puede modificar este dato</p>
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