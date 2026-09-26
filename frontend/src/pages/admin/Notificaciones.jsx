import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Inbox, Send, AlertTriangle, CalendarClock } from 'lucide-react';
import Layout from '../../components/Layout';
import api from '../../services/api';
import { KpiCard } from '../../components/kpis/KpiCard';
import { DataTable } from '../../components/kpis/DataTable';
import {
    ETIQUETAS, etiquetaDe, destinoDe, urlDestino,
} from '../../components/kpis/destinoNotificacion';

const LIMITE = 50;

const Notificaciones = () => {
    const navigate = useNavigate();
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [resumen, setResumen] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [reenviando, setReenviando] = useState(null);
    // Filtros server-side (el endpoint ya los soporta) + paginacion real.
    const [filtroTipo, setFiltroTipo] = useState('');
    const [filtroEstado, setFiltroEstado] = useState('');
    const [skip, setSkip] = useState(0);

    const cargar = useCallback(async () => {
        setLoading(true); setError('');
        try {
            const params = { limit: LIMITE, skip };
            if (filtroTipo) params.tipo = filtroTipo;
            if (filtroEstado) params.estado = filtroEstado;
            const r = await api.get('/api/v1/notificaciones-enviadas', { params });
            const data = r.data || {};
            setItems(data.items || []);
            setTotal(data.total || 0);
            setResumen(data.resumen || null);
        } catch (e) {
            setError('Error al cargar notificaciones: ' + (e.response?.data?.detail || e.message));
        } finally { setLoading(false); }
    }, [filtroTipo, filtroEstado, skip]);
    useEffect(() => { cargar(); }, [cargar]);
    // Al cambiar un filtro se vuelve a la primera pagina.
    useEffect(() => { setSkip(0); }, [filtroTipo, filtroEstado]);

    // Fila clickeable: cada tipo navega a su pantalla (destinoNotificacion.js).
    const irA = (n) => {
        const url = urlDestino(n.tipo, n.alumno_id);
        if (url) navigate(url);
    };

    const reenviar = async (id) => {
        setReenviando(id); setError('');
        try {
            await api.post(`/api/v1/notificaciones-enviadas/${id}/reenviar`, {});
            await cargar();
        } catch (e) {
            setError('Error al reenviar: ' + (e.response?.data?.detail || e.message));
        } finally { setReenviando(null); }
    };

    // Columnas estilo BI. La celda del alumno lleva un <button> (accesible +
    // ancla para los tests) y la fila entera tambien navega (onRowClick).
    const columnas = [
        {
            key: 'alumno_nombre', label: 'Destinatario',
            render: (v, row) => {
                // FIX cobertura: los correos al admin del box o a un lead no tienen
                // alumno. Se muestran igual, con el rol y sin link a la ficha.
                if (!row.alumno_id) {
                    const rol = row.destinatario_rol === 'administrador' ? 'Admin'
                        : row.destinatario_rol === 'lead' ? 'Lead' : null;
                    const badge = rol ? (
                        <span className="ml-2 rounded bg-zinc-700 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-zinc-300">
                            {rol}
                        </span>
                    ) : null;
                    return (
                        <span className="font-medium text-zinc-100">
                            {v}
                            {row.destinatario_correo && row.destinatario_correo !== v && (
                                <span className="ml-2 text-[11px] text-zinc-500">{row.destinatario_correo}</span>
                            )}
                            {badge}
                        </span>
                    );
                }
                const url = urlDestino(row.tipo, row.alumno_id);
                const d = destinoDe(row.tipo);
                if (!url) return <span className="font-medium text-zinc-100">{v}</span>;
                return (
                    <button
                        type="button"
                        onClick={() => irA(row)}
                        aria-label={`Ir a ${d?.label || 'el detalle'}: ${v}`}
                        className="text-left font-medium text-zinc-100 underline decoration-dotted transition hover:text-orange-300"
                    >
                        {v}
                    </button>
                );
            },
        },
        {
            key: 'tipo', label: 'Tipo',
            render: (v) => (
                <>
                    <span className="text-zinc-200">{etiquetaDe(v)}</span>
                    <span className="ml-2 text-[11px] text-zinc-500">{v}</span>
                </>
            ),
        },
        {
            key: 'fecha_envio', label: 'Fecha envío',
            render: (v) => (v ? String(v).slice(0, 19).replace('T', ' ') : '—'),
        },
        {
            key: 'estado', label: 'Estado',
            render: (v, row) => (
                <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium ${v === 'enviado'
                        ? 'border-green-300 bg-green-100 text-green-800'
                        : 'border-red-300 bg-red-100 text-red-800'}`}
                    title={v === 'fallido' ? (row.detalle_error || 'Sin detalle del error') : undefined}
                >
                    {v === 'enviado' ? '✅ Enviado' : '❌ Fallido'}
                </span>
            ),
        },
        {
            key: 'detalle_error', label: 'Error',
            render: (v) => (v
                ? <span className="text-xs text-red-300" title={v}>{String(v).slice(0, 70)}{String(v).length > 70 ? '…' : ''}</span>
                : <span className="text-zinc-600">—</span>),
        },
        {
            key: 'destino', label: 'Destino',
            render: (v, row) => {
                const d = destinoDe(row.tipo);
                return d?.label
                    ? <span className="text-xs text-zinc-400">{d.label} ↗</span>
                    : <span className="text-zinc-600">—</span>;
            },
        },
        {
            key: 'accion', label: 'Acción',
            render: (v, row) => (row.estado === 'fallido' ? (
                <button
                    type="button"
                    // stopPropagation: sin esto, el click en "Reenviar" también disparaba el
                    // onRowClick de la fila y te sacaba de la pantalla antes de ver el
                    // resultado del reenvío (el estado de la fila no se veía actualizar).
                    onClick={(e) => { e.stopPropagation(); reenviar(row.id); }}
                    disabled={reenviando === row.id}
                    className="rounded bg-orange-500 px-3 py-1.5 text-xs font-bold text-white hover:bg-orange-600 disabled:opacity-50"
                >
                    {reenviando === row.id ? '⏳ Reenviando…' : '↻ Reenviar'}
                </button>
            ) : null),
        },
    ];

    return (
        <Layout>
            <div className="space-y-6 p-6">
                <div>
                    <h1 className="text-2xl font-bold text-zinc-100">📨 Notificaciones Enviadas</h1>
                    <p className="mt-1 text-sm text-zinc-400">
                        Correos automáticos y manuales registrados. Clic en el alumno para ir a su
                        pantalla de gestión según el tipo.
                    </p>
                </div>
                {error && <div className="rounded-lg bg-red-100 p-4 font-bold text-red-800">{error}</div>}

                <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
                    <KpiCard label="Registros (con filtros)" value={total} icon={Inbox} color="border-blue-500" />
                    <KpiCard label="Enviados" value={resumen ? resumen.enviado : null} icon={Send} color="border-green-500" />
                    <KpiCard label="Fallidos" value={resumen ? resumen.fallido : null} icon={AlertTriangle} color="border-red-500" />
                    <KpiCard
                        label="Página"
                        value={`${Math.floor(skip / LIMITE) + 1} de ${Math.max(1, Math.ceil(total / LIMITE))}`}
                        icon={CalendarClock}
                        color="border-zinc-500"
                    />
                </div>

                <div className="flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-2 text-xs text-zinc-400">
                        Tipo
                        <select
                            value={filtroTipo}
                            onChange={(e) => setFiltroTipo(e.target.value)}
                            aria-label="Filtrar por tipo de notificación"
                            className="rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-xs text-white focus:border-orange-500 focus:outline-none"
                        >
                            <option value="">Todos</option>
                            {Object.keys(ETIQUETAS).map((t) => (
                                <option key={t} value={t}>{ETIQUETAS[t]}</option>
                            ))}
                        </select>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-zinc-400">
                        Estado
                        <select
                            value={filtroEstado}
                            onChange={(e) => setFiltroEstado(e.target.value)}
                            aria-label="Filtrar por estado de envío"
                            className="rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-xs text-white focus:border-orange-500 focus:outline-none"
                        >
                            <option value="">Todos</option>
                            <option value="enviado">Enviados</option>
                            <option value="fallido">Fallidos</option>
                        </select>
                    </label>
                    {(filtroTipo || filtroEstado) && (
                        <button
                            type="button"
                            onClick={() => { setFiltroTipo(''); setFiltroEstado(''); }}
                            className="rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-zinc-300 hover:bg-zinc-700/60"
                        >
                            Limpiar filtros
                        </button>
                    )}
                    {loading && <span className="text-xs text-zinc-500">Cargando…</span>}
                    <div className="ml-auto flex items-center gap-2">
                        <button
                            type="button"
                            disabled={skip === 0}
                            onClick={() => setSkip(Math.max(0, skip - LIMITE))}
                            className="rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-zinc-300 disabled:opacity-40"
                        >
                            ← Anterior
                        </button>
                        <span className="text-xs text-zinc-500">
                            {items.length ? `${skip + 1}-${skip + items.length} de ${total}` : 'sin resultados'}
                        </span>
                        <button
                            type="button"
                            disabled={skip + LIMITE >= total}
                            onClick={() => setSkip(skip + LIMITE)}
                            className="rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-zinc-300 disabled:opacity-40"
                        >
                            Siguiente →
                        </button>
                    </div>
                </div>

                <DataTable columns={columnas} data={items} onRowClick={(row) => irA(row)} />
            </div>
        </Layout>
    );
};
export default Notificaciones;