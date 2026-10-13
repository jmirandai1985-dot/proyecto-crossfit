import React, { useMemo, useState } from 'react';
import Layout from '../../components/Layout';
import ModalAvisoMarketing from '../../components/ModalAvisoMarketing';
import {
    useAvisosMarketing, useEliminarAviso, useGuardarAvisoMarketing, SIN_DATOS,
} from '../../hooks/queries';
import {
    aFormulario, acentoDeTipo, contarPorEstado, estadoVigencia, etiquetaTipo,
    formatearFechaCorta, payloadEdicion, resumenVigencia, tinteDeAcento,
} from '../../utils/avisosMarketing';

// Los 4 filtros son del BACKEND (`GET /marketing?filtro=`): "programado" (todavía
// no empieza) es tan importante como "vencido" para el admin.
const FILTROS = [
    { key: 'todos', label: 'Todos' },
    { key: 'vigentes', label: 'Al aire hoy' },
    { key: 'programados', label: 'Programados' },
    { key: 'vencidos', label: 'Terminados' },
];

const ESTADO_CHIP = {
    vigente: 'bg-green-500/15 text-green-400 border-green-500/30',
    programado: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    vencido: 'bg-zinc-800 text-zinc-500 border-zinc-700',
};
const ESTADO_LABEL = { vigente: 'Al aire', programado: 'Programado', vencido: 'Terminado' };

