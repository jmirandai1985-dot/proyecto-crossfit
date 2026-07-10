import React, { useState } from 'react';
import { Building2, User, CheckCircle2, ArrowRight } from 'lucide-react';
import { tenantsAPI, usuariosAPI } from '../services/api';

export default function Setup({ onComplete, existingTenantId }) {
    const [step, setStep] = useState(existingTenantId ? 2 : 1);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState(false);

    // Datos del tenant
    const [tenantData, setTenantData] = useState({
        nombre: '',
        subdomain: ''
    });

    // Datos del administrador
    const [adminData, setAdminData] = useState({
        rut: '',
        nombre: '',
        telefono: '',
        correo: '',
        password: ''
    });

    const [createdTenantId, setCreatedTenantId] = useState(existingTenantId || null);

    const handleTenantSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        try {
            const tenant = await tenantsAPI.create(tenantData);
            setCreatedTenantId(tenant.id);
            setStep(2);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleAdminSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        try {
            await usuariosAPI.create({
                tenant_id: createdTenantId,
                ...adminData,
                rol: 'administrador'
            });
            setSuccess(true);
            setTimeout(() => {
                if (onComplete) {
                    onComplete(createdTenantId);
                }
            }, 2000);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    if (success) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-emerald-50 to-blue-50 flex items-center justify-center p-4">
                <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full text-center">
                    <div className="h-16 w-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <CheckCircle2 className="h-8 w-8 text-emerald-600" />
                    </div>
                    <h2 className="text-2xl font-bold text-gray-900 mb-2">¡Configuración Completada!</h2>
                    <p className="text-gray-600">Tu box ha sido creado exitosamente</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-emerald-50 to-blue-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-2xl shadow-xl p-8 max-w-2xl w-full">
                {/* Header */}
                <div className="text-center mb-8">
                    <h1 className="text-3xl font-bold text-gray-900 mb-2">Configuración Inicial</h1>
                    <p className="text-gray-600">Configura tu box en 2 simples pasos</p>
                </div>

                {/* Progress Steps */}
                <div className="flex items-center justify-center mb-8">
                    <div className="flex items-center">
                        <div className={`flex items-center justify-center h-10 w-10 rounded-full ${step >= 1 ? 'bg-emerald-600 text-white' : 'bg-gray-200 text-gray-600'}`}>
                            <Building2 className="h-5 w-5" />
                        </div>
                        <div className="text-xs font-semibold ml-2 mr-4">Crear Box</div>
                    </div>
                    <div className={`h-1 w-16 ${step >= 2 ? 'bg-emerald-600' : 'bg-gray-200'}`}></div>
                    <div className="flex items-center ml-4">
                        <div className={`flex items-center justify-center h-10 w-10 rounded-full ${step >= 2 ? 'bg-emerald-600 text-white' : 'bg-gray-200 text-gray-600'}`}>
                            <User className="h-5 w-5" />
                        </div>
                        <div className="text-xs font-semibold ml-2">Crear Admin</div>
                    </div>
                </div>

                {/* Error Message */}
                {error && (
                    <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6">
                        {error}
                    </div>
                )}

                {/* Step 1: Crear Tenant */}
                {step === 1 && (
                    <form onSubmit={handleTenantSubmit} className="space-y-6">
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-2">
                                Nombre del Box
                            </label>
                            <input
                                type="text"
                                required
                                value={tenantData.nombre}
                                onChange={(e) => setTenantData({ ...tenantData, nombre: e.target.value })}
                                className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                placeholder="Ej: CrossFit Santiago Centro"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-2">
                                Subdominio
                            </label>
                            <div className="flex items-center">
                                <input
                                    type="text"
                                    required
                                    value={tenantData.subdomain}
                                    onChange={(e) => setTenantData({ ...tenantData, subdomain: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') })}
                                    className="flex-1 px-4 py-3 border border-gray-300 rounded-l-xl focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    placeholder="santiago-centro"
                                />
                                <span className="px-4 py-3 bg-gray-100 border border-l-0 border-gray-300 rounded-r-xl text-gray-600">
                                    .tuapp.com
                                </span>
                            </div>
                            <p className="text-xs text-gray-500 mt-1">Solo letras minúsculas, números y guiones</p>
                        </div>

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full bg-emerald-600 text-white font-bold py-3 px-4 rounded-xl hover:bg-emerald-700 transition-all flex items-center justify-center space-x-2 disabled:opacity-50"
                        >
                            <span>{loading ? 'Creando...' : 'Continuar'}</span>
                            <ArrowRight className="h-5 w-5" />
                        </button>
                    </form>
                )}

                {/* Step 2: Crear Administrador */}
                {step === 2 && (
                    <form onSubmit={handleAdminSubmit} className="space-y-6">
                        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4 mb-6">
                            <p className="text-sm text-emerald-800">
                                <strong>Box creado:</strong> {tenantData.nombre}
                            </p>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-2">
                                    RUT
                                </label>
                                <input
                                    type="text"
                                    required
                                    value={adminData.rut}
                                    onChange={(e) => setAdminData({ ...adminData, rut: e.target.value })}
                                    className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    placeholder="12345678-9"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-2">
                                    Nombre Completo
                                </label>
                                <input
                                    type="text"
                                    required
                                    value={adminData.nombre}
                                    onChange={(e) => setAdminData({ ...adminData, nombre: e.target.value })}
                                    className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    placeholder="Juan Pérez"
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-2">
                                    Teléfono
                                </label>
                                <input
                                    type="tel"
                                    value={adminData.telefono}
                                    onChange={(e) => setAdminData({ ...adminData, telefono: e.target.value })}
                                    className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    placeholder="+56912345678"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-2">
                                    Correo Electrónico
                                </label>
                                <input
                                    type="email"
                                    required
                                    value={adminData.correo}
                                    onChange={(e) => setAdminData({ ...adminData, correo: e.target.value })}
                                    className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    placeholder="admin@box.com"
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-2">
                                Contraseña
                            </label>
                            <input
                                type="password"
                                required
                                value={adminData.password}
                                onChange={(e) => setAdminData({ ...adminData, password: e.target.value })}
                                className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                placeholder="Mínimo 8 caracteres"
                                minLength={8}
                            />
                        </div>

                        <div className="flex space-x-4">
                            <button
                                type="button"
                                onClick={() => setStep(1)}
                                className="flex-1 bg-gray-200 text-gray-700 font-bold py-3 px-4 rounded-xl hover:bg-gray-300 transition-all"
                            >
                                Atrás
                            </button>
                            <button
                                type="submit"
                                disabled={loading}
                                className="flex-1 bg-emerald-600 text-white font-bold py-3 px-4 rounded-xl hover:bg-emerald-700 transition-all flex items-center justify-center space-x-2 disabled:opacity-50"
                            >
                                <span>{loading ? 'Creando...' : 'Finalizar'}</span>
                                <CheckCircle2 className="h-5 w-5" />
                            </button>
                        </div>
                    </form>
                )}
            </div>
        </div>
    );
}
