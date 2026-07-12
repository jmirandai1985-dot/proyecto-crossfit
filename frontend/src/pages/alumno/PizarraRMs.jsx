import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const CATEGORIA_META = {
    fuerza: { label: 'FUERZA', icon: '🏋️', color: 'emerald', bgClass: 'bg-emerald-50', textClass: 'text-emerald-700', borderClass: 'border-emerald-200' },
    gimnastico: { label: 'GIMNÁSTICO', icon: '🤸', color: 'blue', bgClass: 'bg-blue-50', textClass: 'text-blue-700', borderClass: 'border-blue-200' },
    cardio: { label: 'CARDIO', icon: '🏃', color: 'purple', bgClass: 'bg-purple-50', textClass: 'text-purple-700', borderClass: 'border-purple-200' },
    metabolico: { label: 'MÁQUINAS', icon: '⚙️', color: 'amber', bgClass: 'bg-amber-50', textClass: 'text-amber-700', borderClass: 'border-amber-200' },
};

const getCategoriaMeta = (cat) => CATEGORIA_META[cat] || CATEGORIA_META.fuerza;

// ─── Formatear resultado según categoría y campos disponibles ───────
const formatResultado = (rm, categoria) => {
    const partes = [];
    if (categoria === 'fuerza') {
        if (rm.peso_kg) partes.push(`${rm.peso_kg} kg`);
        if (rm.repeticiones) partes.push(`${rm.repeticiones} reps`);
        if (rm.series) partes.push(`${rm.series} series`);
        return partes.length > 0 ? partes.join(' x ') : `${rm.peso_kg || '?'} kg`;
    }
    if (categoria === 'gimnastico') {
        if (rm.repeticiones) partes.push(`${rm.repeticiones} reps`);
        if (rm.series) partes.push(`${rm.series} series`);
        return partes.length > 0 ? partes.join(' x ') : `${rm.peso_kg || '?'} reps`;
    }
    if (categoria === 'cardio') {
        if (rm.km) partes.push(`${rm.km} km`);
        if (rm.minutos) partes.push(`${rm.minutos} min`);
        if (rm.vueltas) partes.push(`${rm.vueltas} vueltas`);
        return partes.length > 0 ? partes.join(', ') : `${rm.peso_kg || '?'}`;
    }
    if (categoria === 'metabolico') {
        if (rm.calorias) partes.push(`${rm.calorias} cal`);
        if (rm.km) partes.push(`${rm.km} km`);
        if (rm.vueltas) partes.push(`${rm.vueltas} vueltas`);
        return partes.length > 0 ? partes.join(', ') : `${rm.peso_kg || '?'}`;
    }
    return `${rm.peso_kg || '?'}`;
};

