import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Configuracion = () => {
    const { tenant_id } = useAuth();
    const [form, setForm] = useState({
        banco: '',
        numero_cuenta: '',
        tipo_cuenta: '',
        rut: '',
        email_comprobantes: '',
    });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState({ type: '', text: '' });

    useEffect(() => {
        const fetchConfig = async () => {
            try {
                const res = await api.get(`/api/v1/configuracion?tenant_id=${tenant_id}`);
                const data = res.data;
                if (data.configurado) {
                    setForm({
                        banco: data.banco || '',
                        numero_cuenta: data.numero_cuenta || '',
                        tipo_cuenta: data.tipo_cuenta || '',
                        rut: data.rut || '',
                        email_comprobantes: data.email_comprobantes || '',
                    });
                }
            } catch (err) {
                console.error('Error cargando config:', err);
            } finally {
                setLoading(false);
            }
        };
        fetchConfig();
    }, [tenant_id]);

    const handleChange = (e) => {
        setForm({ ...form, [e.target.name]: e.target.value });
    };

    const handleSave = async () => {
        setSaving(true);
        setMessage({ type: '', text: '' });
        try {
            await api.put(`/api/v1/configuracion`, form);
            setMessage({ type: 'success', text: 'Datos bancarios guardados exitosamente.' });
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al guardar. Intenta nuevamente.';
            setMessage({ type: 'error', text: detalle });
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500"></div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-2xl mx-auto space-y-6">
                <div className="flex items-center gap-3">
                    <span className="text-3xl">⚙️</span>
                    <div>
                        <h1 className="text-2xl font-bold text-zinc-100">Configuración</h1>
                        <p className="text-sm text-zinc-400">Datos bancarios para transferencias de los alumnos</p>
                    </div>
                </div>

                {message.text && (
                    <div className={`p-4 rounded-xl border text-sm font-medium ${message.type === 'success'
                            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                            : 'bg-red-50 border-red-200 text-red-700'
                        }`}>
                        {message.type === 'success' ? '✅' : '❌'} {message.text}
                    </div>
                )}

                <div className="bg-zinc-900 rounded-xl border border-zinc-800 p-6 shadow-sm space-y-5">
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Banco</label>
                        <input type="text" name="banco" value={form.banco} onChange={handleChange}
                            placeholder="Ej: Banco Santander"
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Número de Cuenta</label>
                        <input type="text" name="numero_cuenta" value={form.numero_cuenta} onChange={handleChange}
                            placeholder="Ej: 12345678"
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Tipo de Cuenta</label>
                        <select name="tipo_cuenta" value={form.tipo_cuenta} onChange={handleChange}
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm">
                            <option value="">Seleccionar...</option>
                            <option value="Corriente">Corriente</option>
                            <option value="Vista">Vista</option>
                            <option value="Rut">RUT</option>
                            <option value="Ahorro">Ahorro</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">RUT</label>
                        <input type="text" name="rut" value={form.rut} onChange={handleChange}
                            placeholder="Ej: 12.345.678-9"
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Email para Comprobantes</label>
                        <input type="email" name="email_comprobantes" value={form.email_comprobantes} onChange={handleChange}
                            placeholder="Ej: pagos@urbanbox.cl"
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                    </div>

                    <button onClick={handleSave} disabled={saving}
                        className="w-full py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50">
                        {saving ? 'Guardando...' : '💾 Guardar'}
                    </button>
                </div>
            </div>
        </Layout>
    );
};

export default Configuracion;