import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const CAT_CONFIG = {
    fuerza: { label: 'Fuerza Máxima', color: '#3B82F6', icon: '💪' },
    gimnastico: { label: 'Gimnástico', color: '#10B981', icon: '🤸' },
    cardio: { label: 'Cardio', color: '#F97316', icon: '🧀' },
    metabolico: { label: 'Metabólico', color: '#8B5CF6', icon: '⚡' },
};

function inferirCategoria(rm) {
    if (rm.categoria && rm.categoria !== '') return rm.categoria;
    const n = (rm.movimiento_nombre || '').toLowerCase();
    // Keywords por categoria (orden: mas especifico primero)
    if (/sled|air.?runner|sandbag|farmer|carry/.test(n)) return 'metabolico';
    if (/run|row|ski.?erg|bike|assault/.test(n)) return 'cardio';
    if (/clean|snatch|jerk|deadlift|squat|press|thruster|dumbbell|kettlebell/.test(n)) return 'fuerza';
    if (/pull.?up|push.?up|burpee|muscle.?up|toes?.?to?.?bar|t2b|chest?.?to?.?bar|c2b|handstand|hspu|rope.?climb|pistol|doble.?under|double.?under|box.?jump|wall.?ball|bear.?crawl|kip|strict|ring|walk/.test(n)) return 'gimnastico';
    return rm.tipo_rm === 'cardio' ? 'cardio' : rm.tipo_rm === 'metabolico' ? 'metabolico' : 'fuerza';
}

function getValorNumerico(rm) {
    const cat = inferirCategoria(rm);
    if (cat === 'gimnastico') return Number(rm.repeticiones || rm.peso_kg || 0);
    if (cat === 'cardio' || cat === 'metabolico') return Number(rm.peso_kg || rm.calorias || rm.km || rm.minutos || 0);
    return Number(rm.peso_kg || 0);
}

function getUnidad(rm) {
    const cat = inferirCategoria(rm);
    if (cat === 'gimnastico') return 'reps';
    if (cat === 'cardio' || cat === 'metabolico') return '';
    return 'kg';
}

