import React, { useState, useEffect } from 'react';
import api from '../services/api';

const INTERVALO_MS = 300000; // refresco cada 5 minutos

/**
 * Tarjeta del panel admin: "Alumnos de Prueba Hoy".
 *
 * Carga GET /api/v1/admin/alumnos-prueba-hoy al montar y cada 5 minutos, muestra
 * un resumen y permite expandir con detalle + filtro por estado de suscripción.
 */
const AdminTarjetaAlumnosPrueba = () => {
    const [alumnos, setAlumnos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [expandida, setExpandida] = useState(false);
    const [filtro, setFiltro] = useState('todos');

    const cargar = async () => {
        try {
            const { data } = await api.get('/api/v1/admin/alumnos-prueba-hoy');
            setAlumnos(data?.alumnos || []);
            setError('');
        } catch (err) {
            setError(err.response?.data?.detail || 'No se pudieron cargar los alumnos de prueba.');
            setAlumnos([]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        cargar();
        const id = setInterval(cargar, INTERVALO_MS);
        return () => clearInterval(id);
    }, []);

    const horaRegistro = (iso) => {
        if (!iso) return '—';
        try {
            return new Date(iso).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' });
        } catch {
            return '—';
        }
    };

    const colorEstado = (estado) => {
        switch (estado) {
            case 'activo': return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
            case 'vencido': return 'bg-red-500/20 text-red-300 border-red-500/30';
            case 'pendiente': return 'bg-amber-500/20 text-amber-300 border-amber-500/30';
            default: return 'bg-zinc-700/40 text-zinc-300 border-zinc-600';
        }
    };

    const visibles = filtro === 'todos'
        ? alumnos
        : alumnos.filter((a) => a.estado_suscripcion === filtro);

    const aMostrar = expandida ? visibles : visibles.slice(0, 3);

    return (
        <div className="bg-zinc-900 rounded-lg shadow p-5 border-l-4 border-orange-500">
            <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-3">
                    <span className="text-3xl">📊</span>
                    <div>
                        <p className="text-lg font-bold text-zinc-100">
                            {loading ? 'Cargando…' : `${alumnos.length} ${alumnos.length === 1 ? 'alumno' : 'alumnos'} de prueba hoy`}
                        </p>
                        <p className="text-xs text-zinc-500 mt-0.5">
                            Se registraron hoy y ya tienen su crédito de prueba (1 clase). Refresco automático cada 5 min.
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={cargar}
                        className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm transition-colors"
                    >
                        ⟳ Refrescar
                    </button>
                    {alumnos.length > 0 && (
                        <button
                            onClick={() => setExpandida((v) => !v)}
                            className="px-3 py-1.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold transition-colors"
                        >
                            {expandida ? 'Ver menos' : 'Ver más'}
                        </button>
                    )}
                </div>
            </div>

            {error && (
                <div className="mt-4 bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                    {error}
                </div>
            )}

            {!loading && !error && alumnos.length === 0 && (
                <p className="mt-4 text-sm text-zinc-500 italic">Sin registros de prueba hoy.</p>
            )}

            {aMostrar.length > 0 && (
                <div className="mt-4">
                    {expandida && (
                        <div className="mb-3 flex items-center gap-2">
                            <label className="text-xs text-zinc-400 uppercase tracking-wide">Estado:</label>
                            <select
                                value={filtro}
                                onChange={(e) => setFiltro(e.target.value)}
                                className="bg-zinc-800 border border-zinc-700 text-zinc-200 text-sm rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-orange-500/60"
                            >
                                <option value="todos">Todos</option>
                                <option value="activo">Activo</option>
                                <option value="pendiente">Pendiente</option>
                                <option value="vencido">Vencido</option>
                            </select>
                            <span className="text-xs text-zinc-500">{visibles.length} resultado(s)</span>
                        </div>
                    )}

                    <ul className="space-y-2">
                        {aMostrar.map((a) => (
                            <li key={a.id} className="flex items-center justify-between gap-3 bg-zinc-800/60 rounded-lg px-4 py-2.5">
                                <div className="min-w-0">
                                    <p className="text-sm font-semibold text-zinc-100 truncate">{a.nombre}</p>
                                    <p className="text-xs text-zinc-400 truncate">{a.correo}</p>
                                </div>
                                <div className="flex items-center gap-3 shrink-0">
                                    <span className="text-xs text-zinc-400">{horaRegistro(a.hora_registro)}</span>
                                    <span className={`text-[10px] font-semibold uppercase px-2 py-1 rounded-full border ${colorEstado(a.estado_suscripcion)}`}>
                                        {a.estado_suscripcion || '—'}
                                    </span>
                                </div>
                            </li>
                        ))}
                    </ul>

                    {!expandida && visibles.length > 3 && (
                        <button
                            onClick={() => setExpandida(true)}
                            className="mt-2 text-xs text-orange-400 hover:text-orange-300 underline underline-offset-2"
                        >
                            Ver los {visibles.length} alumnos
                        </button>
                    )}
                </div>
            )}
        </div>
    );
};

export default AdminTarjetaAlumnosPrueba;
