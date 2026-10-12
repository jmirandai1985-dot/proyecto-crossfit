import React from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import Layout from '../../components/Layout';
import AvisoCarga from '../../components/AvisoCarga';
import BotonVolver from '../../components/BotonVolver';
import { useAuth } from '../../context/AuthContext';
// Fase 2 (Bloque 1): los datos salen de la cachÃƒÂ© compartida (`hooks/queries.js`), la
// MISMA que usan la Pizarra de RMs y EvoluciÃƒÂ³n.
import { useHistorialRmTodos, useRmsAlumno } from '../../hooks/queries';
// H-03: la categorÃƒÂ­a/valor de un RM salen de una ÃƒÂºnica fuente (utils/rm.js).
// Antes estas 3 funciones vivÃƒÂ­an acÃƒÂ¡ y habÃƒÂ­a otra copia en EvoluciÃƒÂ³n y otra en la Pizarra.
import {
    inferirCategoriaRM as inferirCategoria,
    valorRM as getValorNumerico,
    unidadRM as getUnidad,
} from '../../utils/rm';
// TZ Chile: fechas de los RMs en el calendario chileno.
import { fmtFechaCortaChile } from '../../utils/fecha';

const CAT_CONFIG = {
    fuerza: { label: 'Fuerza MÃƒÂ¡xima', color: '#3B82F6', icon: 'Ã°Å¸â€™Âª' },
    gimnastico: { label: 'GimnÃƒÂ¡stico', color: '#10B981', icon: 'Ã°Å¸Â¤Â¸' },
    cardio: { label: 'Cardio', color: '#F97316', icon: 'Ã°Å¸Â§â‚¬' },
    metabolico: { label: 'MetabÃƒÂ³lico', color: '#8B5CF6', icon: 'Ã¢Å¡Â¡' },
};