const PerformanceHub = () => {
    const { usuario_id } = useAuth();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [rms, setRms] = useState([]);
    const [catsData, setCatsData] = useState({});
    const [chartDataCat, setChartDataCat] = useState({});

    useEffect(() => {
        const fetchData = async () => {
            try {
                const rmsRes = await api.get(`/api/v1/historial-rm/alumnos/${usuario_id}/rms`);
                const rmsData = (rmsRes.data || []).map(rm => ({ ...rm, categoria: inferirCategoria(rm) }));
                setRms(rmsData);

                const allRes = await api.get(`/api/v1/historial-rm?limit=500`);
                const allRms = (allRes.data || []).map(rm => ({ ...rm, categoria: inferirCategoria(rm) }));

                const cats = { fuerza: [], gimnastico: [], cardio: [], metabolico: [] };
                rmsData.forEach(rm => {
                    const c = inferirCategoria(rm);
                    if (cats[c]) cats[c].push(getValorNumerico(rm));
                });
                const catsRes = {};
                Object.keys(cats).forEach(c => {
                    const arr = cats[c];
                    catsRes[c] = { valor: arr.length > 0 ? Math.max(...arr) : 0, count: arr.length };
                });
                setCatsData(catsRes);

                const byCat = { fuerza: [], gimnastico: [], cardio: [], metabolico: [] };
                allRms.forEach(rm => {
                    const c = inferirCategoria(rm);
                    if (byCat[c] && rm.fecha) {
                        try { byCat[c].push({ fecha: new Date(rm.fecha), valor: getValorNumerico(rm), nombre: rm.movimiento_nombre }); }
                        catch (e) { }
                    }
                });

                const chartRes = {};
                Object.keys(byCat).forEach(c => {
                    const items = byCat[c].sort((a, b) => a.fecha - b.fecha);
                    if (items.length < 2) { chartRes[c] = []; return; }
                    const weekMap = {};
                    items.forEach(item => {
                        const d = item.fecha, wk = getWeekKey(d);
                        if (!weekMap[wk] || item.valor > weekMap[wk].valor) weekMap[wk] = { valor: item.valor, nombre: item.nombre };
                    });
                    chartRes[c] = Object.entries(weekMap).sort(([a], [b]) => a.localeCompare(b)).map(([wk, v]) => ({ semana: wk, max: v.valor }));
                });
                setChartDataCat(chartRes);
            } catch (err) { console.error('Error:', err); }
            finally { setLoading(false); }
        };
        fetchData();
    }, [usuario_id]);

    if (loading) return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>);

    if (rms.length === 0) return (
        <Layout><div className="max-w-6xl mx-auto text-center py-16">
            <span className="text-7xl block mb-6">📊</span>
            <h2 className="text-xl font-bold text-gray-800 mb-3">Registra tu primer RM</h2>
            <p className="text-gray-500 max-w-md mx-auto mb-6">Para desbloquear tu perfil de atleta, comienza registrando tus marcas personales.</p>
            <a href="/alumno/rms" className="inline-block px-8 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm">Ir a Pizarra de RMs</a>
        </div></Layout>
    );

    const renderCuadrante = (cat) => {
        const cfg = CAT_CONFIG[cat];
        const data = catsData[cat] || {};
        const chart = chartDataCat[cat] || [];
        const tieneDatos = data.count > 0;
        return (
            <div key={cat} className="bg-white rounded-xl border p-4 shadow-sm" style={{ borderLeft: `4px solid ${cfg.color}` }}>
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2"><span>{cfg.icon}</span><span className="font-bold text-gray-800 text-xl">{cfg.label}</span></div>
                    {tieneDatos && <span className="text-4xl font-bold" style={{ color: cfg.color }}>{data.valor}<span className="text-base font-normal text-gray-400 ml-1">{cat === 'gimnastico' ? 'reps' : cat === 'fuerza' ? 'kg' : ''}</span></span>}
                </div>
                {tieneDatos && chart.length >= 2 ? (
                    <div style={{ height: 100 }}>
                        <ResponsiveContainer width="100%" height={100}>
                            <BarChart data={chart} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                                <XAxis dataKey="semana" tick={{ fontSize: 9 }} axisLine={false} tickLine={false} />
                                <YAxis hide domain={[0, 'dataMax + 10']} />
                                <Tooltip formatter={(v) => [`${v} ${cat === 'gimnastico' ? 'reps' : cat === 'fuerza' ? 'kg' : ''}`, cfg.label]} />
                                <Bar dataKey="max" fill={cfg.color} radius={[3, 3, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                ) : tieneDatos ? (
                    <div className="h-[100px] flex items-center justify-center text-gray-400 text-sm italic">Registra más RMs para ver tu evolución</div>
                ) : (
                    <div className="h-[100px] flex items-center justify-center text-gray-400 text-sm">Sin registros aún</div>
                )}
            </div>
        );
    };

    return (
        <Layout>
            <div className="max-w-6xl mx-auto">
                <div className="flex items-center gap-3 mb-6">
                    <span className="text-3xl">🏆</span>
                    <div><h1 className="text-2xl font-bold text-gray-800">Performance Hub</h1><p className="text-sm text-gray-500">Perfil completo de atleta basado en tus RMs</p></div>
                </div>
                <div className="space-y-6">
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div className="px-3 py-3 border-b border-gray-100"><h2 className="font-bold text-gray-800 text-xl">📋 Tus RMs</h2></div>
                        <div className="overflow-x-auto">
                            <table className="w-full" style={{ tableLayout: 'fixed' }}>
                                <thead><tr className="text-sm text-gray-500 uppercase bg-gray-50">
                                    <th className="px-2 py-2 text-left w-[30%]">Movimiento</th>
                                    <th className="px-1 py-2 text-center w-[12%]">RM</th>
                                    <th className="px-1 py-2 text-center w-[10%]">Ud.</th>
                                    <th className="px-1 py-2 text-center w-[10%]">Reps</th>
                                    <th className="px-1 py-2 text-center w-[10%]">Ser.</th>
                                    <th className="px-1 py-2 text-center w-[15%]">Fecha</th>
                                    <th className="px-2 py-2 text-left w-[13%]">Notas</th>
                                </tr></thead>
                                <tbody>{rms.map((rm, i) => {
                                    const mejor = Math.max(...rms.map(r => getValorNumerico(r)));
                                    const isPB = getValorNumerico(rm) === mejor;
                                    return (
                                        <tr key={rm.movimiento_id || i} onClick={() => navigate(`/alumno/evolucion?movimiento=${rm.movimiento_id}`)}
                                            className="border-t border-gray-100 hover:bg-emerald-50 cursor-pointer transition-colors">
                                            <td className="px-2 py-1.5 font-medium text-gray-800 text-base truncate">{rm.movimiento_nombre}{isPB && <span className="ml-0.5 text-amber-500 text-xs">⭐</span>}</td>
                                            <td className="px-1 py-1.5 text-center font-bold text-emerald-600 text-base">{getValorNumerico(rm) || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{getUnidad(rm) || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{rm.repeticiones || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{rm.series || '—'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-400 text-base">{rm.fecha ? formatFecha(rm.fecha) : '—'}</td>
                                            <td className="px-2 py-1.5 text-gray-400 italic text-base truncate max-w-0">{rm.notas || '—'}</td>
                                        </tr>
                                    );
                                })}</tbody>
                            </table>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        {Object.keys(CAT_CONFIG).map(cat => renderCuadrante(cat))}
                    </div>
                </div>
            </div>
        </Layout>
    );
};

function getWeekKey(d) {
    const start = new Date(d.getFullYear(), 0, 1);
    const diff = (d - start + (start.getTimezoneOffset() - d.getTimezoneOffset()) * 60000) / 86400000;
    return `S${Math.ceil((diff + start.getDay() + 1) / 7)}`;
}

function formatFecha(f) {
    try { const d = new Date(f); return `${String(d.getDate()).padStart(2, '0')}-${String(d.getMonth() + 1).padStart(2, '0')}`; }
    catch (e) { return f ? f.slice(5, 10) : '—'; }
}

export default PerformanceHub;