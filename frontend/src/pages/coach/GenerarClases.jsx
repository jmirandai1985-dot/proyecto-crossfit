import React, { useState } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const GenerarClases = () => {
    const { tenant_id } = useAuth();

    const [fecha, setFecha] = useState(new Date().toISOString().split('T')[0]);
    const [generando, setGenerando] = useState(false);
    const [resultado, setResultado] = useState(null);
    const [error, setError] = useState('');

    const handleGenerar = async () => {
        setGenerando(true);
        setResultado(null);
        setError('');
        try {
            const res = await api.post(
                `/api/v1/horarios/generar-clases-dia?tenant_id=${tenant_id}&fecha=${fecha}`
            );
            setResultado(res.data);
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al generar clases';
            setError(typeof detalle === 'string' ? detalle : 'Error desconocido');
        } finally {
            setGenerando(false);
        }
    };

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">⚡ Generar Clases del Día</h1>
                    <p className="text-gray-600 mt-1">
                        Crea todas las clases de un día desde el horario base semanal. No duplica si ya existen.
                    </p>
                </div>

                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <div className="flex items-end gap-4">
                        <div className="flex-1">
                            <label className="block text-sm font-medium text-gray-700 mb-1">Fecha</label>
                            <input
                                type="date"
                                value={fecha}
                                onChange={(e) => setFecha(e.target.value)}
                                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                            />
                        </div>
                        <button
                            onClick={handleGenerar}
                            disabled={generando}
                            className="px-6 py-2.5 bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-colors font-bold text-sm disabled:opacity-50 flex items-center gap-2"
                        >
                            {generando ? (
                                <><span className="animate-spin">⏳</span> Generando...</>
                            ) : (
                                <><span>⚡</span> Generar Clases</>
                            )}
                        </button>
                    </div>

                    {error && (
                        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                            ❌ {error}
                        </div>
                    )}

                    {resultado && (
                        <div className="mt-4 space-y-3">
                            <div className={`p-4 rounded-lg border text-sm ${resultado.creadas > 0
                                    ? 'bg-green-50 border-green-200 text-green-700'
                                    : 'bg-blue-50 border-blue-200 text-blue-700'
                                }`}>
                                <p className="font-medium">
                                    {resultado.creadas > 0 ? '✅' : 'ℹ️'} {resultado.message}
                                </p>
                            </div>
                            <div className="grid grid-cols-3 gap-3 text-sm">
                                <div className="bg-gray-50 rounded-lg p-3 text-center">
                                    <p className="text-2xl font-bold text-emerald-600">{resultado.creadas}</p>
                                    <p className="text-xs text-gray-500">Creadas</p>
                                </div>
                                <div className="bg-gray-50 rounded-lg p-3 text-center">
                                    <p className="text-2xl font-bold text-gray-500">{resultado.omitidas}</p>
                                    <p className="text-xs text-gray-500">Ya existían</p>
                                </div>
                                <div className="bg-gray-50 rounded-lg p-3 text-center">
                                    <p className="text-2xl font-bold text-gray-800">{resultado.total_horarios}</p>
                                    <p className="text-xs text-gray-500">Horarios base</p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
                    <p className="text-sm text-amber-800">
                        <strong>💡 Tip:</strong> Puedes usar esta página al inicio de cada día para generar
                        todas las clases automáticamente. Si ya existen, se omiten (no se duplican).
                    </p>
                </div>
            </div>
        </Layout>
    );
};

export default GenerarClases;