const Marketing = () => {
    const [filtro, setFiltro] = useState('todos');
    // La lista sale de la caché compartida `['marketing']`: el mismo prefijo que
    // invalida cada mutación (y el que mira el carrusel del alumno).
    const { data, isPending, error: errorQuery, refetch } = useAvisosMarketing(filtro);
    const avisos = data || SIN_DATOS;
    const eliminarAviso = useEliminarAviso();
    const guardarAviso = useGuardarAvisoMarketing();
    const [errorMsg, setErrorMsg] = useState('');
    const [ocupadoId, setOcupadoId] = useState(null);
    const [showModal, setShowModal] = useState(false);
    const [avisoEditar, setAvisoEditar] = useState(null);

    const error = errorMsg || (errorQuery ? 'No se pudieron cargar los avisos.' : '');
    // Los KPIs son del conjunto CARGADO (el filtro es del backend, así que "Al aire
    // hoy" con el filtro "Todos" es la foto real del box).
    const conteo = useMemo(() => contarPorEstado(avisos), [avisos]);

    const abrirNuevo = () => {
        setAvisoEditar(null);
        setShowModal(true);
    };

    const abrirEditar = (aviso) => {
        setAvisoEditar(aviso);
        setShowModal(true);
    };

    const alternarFijado = async (aviso) => {
        setOcupadoId(aviso.id);
        setErrorMsg('');
        try {
            // "Fijar arriba" es un PUT con el MISMO formulario del aviso y el flag
            // dado vuelta: el backend recibe el payload completo (no hay PATCH).
            const payload = payloadEdicion({
                ...aFormulario(aviso),
                fijado_arriba: !aviso.fijado_arriba,
            });
            await guardarAviso.mutateAsync({ id: aviso.id, payload });
        } catch (err) {
            console.error('Error fijando el aviso:', err);
            setErrorMsg('No se pudo cambiar el aviso de lugar en el carrusel.');
        } finally {
            setOcupadoId(null);
        }
    };

    const borrar = async (aviso) => {
        const esAutomatico = aviso.tipo === 'producto_bazar';
        const confirmacion = esAutomatico
            ? `¿Quitar el anuncio de "${aviso.producto_nombre || aviso.titulo}" del carrusel?\n(El producto sigue en el Bazar.)`
            : `¿Eliminar el aviso "${aviso.titulo}"?`;
        if (!window.confirm(confirmacion)) return;
        setOcupadoId(aviso.id);
        setErrorMsg('');
        try {
            await eliminarAviso.mutateAsync(aviso.id);
        } catch (err) {
            console.error('Error eliminando el aviso:', err);
            setErrorMsg('No se pudo eliminar el aviso.');
        } finally {
            setOcupadoId(null);
        }
    };

    if (isPending) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-64">
                    <div className="animate-spin rounded-full h-10 w-10 border-4 border-orange-500 border-t-transparent"></div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                {/* ── Encabezado ── */}
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl font-extrabold text-zinc-100">Marketing — Avisos del Inicio</h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            El carrusel "Novedades del box" que ve el alumno al abrir la app.
                            Fuera de su vigencia, un aviso no se muestra.
                        </p>
                    </div>
                    <button
                        onClick={abrirNuevo}
                        className="flex items-center gap-1.5 bg-orange-500 hover:bg-orange-600 text-white font-bold text-sm px-4 py-2.5 rounded-xl shadow-lg shadow-orange-500/25 transition-colors"
                    >
                        <span>+</span> Nuevo aviso
                    </button>
                </div>

                {/* ── 4 tarjetas: la foto de hoy ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-6">
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-green-500"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Al aire hoy</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{conteo.vigentes}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">se están mostrando en el Inicio</div>
                    </div>
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-amber-500"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Programados</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{conteo.programados}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">empiezan más adelante</div>
                    </div>
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-zinc-600"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Terminados</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{conteo.vencidos}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">ya salieron del carrusel</div>
                    </div>
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-orange-500"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Fijados arriba</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{conteo.fijados}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">van primero en el carrusel</div>
                    </div>
                </div>

                {error && (
                    <div className="mb-4 rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-[13px] text-red-200">
                        ⚠️ {error}
                        {errorQuery && (
                            <button onClick={() => refetch()} className="ml-3 underline font-semibold">
                                Reintentar
                            </button>
                        )}
                    </div>
                )}

                {/* ── Filtros (los aplica el backend) ── */}
                <div className="flex flex-wrap gap-2 mb-4">
                    {FILTROS.map((f) => {
                        const activo = filtro === f.key;
                        return (
                            <button
                                key={f.key}
                                onClick={() => setFiltro(f.key)}
                                className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-colors ${activo
                                    ? 'bg-orange-500/15 border-orange-500/40 text-orange-500'
                                    : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-zinc-200'}`}
                            >
                                {f.label}
                            </button>
                        );
                    })}
                </div>

                {/* ── Tabla ── */}
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-left text-[11.5px] uppercase tracking-wide text-zinc-500 border-b border-zinc-800">
                                    <th className="px-4 py-3 font-semibold">Aviso</th>
                                    <th className="px-4 py-3 font-semibold">Ventana</th>
                                    <th className="px-4 py-3 font-semibold">Estado</th>
                                    <th className="px-4 py-3 font-semibold">Carrusel</th>
                                    <th className="px-4 py-3 font-semibold text-right">Acciones</th>
                                </tr>
                            </thead>
                            <tbody>
                                {avisos.length > 0 ? (
                                    avisos.map((aviso) => {
                                        const acento = acentoDeTipo(aviso.tipo);
                                        const estado = estadoVigencia(aviso);
                                        const automatico = aviso.tipo === 'producto_bazar';
                                        const pie = resumenVigencia(aviso);
                                        return (
                                            <tr key={aviso.id} className="border-b border-zinc-800/60 last:border-0 align-top">
                                                <td className="px-4 py-3.5 max-w-[420px]">
                                                    <span
                                                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10.5px] font-bold uppercase tracking-wide"
                                                        style={{ backgroundColor: tinteDeAcento(acento), color: acento }}
                                                    >
                                                        {etiquetaTipo(aviso.tipo)}
                                                    </span>
                                                    {aviso.fijado_arriba && (
                                                        <span className="ml-2 text-[10.5px] text-orange-400 font-bold">★ Fijado</span>
                                                    )}
                                                    {/* Un aviso automático muestra el nombre ACTUAL del
                                                        producto: el título guardado puede haber quedado
                                                        viejo si el producto se renombró. */}
                                                    <div className="text-zinc-100 font-semibold mt-1.5">
                                                        {automatico ? (aviso.producto_nombre || aviso.titulo) : aviso.titulo}
                                                    </div>
                                                    {aviso.texto && (
                                                        <div className="text-zinc-500 text-[12.5px] mt-0.5 line-clamp-2">{aviso.texto}</div>
                                                    )}
                                                    {aviso.nombre_aliado && (
                                                        <div className="text-[11.5px] text-green-400 font-semibold mt-1">{aviso.nombre_aliado}</div>
                                                    )}
                                                    {automatico && (
                                                        <div className="text-[11.5px] text-blue-400 mt-1">
                                                            Automático del Bazar
                                                            {aviso.producto_nombre ? `: ${aviso.producto_nombre}` : ''}
                                                        </div>
                                                    )}
                                                </td>
                                                <td className="px-4 py-3.5 text-zinc-300 whitespace-nowrap">
                                                    {formatearFechaCorta(aviso.vigente_desde)} → {formatearFechaCorta(aviso.vigente_hasta)}
                                                    {pie && <div className="text-[11.5px] text-zinc-500 mt-0.5">{pie}</div>}
                                                </td>
                                                <td className="px-4 py-3.5">
                                                    <span className={`px-2.5 py-1 rounded-full border text-[11px] font-semibold ${ESTADO_CHIP[estado]}`}>
                                                        {ESTADO_LABEL[estado]}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3.5 text-zinc-400">
                                                    {automatico
                                                        ? '—'
                                                        : (aviso.fijado_arriba ? 'Primero' : 'Orden normal')}
                                                </td>
                                                {/* Acciones: fijar y editar son de los avisos
                                                    manuales; el del producto lo mantiene el Bazar
                                                    (de ese sólo se puede quitar el anuncio). */}
                                                <td className="px-4 py-3.5">
                                                    <div className="flex items-center justify-end gap-2">
                                                        {!automatico && (
                                                            <>
                                                                <button
                                                                    onClick={() => alternarFijado(aviso)}
                                                                    disabled={ocupadoId === aviso.id}
                                                                    title={aviso.fijado_arriba ? 'Sacar de arriba' : 'Fijar arriba del carrusel'}
                                                                    className="h-8 px-2.5 rounded-lg border border-zinc-700 bg-zinc-800 text-[11px] font-bold text-zinc-400 hover:border-orange-500 hover:text-orange-400 transition-colors disabled:opacity-50"
                                                                >
                                                                    {aviso.fijado_arriba ? '☆ Desfijar' : '★ Fijar'}
                                                                </button>
                                                                <button
                                                                    onClick={() => abrirEditar(aviso)}
                                                                    title="Editar aviso"
                                                                    className="h-8 px-2.5 rounded-lg border border-zinc-700 bg-zinc-800 text-[11px] font-bold text-zinc-400 hover:border-blue-500 hover:text-blue-400 transition-colors"
                                                                >
                                                                    Editar
                                                                </button>
                                                            </>
                                                        )}
                                                        <button
                                                            onClick={() => borrar(aviso)}
                                                            disabled={ocupadoId === aviso.id}
                                                            title={automatico ? 'Quitar el anuncio (el producto sigue en el Bazar)' : 'Eliminar aviso'}
                                                            aria-label="Eliminar aviso"
                                                            className="w-8 h-8 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-400 hover:border-red-500 hover:text-red-500 transition-colors disabled:opacity-50"
                                                        >
                                                            🗑
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })
                                ) : (
                                    <tr>
                                        <td colSpan={5} className="px-4 py-10 text-center">
                                            <p className="text-zinc-500 text-sm">
                                                {error || (filtro === 'todos'
                                                    ? 'Todavía no hay avisos: el Inicio del alumno no muestra la sección.'
                                                    : 'No hay avisos con ese filtro.')}
                                            </p>
                                            <button
                                                onClick={abrirNuevo}
                                                className="mt-3 px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-bold"
                                            >
                                                + Crear el primer aviso
                                            </button>
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>

                <p className="text-[12px] text-zinc-500 mt-4">
                    Las tarjetas de <strong className="text-zinc-300">producto nuevo</strong> no se crean acá:
                    las genera el Bazar al publicar un producto con días de anuncio (y muestran su foto y su precio reales).
                </p>

                <ModalAvisoMarketing
                    isOpen={showModal}
                    onClose={() => { setShowModal(false); setAvisoEditar(null); }}
                    onSuccess={() => { setShowModal(false); setAvisoEditar(null); }}
                    avisoEditar={avisoEditar}
                />
            </div>
        </Layout>
    );
};

export default Marketing;
