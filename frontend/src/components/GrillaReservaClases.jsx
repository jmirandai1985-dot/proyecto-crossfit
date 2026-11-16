import React, { useEffect, useState } from 'react';
import { separarClasesPorFranja } from '../utils/grillaReserva';

// Título con el que la sección se veía en el Inicio del alumno.
const TITULO_POR_DEFECTO = 'CLASES DISPONIBLES — PRÓXIMOS 7 DÍAS';

/**
 * Grilla para TOMAR una clase (selector de día + horarios + botón Reservar).
 * Es la MISMA que vivía inline en `pages/alumno/Dashboard.jsx` (Inicio ≥768px) y
 * ahora también la monta `pages/alumno/AgendarReserva.jsx`.
 *
 * Genérica: no consulta la API ni conoce el rol. Recibe los días, las clases ya
 * agrupadas por día y `onReservar(clase)`. La confirmación vive en
 * `ModalConfirmarReserva` (mismo módulo).
 */
const GrillaReservaClases = ({
    proximosDias = [],
    clasesPorDia = {},
    onReservar,
    titulo = TITULO_POR_DEFECTO,
    cargando = false,
    className = '',
}) => {
    const [diaExpandido, setDiaExpandido] = useState(null);
    const [disciplinaFiltro, setDisciplinaFiltro] = useState('Todos');
    const [seccionesExpandidas, setSeccionesExpandidas] = useState({ manana: false, tarde: false });

    // Primer día de la semana con al menos una clase.
    const primerDiaDisponible = (() => {
        for (const dia of proximosDias) {
            if ((clasesPorDia[dia.fecha] || []).length > 0) return dia.fecha;
        }
        return null;
    })();

    // Al cambiar de día, cerrar Mañana/Tarde (mismo comportamiento del Inicio).
    useEffect(() => {
        setSeccionesExpandidas({ manana: false, tarde: false });
    }, [diaExpandido]);

    // Con los datos cargados, abrir el primer día disponible.
    useEffect(() => {
        if (!cargando && diaExpandido === null && primerDiaDisponible) {
            setDiaExpandido(primerDiaDisponible);
        }
    }, [cargando, primerDiaDisponible, diaExpandido]);

    const abrirReserva = (clase) => onReservar?.(clase);

    return (
        <div className={className}>
            <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
                <span>📋</span> {titulo}
            </h2>

            {/* ── FILA DE BOTONES (uno por día) ── */}
            <div className="flex flex-wrap gap-2 mb-4">
                {proximosDias.map(({ fecha, nombreDia, diaNum }) => {
                    const clasesDelDia = clasesPorDia[fecha] || [];
                    const tieneClases = clasesDelDia.length > 0;
                    const estaExpandido = diaExpandido === fecha;
                    const esPrimerDisponible = primerDiaDisponible === fecha;
                    const nombreCorto = nombreDia.substring(0, 3);

                    return (
                        <button
                            key={fecha}
                            onClick={() => setDiaExpandido(estaExpandido ? null : fecha)}
                            className={`
                                px-4 py-2.5 rounded-xl text-sm font-bold transition-all border-2
                                ${estaExpandido
                                    ? 'bg-emerald-500 text-white border-emerald-500 shadow-md'
                                    : tieneClases
                                        ? esPrimerDisponible
                                            ? 'bg-amber-50 text-amber-700 border-amber-300 hover:bg-amber-100'
                                            : 'bg-white text-gray-700 border-gray-200 hover:border-emerald-300 hover:bg-emerald-50'
                                        : 'bg-gray-100 text-gray-400 border-gray-200 opacity-60'
                                }
                            `}
                        >
                            <span className="block leading-tight">{nombreCorto}</span>
                            <span className="block text-lg">{diaNum}</span>
                            {tieneClases && estaExpandido && (
                                <span className="block text-[10px] font-normal opacity-80">▼ abierto</span>
                            )}
                            {tieneClases && !estaExpandido && (
                                <span className="block text-[10px] font-normal opacity-60">{clasesDelDia.length} clase(s)</span>
                            )}
                            {!tieneClases && (
                                <span className="block text-[10px] font-normal opacity-50">sin cls</span>
                            )}
                        </button>
                    );
                })}
            </div>

            {/* ── PANEL EXPANDIDO (solo el día seleccionado) ── */}
            {diaExpandido && (() => {
                const diaInfo = proximosDias.find(d => d.fecha === diaExpandido);
                if (!diaInfo) return null;
                const clasesDelDia = (clasesPorDia[diaExpandido] || [])
                    .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));
                const { manana, tarde } = separarClasesPorFranja(clasesDelDia);
                const esPrimerDisponible = primerDiaDisponible === diaExpandido;

                const disciplinasUnicas = [...new Set(clasesDelDia.map(c => c.disciplina_nombre).filter(Boolean))].sort();

                const filtrarPorDisciplina = (clases) => {
                    if (disciplinaFiltro === 'Todos') return clases;
                    return clases.filter(c => c.disciplina_nombre === disciplinaFiltro);
                };

                const renderTabla = (clases) => {
                    const clasesFiltradas = filtrarPorDisciplina(clases);
                    if (clasesFiltradas.length === 0) {
                        return (
                            <div className="px-5 py-6 text-center">
                                <p className="text-gray-400 italic text-sm">Sin clases para esta disciplina en este horario</p>
                            </div>
                        );
                    }
                    return (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="border-b border-gray-200">
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Disciplina</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Horario</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Coach</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Cupos</th>
                                        <th className="px-5 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider"></th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">

                                    {clasesFiltradas.map((clase) => {
                                        // Migración 066: cupo NULL = sin tope (Musculación /
                                        // Open Box): la sala es de acceso libre y siempre se
                                        // puede reservar (sin "X/Y libres" ni botón apagado).
                                        const sinTope = clase.cupo_maximo === null || clase.cupo_maximo === undefined;
                                        const cuposLibres = sinTope
                                            ? Infinity
                                            : (clase.cupo_maximo || 0) - (clase.asistentes_confirmados || 0);
                                        const libre = cuposLibres > 0;
                                        return (
                                            <tr key={clase.id} className="hover:bg-gray-50 transition-colors">
                                                <td className="px-5 py-2.5 text-sm font-medium text-gray-900">{clase.disciplina_nombre || 'Clase'}</td>
                                                <td className="px-5 py-2.5 text-sm text-gray-600">🕐 {clase.hora_inicio} - {clase.hora_fin}</td>
                                                <td className="px-5 py-2.5 text-sm text-gray-600">👨‍🏫 {clase.coach_nombre || '—'}</td>
                                                <td className="px-5 py-2.5">
                                                    <span className={`inline-flex items-center px-3 py-1.5 rounded-full text-sm font-bold ${libre
                                                        ? 'bg-green-100 text-green-700'
                                                        : 'bg-red-100 text-red-700'
                                                        }`}>
                                                        {sinTope ? 'Acceso libre' : (libre ? `${cuposLibres}/${clase.cupo_maximo} libres` : 'Completo')}
                                                    </span>
                                                </td>
                                                <td className="px-5 py-2.5 text-right">
                                                    <button
                                                        onClick={() => abrirReserva(clase)}
                                                        disabled={!libre}
                                                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${libre
                                                            ? 'bg-emerald-500 text-white hover:bg-emerald-600'
                                                            : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                                                            }`}
                                                    >
                                                        {libre ? 'Reservar' : 'Lleno'}
                                                    </button>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    );
                };


                const disciplinasFiltroChips = [...new Set(['Todos', ...disciplinasUnicas])];

                return (
                    <>
                        {/* Filtro por disciplina */}
                        {disciplinasUnicas.length > 1 && (
                            <div className="flex flex-wrap gap-1.5 mb-3 px-5 pt-2">
                                {disciplinasFiltroChips.map(d => (
                                    <button
                                        key={d}
                                        onClick={() => setDisciplinaFiltro(d)}
                                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${disciplinaFiltro === d
                                            ? 'bg-emerald-500 text-white shadow-sm'
                                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                                            }`}
                                    >
                                        {d === 'Todos' ? '📋 Todos' : d}
                                    </button>
                                ))}
                            </div>
                        )}
                        <div className={`rounded-xl border-2 overflow-hidden transition-all ${esPrimerDisponible
                            ? 'border-emerald-400 bg-emerald-50/50 shadow-md'
                            : 'border-gray-200 bg-white shadow-sm'
                            }`}>
                            {/* Encabezado del día expandido */}
                            <div className={`px-5 py-3 flex items-center gap-3 ${esPrimerDisponible
                                ? 'bg-emerald-500 text-white'
                                : 'bg-gray-100 text-gray-800'
                                }`}>
                                <div className="flex-1">
                                    <h3 className="text-base font-bold tracking-wide">
                                        {diaInfo.nombreDia} {diaInfo.diaNum}
                                    </h3>
                                    <p className={`text-xs ${esPrimerDisponible ? 'text-emerald-100' : 'text-gray-500'}`}>
                                        {diaInfo.fecha}
                                    </p>
                                </div>
                                {esPrimerDisponible && (
                                    <span className="text-xs font-bold bg-white text-emerald-600 px-3 py-1 rounded-full">
                                        ⭐ PRÓXIMO DÍA
                                    </span>
                                )}
                            </div>


                            {/* ── SECCIÓN MAÑANA ── */}
                            <div className="border-b border-gray-100 last:border-b-0">
                                <button
                                    onClick={() => setSeccionesExpandidas(prev => ({ ...prev, manana: !prev.manana }))}
                                    className={`w-full px-5 py-3 flex items-center gap-3 transition-colors ${manana.length > 0
                                        ? 'hover:bg-gray-50 text-gray-800'
                                        : 'text-gray-400 cursor-pointer hover:bg-gray-50'
                                        }`}
                                >
                                    <span className={`text-sm font-bold transition-transform ${seccionesExpandidas.manana ? 'rotate-90' : ''}`}>
                                        ▶
                                    </span>
                                    <span className="font-bold text-sm">🌅 MAÑANA</span>
                                    <span className={`text-xs font-medium ${manana.length > 0 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-400'} px-2 py-0.5 rounded-full`}>
                                        {manana.length} clase(s)
                                    </span>
                                    {manana.length === 0 && (
                                        <span className="text-xs italic opacity-60">Sin clases en la mañana</span>
                                    )}
                                </button>
                                {seccionesExpandidas.manana && (
                                    <div className="border-t border-gray-100">
                                        {manana.length > 0 ? renderTabla(manana) : (
                                            <div className="px-5 py-6 text-center">
                                                <p className="text-gray-400 italic text-sm">Sin clases en la mañana</p>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* ── SECCIÓN TARDE ── */}
                            <div>
                                <button
                                    onClick={() => setSeccionesExpandidas(prev => ({ ...prev, tarde: !prev.tarde }))}
                                    className={`w-full px-5 py-3 flex items-center gap-3 transition-colors ${tarde.length > 0
                                        ? 'hover:bg-gray-50 text-gray-800'
                                        : 'text-gray-400 cursor-pointer hover:bg-gray-50'
                                        }`}
                                >
                                    <span className={`text-sm font-bold transition-transform ${seccionesExpandidas.tarde ? 'rotate-90' : ''}`}>
                                        ▶
                                    </span>
                                    <span className="font-bold text-sm">🌆 TARDE</span>
                                    <span className={`text-xs font-medium ${tarde.length > 0 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-400'} px-2 py-0.5 rounded-full`}>
                                        {tarde.length} clase(s)
                                    </span>
                                    {tarde.length === 0 && (
                                        <span className="text-xs italic opacity-60">Sin clases en la tarde</span>
                                    )}
                                </button>
                                {seccionesExpandidas.tarde && (
                                    <div className="border-t border-gray-100">
                                        {tarde.length > 0 ? renderTabla(tarde) : (
                                            <div className="px-5 py-6 text-center">
                                                <p className="text-gray-400 italic text-sm">Sin clases en la tarde</p>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </>);
            })()}

            {!diaExpandido && (
                <div className="text-center py-6 text-gray-400 text-sm italic">
                    Selecciona un día arriba para ver sus horarios disponibles
                </div>
            )}
        </div>
    );
};

/**
 * Modal "¿Estás seguro de reservar esta clase?" — la confirmación de la grilla.
 * Vivía inline en `pages/alumno/Dashboard.jsx`; se extrajo con la grilla para que
 * el Inicio y "Agendar Reserva" usen EXACTAMENTE el mismo modal.
 *
 * Presentacional + estado de envío/error propio: el padre entrega la clase
 * elegida y `onConfirmar(clase)` (que devuelve una promesa). El error del
 * backend se muestra tal cual (`detail`).
 */
export function ModalConfirmarReserva({ clase, misReservas = [], onCerrar, onConfirmar }) {
    const [error, setError] = useState('');
    const [enviando, setEnviando] = useState(false);

    // Al cambiar de clase se limpia el mensaje anterior.
    useEffect(() => {
        setError('');
    }, [clase?.id]);

    if (!clase) return null;

    const fechaClase = clase.fecha || clase.fecha_clase;
    const disciplina = clase.disciplina_nombre;
    // D-02: cupos REALES de la clase (no un "Cupos disponibles" fijo).
    const cupoMax = Number(clase.cupo_maximo || 0);
    const asistentes = Number(clase.asistentes_confirmados || 0);
    // Migración 066: sin tope no hay "N/M cupos": se informa el acceso libre.
    const sinTopeModal = clase.cupo_maximo === null || clase.cupo_maximo === undefined;
    const cuposModal = Math.max(0, cupoMax - asistentes);
    const tieneDuplicado = disciplina && fechaClase && misReservas.some(r => (
        r.disciplina_nombre === disciplina
        && (r.clase_fecha === fechaClase || r.fecha === fechaClase)
    ));

    const confirmar = async () => {
        setError('');
        setEnviando(true);
        try {
            await onConfirmar?.(clase);
            onCerrar?.();
        } catch (e) {
            console.error('Error creando reserva:', e);
            setError(e?.response?.data?.detail
                || 'No se pudo confirmar la reserva. Intenta nuevamente.');
        } finally {
            setEnviando(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-xl shadow-xl max-w-md w-full">
                <div className="bg-emerald-600 text-white px-6 py-4 rounded-t-xl">
                    <h2 className="text-lg font-bold">Confirmar Reserva</h2>
                    <p className="text-emerald-100 text-sm">¿Estás seguro de reservar esta clase?</p>
                </div>
                <div className="p-6 space-y-4">
                    {error && (
                        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                            ❌ {error}
                        </div>
                    )}
                    {tieneDuplicado && (
                        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                            ⚠️ Ya tienes una reserva de <strong>{disciplina}</strong> para esta fecha.
                            Esta será tu <strong>segunda clase</strong> del día y se descontará <strong>otro crédito</strong>.
                            ¿Confirmas igual?
                        </div>
                    )}
                    <div className="bg-gray-50 rounded-xl p-4 space-y-2">
                        <p className="font-bold text-gray-900 text-lg">{disciplina || 'Clase'}</p>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                            <p className="text-gray-600">🕐 {clase.hora_inicio} - {clase.hora_fin}</p>
                            <p className="text-gray-600">👨‍🏫 {clase.coach_nombre || '—'}</p>
                            <p className="text-gray-600">📅 {fechaClase}</p>
                            <p className={sinTopeModal || cuposModal > 0 ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
                                {sinTopeModal
                                    ? `✅ Acceso libre (${asistentes} reservas)`
                                    : (cuposModal > 0
                                        ? `✅ ${cuposModal}/${cupoMax} cupos disponibles`
                                        : `⛔ Sin cupos (${asistentes}/${cupoMax})`)}
                            </p>
                        </div>
                    </div>
                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onCerrar}
                            className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors"
                            disabled={enviando}
                        >
                            Cancelar
                        </button>
                        <button
                            type="button"
                            onClick={confirmar}
                            disabled={enviando}
                            className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50"
                        >
                            {enviando ? 'Reservando...' : '✅ Confirmar Reserva'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default GrillaReservaClases;