const PizarraRMs = () => {
    const { usuario_id, tenant_id } = useAuth();
    const d = new Date();
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

    const [loading, setLoading] = useState(true);
    const [movimientos, setMovimientos] = useState([]);
    const [rms, setRms] = useState([]);
    const [rmTab, setRmTab] = useState('todas');
    const [fetchError, setFetchError] = useState('');
    const [showRMModal, setShowRMModal] = useState(false);
    const [rmForm, setRmForm] = useState({
        movimiento_id: '',
        peso_kg: '',
        repeticiones: '',
        series: '',
        minutos: '',
        vueltas: '',
        km: '',
        calorias: '',
        fecha: today,
        notas: ''
    });
    const [rmSubmitting, setRmSubmitting] = useState(false);
    const [rmError, setRmError] = useState('');
    const [successMsg, setSuccessMsg] = useState('');

    const fetchAll = useCallback(async () => {
        setLoading(true);
        try {
            const [movRes, rmsRes] = await Promise.all([
                api.get(`/api/v1/movimientos?tenant_id=${tenant_id}`),
                api.get(`/api/v1/historial-rm/alumnos/${usuario_id}/rms?tenant_id=${tenant_id}`)
            ]);
            setMovimientos(movRes.data || []);
            const bestRMs = rmsRes.data || [];
            const mappedRMs = bestRMs.map(r => ({
                ...r,
                id: r.id || r.movimiento_id,
                tipo_rm: r.tipo_rm || 'peso',
            }));
            setRms(mappedRMs);
        } catch (e) {
            console.error('Error fetching RMs:', e);
            setFetchError('No se pudieron cargar tus RMs. Verifica la conexión con el servidor e intenta de nuevo.');
        }
        setLoading(false);
    }, [usuario_id, tenant_id]);

    useEffect(() => { fetchAll(); }, [fetchAll]);

    const getCategoriaMovimiento = (movimientoId) => {
        const mov = movimientos.find(m => m.id === movimientoId);
        return mov?.categoria || 'fuerza';
    };

    // ─── Determinar qué campos mostrar según la categoría del movimiento seleccionado ──
    const categoriaSeleccionada = rmForm.movimiento_id ? getCategoriaMovimiento(Number(rmForm.movimiento_id)) : null;

    const handleRegistrarRM = async () => {
        setRmSubmitting(true);
        setRmError('');
        try {
            const cat = categoriaSeleccionada || 'fuerza';
            const payload = {
                tenant_id,
                alumno_id: usuario_id,
                movimiento_id: Number(rmForm.movimiento_id),
                peso_kg: cat === 'fuerza' ? (parseFloat(rmForm.peso_kg) || 1) : 1,
                fecha: rmForm.fecha || today,
                notas: rmForm.notas || null,
                repeticiones: rmForm.repeticiones ? parseInt(rmForm.repeticiones) : null,
                series: rmForm.series ? parseInt(rmForm.series) : null,
                minutos: rmForm.minutos ? parseInt(rmForm.minutos) : null,
                vueltas: rmForm.vueltas ? parseInt(rmForm.vueltas) : null,
                km: rmForm.km ? parseFloat(rmForm.km) : null,
                calorias: rmForm.calorias ? parseInt(rmForm.calorias) : null,
            };
            await api.post('/api/v1/historial-rm', payload);
            setShowRMModal(false);
            setSuccessMsg('🎉 RM registrado exitosamente!');
            setTimeout(() => setSuccessMsg(''), 3000);
            fetchAll();
        } catch (err) {
            setRmError(err.response?.data?.detail || 'Error al registrar RM');
        } finally {
            setRmSubmitting(false);
        }
    };

    const resetForm = () => {
        setRmForm({
            movimiento_id: '',
            peso_kg: '',
            repeticiones: '',
            series: '',
            minutos: '',
            vueltas: '',
            km: '',
            calorias: '',
            fecha: today,
            notas: ''
        });
        setRmError('');
    };

    const rmsFiltrados = rmTab === 'todas'
        ? rms
        : rms.filter(rm => getCategoriaMovimiento(rm.movimiento_id) === rmTab);

    // ─── RENDER ────────────────────────────────────────────────────────
    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-64">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500 mx-auto"></div>
                        <p className="mt-4 text-gray-500">Cargando RMs...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-6xl mx-auto space-y-6">
                {/* Header */}
                <div className="flex flex-col md:flex-row md:items-center md:justify-between">
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
                            💪 Pizarra de RMs y Leaderboard Comunitario
                        </h1>
                        <p className="text-gray-500 mt-1">Tus récords personales y rankings</p>
                    </div>
                    <button
                        onClick={() => { resetForm(); setShowRMModal(true); }}
                        className="mt-4 md:mt-0 px-5 py-2.5 bg-emerald-600 text-white rounded-xl font-bold text-sm hover:bg-emerald-700 transition-all flex items-center gap-2 shadow-sm"
                    >
                        <span>+</span> REGISTRAR NUEVA MARCA / RM
                    </button>
                </div>

                {successMsg && (
                    <div className="p-4 rounded-xl bg-green-50 border border-green-200 text-green-700 font-medium text-sm">
                        {successMsg}
                    </div>
                )}

                {fetchError && (
                    <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 font-medium text-sm">
                        ❌ {fetchError}
                    </div>
                )}

                {/* Filtros por categoría */}
                <div className="flex flex-wrap gap-2">
                    {[
                        { key: 'todas', label: '📋 Todos', activeClass: 'bg-gray-600 text-white' },
                        { key: 'fuerza', label: '🏋️ Fuerza', activeClass: 'bg-emerald-600 text-white' },
                        { key: 'gimnastico', label: '🤸 Gimnástico', activeClass: 'bg-blue-600 text-white' },
                        { key: 'cardio', label: '🏃 Cardio', activeClass: 'bg-purple-600 text-white' },
                        { key: 'metabolico', label: '⚙️ Máquinas', activeClass: 'bg-amber-600 text-white' },
                    ].map(t => (
                        <button
                            key={t.key}
                            onClick={() => setRmTab(t.key)}
                            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all ${rmTab === t.key
                                ? t.activeClass
                                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                                }`}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                {/* La Pizarra del Día / Ranking */}
                <div>
                    <h2 className="text-lg font-bold text-gray-800 mb-4">📊 LA PIZARRA DEL DÍA</h2>
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="bg-gray-50 border-b border-gray-200">
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Pos</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Atleta</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Ejercicio / WOD</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Resultado</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Modalidad</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                    {rmsFiltrados.length > 0 ? (
                                        rmsFiltrados.slice(0, 20).map((rm, idx) => {
                                            const cat = getCategoriaMovimiento(rm.movimiento_id);
                                            const meta = getCategoriaMeta(cat);
                                            const movName = movimientos.find(m => m.id === rm.movimiento_id)?.nombre || '—';
                                            const valorDisplay = formatResultado(rm, cat);
                                            return (
                                                <tr key={`${rm.id}-${idx}`} className="hover:bg-gray-50 transition-colors">
                                                    <td className="px-5 py-3.5 text-sm font-bold text-gray-400">#{idx + 1}</td>
                                                    <td className="px-5 py-3.5 text-sm font-medium text-gray-800">Tú</td>
                                                    <td className="px-5 py-3.5 text-sm text-gray-600">{movName}</td>
                                                    <td className="px-5 py-3.5">
                                                        <span className={`inline-flex px-2.5 py-1 rounded-lg text-xs font-bold ${meta.bgClass} ${meta.textClass}`}>
                                                            {valorDisplay}
                                                        </span>
                                                    </td>
                                                    <td className="px-5 py-3.5 text-sm text-gray-500">{meta.label}</td>
                                                </tr>
                                            );
                                        })
                                    ) : (
                                        <tr>
                                            <td colSpan="5" className="px-5 py-10 text-center">
                                                <p className="text-4xl mb-3">💪</p>
                                                <p className="text-gray-500 font-medium">No hay RMs registrados aún</p>
                                                <p className="text-gray-400 text-sm mt-1">Registra tu primera marca usando el botón superior</p>
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {/* Mi Evolución Reciente */}
                {rmsFiltrados.length > 0 && (
                    <div>
                        <h2 className="text-lg font-bold text-gray-800 mb-4">📈 MI EVOLUCIÓN RECIENTE</h2>
                        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead>
                                        <tr className="bg-gray-50 border-b border-gray-200">
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Fecha</th>
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Movimiento</th>
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Resultado</th>
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Notas</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {rmsFiltrados.slice(0, 15).map((rm, idx) => {
                                            const cat = getCategoriaMovimiento(rm.movimiento_id);
                                            const movName = movimientos.find(m => m.id === rm.movimiento_id)?.nombre || '—';
                                            const valorDisplay = formatResultado(rm, cat);
                                            return (
                                                <tr key={`hist-${rm.id}-${idx}`} className="hover:bg-gray-50 transition-colors">
                                                    <td className="px-5 py-3.5 text-sm text-gray-500">{rm.fecha || '—'}</td>
                                                    <td className="px-5 py-3.5 text-sm font-medium text-gray-800">{movName}</td>
                                                    <td className="px-5 py-3.5 text-sm font-bold text-emerald-600">{valorDisplay}</td>
                                                    <td className="px-5 py-3.5 text-sm text-gray-400 italic">{rm.notas || '—'}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* ─── MODAL REGISTRAR RM ─────────────────────────────────── */}
            {showRMModal && (
                <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
                    <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto">
                        <div className="bg-emerald-600 text-white px-6 py-4 rounded-t-xl flex justify-between items-center">
                            <h2 className="text-lg font-bold">📝 Registrar Nueva Marca</h2>
                            <button onClick={() => { setShowRMModal(false); setRmError(''); }} className="text-white/80 hover:text-white text-xl">✕</button>
                        </div>
                        <div className="p-6 space-y-5">
                            {/* Selección de movimiento por categoría */}
                            <div>
                                <label className="block text-sm font-semibold text-gray-700 mb-3">Selecciona un movimiento:</label>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                    {Object.entries(CATEGORIA_META).map(([catKey, catMeta]) => (
                                        <div key={catKey} className={`border ${catMeta.borderClass} rounded-xl p-2 ${catMeta.bgClass}`}>
                                            <p className={`text-[10px] font-bold uppercase tracking-widest mb-1.5 px-1 ${catMeta.textClass}`}>
                                                {catMeta.icon} {catMeta.label}
                                            </p>
                                            <div className="space-y-0.5 max-h-32 overflow-y-auto">
                                                {movimientos.filter(m => m.categoria === catKey).length === 0 && (
                                                    <p className="text-[10px] px-2 py-1.5 text-gray-400">Sin movimientos</p>
                                                )}
                                                {movimientos.filter(m => m.categoria === catKey).map(m => {
                                                    const sel = parseInt(rmForm.movimiento_id) === m.id;
                                                    return (
                                                        <button
                                                            key={m.id}
                                                            type="button"
                                                            onClick={() => setRmForm(prev => ({ ...prev, movimiento_id: m.id }))}
                                                            className={`w-full text-left px-2 py-1.5 rounded-lg text-[11px] font-bold transition-all ${sel ? 'bg-emerald-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200'
                                                                }`}
                                                        >
                                                            {m.nombre}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* ─── Campos específicos según categoría ─────────── */}
                            {categoriaSeleccionada && (
                                <div className="bg-gray-50 rounded-xl p-4 border border-gray-200">
                                    <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
                                        {CATEGORIA_META[categoriaSeleccionada]?.icon} Datos para {CATEGORIA_META[categoriaSeleccionada]?.label}
                                    </p>
                                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                                        {/* Fuerza: peso_kg + reps + series */}
                                        {(categoriaSeleccionada === 'fuerza') && (
                                            <>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Peso (kg) *</label>
                                                    <input type="number" step="0.1" min="0"
                                                        value={rmForm.peso_kg}
                                                        onChange={e => setRmForm(p => ({ ...p, peso_kg: e.target.value }))}
                                                        placeholder="Ej: 100"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Repeticiones</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.repeticiones}
                                                        onChange={e => setRmForm(p => ({ ...p, repeticiones: e.target.value }))}
                                                        placeholder="Ej: 5"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Series</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.series}
                                                        onChange={e => setRmForm(p => ({ ...p, series: e.target.value }))}
                                                        placeholder="Ej: 3"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                            </>
                                        )}
                                        {/* Gimnástico: reps + series */}
                                        {(categoriaSeleccionada === 'gimnastico') && (
                                            <>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Repeticiones *</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.repeticiones}
                                                        onChange={e => setRmForm(p => ({ ...p, repeticiones: e.target.value }))}
                                                        placeholder="Ej: 12"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Series</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.series}
                                                        onChange={e => setRmForm(p => ({ ...p, series: e.target.value }))}
                                                        placeholder="Ej: 3"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                            </>
                                        )}
                                        {/* Cardio: minutos + vueltas + km */}
                                        {(categoriaSeleccionada === 'cardio') && (
                                            <>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Minutos</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.minutos}
                                                        onChange={e => setRmForm(p => ({ ...p, minutos: e.target.value }))}
                                                        placeholder="Ej: 25"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Km</label>
                                                    <input type="number" step="0.1" min="0"
                                                        value={rmForm.km}
                                                        onChange={e => setRmForm(p => ({ ...p, km: e.target.value }))}
                                                        placeholder="Ej: 5"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Vueltas</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.vueltas}
                                                        onChange={e => setRmForm(p => ({ ...p, vueltas: e.target.value }))}
                                                        placeholder="Ej: 8"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                            </>
                                        )}
                                        {/* Máquinas: calorias + km + vueltas */}
                                        {(categoriaSeleccionada === 'metabolico') && (
                                            <>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Calorías</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.calorias}
                                                        onChange={e => setRmForm(p => ({ ...p, calorias: e.target.value }))}
                                                        placeholder="Ej: 500"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Km</label>
                                                    <input type="number" step="0.1" min="0"
                                                        value={rmForm.km}
                                                        onChange={e => setRmForm(p => ({ ...p, km: e.target.value }))}
                                                        placeholder="Ej: 5"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-600 mb-1">Vueltas</label>
                                                    <input type="number" min="0"
                                                        value={rmForm.vueltas}
                                                        onChange={e => setRmForm(p => ({ ...p, vueltas: e.target.value }))}
                                                        placeholder="Ej: 10"
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
                                                </div>
                                            </>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Fecha */}
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Fecha</label>
                                    <input type="date" value={rmForm.fecha}
                                        onChange={e => setRmForm(p => ({ ...p, fecha: e.target.value }))}
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Notas (opcional)</label>
                                    <input value={rmForm.notas}
                                        onChange={e => setRmForm(p => ({ ...p, notas: e.target.value }))}
                                        placeholder="Ej: PR personal"
                                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm" />
                                </div>
                            </div>

                            {rmError && (
                                <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
                                    ❌ {rmError}
                                </div>
                            )}

                            <div className="flex gap-3 pt-2">
                                <button onClick={() => { setShowRMModal(false); setRmError(''); }}
                                    className="flex-1 py-3 border border-gray-300 text-gray-700 rounded-xl font-bold text-sm hover:bg-gray-50 transition-colors">
                                    Cancelar
                                </button>
                                <button onClick={handleRegistrarRM}
                                    disabled={rmSubmitting || !rmForm.movimiento_id}
                                    className="flex-1 py-3 bg-emerald-600 text-white rounded-xl font-bold text-sm hover:bg-emerald-700 transition-colors disabled:opacity-50">
                                    {rmSubmitting ? '⏳ Guardando...' : '💪 GUARDAR RM'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </Layout>
    );
};

export default PizarraRMs;