const PerformanceHub = () => {
    const { usuario_id } = useAuth();
    const navigate = useNavigate();

    // Fase 2 (Bloque 1): las DOS consultas son del PROPIO alumno y viven en la cachÃƒÂ©
    // compartida; los cuadrantes y las series semanales se DERIVAN de esos datos (antes
    // se recalculaban dentro del fetch y se guardaban en estado, asÃƒÂ­ que cualquier
    // re-render los volvÃƒÂ­a a escribir).
    //
    // N-4: `/historial-rm/alumnos/{id}/rms` trae sus RMs y `/historial-rm?limit=500`
    // (sin filtro de alumno) tambiÃƒÂ©n devuelve sÃƒÂ³lo los suyos cuando quien consulta es un
    // alumno (scoping por JWT). Es el perfil del atleta, no un tablero del box.
    const rmsQ = useRmsAlumno(usuario_id);
    const historialQ = useHistorialRmTodos(500);

    const rms = React.useMemo(
        () => (rmsQ.data || []).map(rm => ({ ...rm, categoria: inferirCategoria(rm) })),
        [rmsQ.data],
    );

    // Cuadrantes: mejor valor de cada categorÃƒÂ­a y cuÃƒÂ¡ntas marcas hay.
    const catsData = React.useMemo(() => {
        const cats = { fuerza: [], gimnastico: [], cardio: [], metabolico: [] };
        rms.forEach(rm => {
            const c = inferirCategoria(rm);
            if (cats[c]) cats[c].push(getValorNumerico(rm));
        });
        const catsRes = {};
        Object.keys(cats).forEach(c => {
            const arr = cats[c];
            catsRes[c] = { valor: arr.length > 0 ? Math.max(...arr) : 0, count: arr.length };
        });
        return catsRes;
    }, [rms]);

    // N-5: acÃƒÂ¡ habÃƒÂ­a un `catch (e) { }` VACÃƒÂO. Cualquier fallo al armar la serie semanal
    // se perdÃƒÂ­a en silencio y el grÃƒÂ¡fico salÃƒÂ­a incompleto sin avisar. Ahora se registra
    // en consola y se reporta en el banner de la pantalla (`erroresCarga`).
    // Ojo: una `fecha` ilegible NO lanza excepciÃƒÂ³n (`new Date('x')` da `Invalid Date`),
    // y eso rompÃƒÂ­a el orden y las semanas del grÃƒÂ¡fico en silencio, asÃƒÂ­ que tambiÃƒÂ©n se
    // descarta y se reporta acÃƒÂ¡.
    const { chartDataCat, descartados } = React.useMemo(() => {
        const byCat = { fuerza: [], gimnastico: [], cardio: [], metabolico: [] };
        const descartadosRes = [];
        (historialQ.data || []).forEach(rm => {
            const c = inferirCategoria(rm);
            if (!byCat[c] || !rm.fecha) return;
            try {
                const fecha = new Date(rm.fecha);
                if (Number.isNaN(fecha.getTime())) {
                    throw new Error(`fecha invÃƒÂ¡lida: ${rm.fecha}`);
                }
                byCat[c].push({ fecha, valor: getValorNumerico(rm), nombre: rm.movimiento_nombre });
            } catch (e) {
                console.error('RM descartado de la evoluciÃƒÂ³n semanal:', rm?.movimiento_nombre, rm?.fecha, e);
                descartadosRes.push(rm);
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
        return { chartDataCat: chartRes, descartados: descartadosRes };
    }, [historialQ.data]);

    // "Cargando" sÃƒÂ³lo mientras NO hay dato: al volver a la pantalla se pinta la copia en
    // cachÃƒÂ© al instante (misma queryKey que las otras pantallas de RMs).
    const loading = rmsQ.isPending || historialQ.isPending;

    const erroresCarga = React.useMemo(() => {
        const fallaron = [];
        if (rmsQ.isError) fallaron.push('mis RMs');
        if (historialQ.isError) fallaron.push('tu historial de RMs');
        if (descartados.length > 0) {
            fallaron.push(`evoluciÃƒÂ³n de RMs (${descartados.length} registro/s con fecha o valor invÃƒÂ¡lido)`);
        }
        return fallaron;
    }, [rmsQ.isError, historialQ.isError, descartados]);

    // Reintentar = volver a pedir las dos (mismo botÃƒÂ³n del banner de antes).
    const cargarTodo = () => {
        rmsQ.refetch();
        historialQ.refetch();
    };

    if (loading) return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>);

    if (rms.length === 0 && erroresCarga.length === 0) return (
        <Layout><div className="max-w-6xl mx-auto text-center py-16">
            <span className="text-7xl block mb-6">Ã°Å¸â€œÅ </span>
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
                    <div className="h-[100px] flex items-center justify-center text-gray-400 text-sm italic">Registra mÃƒÂ¡s RMs para ver tu evoluciÃƒÂ³n</div>
                ) : (
                    <div className="h-[100px] flex items-center justify-center text-gray-400 text-sm">Sin registros aÃƒÂºn</div>
                )}
            </div>
        );
    };

    return (
        <Layout>
            <div className="max-w-6xl mx-auto">
                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

                <div className="flex items-center gap-3 mb-6">
                    <BotonVolver />
                    <span className="text-3xl">Ã°Å¸Ââ€ </span>
                    <div><h1 className="text-2xl font-bold text-gray-800">Performance Hub</h1><p className="text-sm text-gray-500">Perfil completo de atleta basado en tus RMs</p></div>
                </div>
                <div className="space-y-6">
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div className="px-3 py-3 border-b border-gray-100"><h2 className="font-bold text-gray-800 text-xl">Ã°Å¸â€œâ€¹ Tus RMs</h2></div>
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
                                            <td className="px-2 py-1.5 font-medium text-gray-800 text-base truncate">{rm.movimiento_nombre}{isPB && <span className="ml-0.5 text-amber-500 text-xs">Ã¢Â­Â</span>}</td>
                                            <td className="px-1 py-1.5 text-center font-bold text-emerald-600 text-base">{getValorNumerico(rm) || 'Ã¢â‚¬â€'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{getUnidad(rm) || 'Ã¢â‚¬â€'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{rm.repeticiones || 'Ã¢â‚¬â€'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-500 text-base">{rm.series || 'Ã¢â‚¬â€'}</td>
                                            <td className="px-1 py-1.5 text-center text-gray-400 text-base">{rm.fecha ? formatFecha(rm.fecha) : 'Ã¢â‚¬â€'}</td>
                                            <td className="px-2 py-1.5 text-gray-400 italic text-base truncate max-w-0">{rm.notas || 'Ã¢â‚¬â€'}</td>
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

// TZ Chile: las fechas de los RMs llegan como 'YYYY-MM-DD'; se formatean en el
// calendario chileno (con new Date(f) a medianoche UTC la fecha se corrÃƒÂ­a un dÃƒÂ­a).
function formatFecha(f) {
    return fmtFechaCortaChile(f) || 'Ã¢â‚¬â€';
}

export default PerformanceHub;
