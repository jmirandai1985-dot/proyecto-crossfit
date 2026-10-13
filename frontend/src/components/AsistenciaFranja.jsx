import React, { useState } from 'react';
import {
    estadoFila, etiquetaEstado, reservasDe, textoProgreso,
} from '../utils/franjasAsistencia';
import { acotarExtra, cupoActual, cupoOriginal, cupoTope, extraMaximo } from '../utils/cuposClase';

/**
 * AsistenciaFranja — una franja del día (Mañana / Tarde / Noche) con sus clases.
 *
 * Es la vista de TELÉFONO (<768px) de la pestaña Asistencia del coach (mockup 6b): las
 * franjas van una debajo de la otra y cada clase es una fila compacta con su barra de
 * color, cuánta asistencia falta y el estado. En ≥768px la pestaña sigue con el acordeón
 * por disciplina (AsistenciaGrupoDisciplina), así que este componente NO reemplaza nada.
 *
 * Decisiones que vienen del backend, no del reloj del navegador:
 *   · `estado` ("en_curso"/"realizada"/…) lo calcula la API en hora de Chile
 *     (`clases_service.estado_clase`); acá sólo se pinta el badge.
 *   · `marcada` dice si la asistencia ya se confirmó (batch del panel o QR del alumno).
 *
 * Acciones: "Marcar" abre el modal de siempre (mismo `onAbrir` que el acordeón) y
 * "+ cupo" amplía el cupo de esa clase con el tope de `utils/cuposClase` (+10 sobre el
 * cupo original), igual que en escritorio: en el teléfono no se pierde ninguna.
 *
 * Props: franja {id,label}, clases[], osc, formatearHora, onAbrir, onAmpliarCupo.
 */

// Íconos del mockup (sol / sol bajando / luna): SVG en línea, sin librería nueva.
const ICONO_FRANJA = {
    manana: {
        color: 'text-amber-500',
        cuerpo: (
            <>
                <circle cx="12" cy="12" r="4.5" />
                <path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
            </>
        ),
    },
    tarde: {
        color: 'text-orange-500',
        cuerpo: (
            <>
                <circle cx="12" cy="13" r="4" />
                <path d="M12 4v2M4.6 6.6l1.4 1.4M2 13h2M20 13h2M19.4 6.6l-1.4 1.4M3 19h18" />
            </>
        ),
    },
    noche: {
        color: 'text-violet-500',
        cuerpo: <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5Z" />,
    },
};

// Barra de la izquierda: verde la hecha, roja la que está en curso, ámbar la pendiente
// (los mismos colores del mockup 6b).
const BARRA = {
    hecha: 'bg-emerald-500',
    'en-curso': 'bg-red-500',
    pendiente: 'bg-amber-500',
};

const AsistenciaFranja = ({ franja, clases, osc, formatearHora, onAbrir, onAmpliarCupo }) => {
    // Ampliar el cupo de una clase puntual: estado local de la visita (igual que el
    // acordeón: el cupo nuevo se pinta con la respuesta del backend, no se persiste acá).
    const [cupos, setCupos] = useState({});
    const [abierto, setAbierto] = useState(null);
    const [extra, setExtra] = useState(2);
    const [enviando, setEnviando] = useState(false);
    const [msg, setMsg] = useState(null);

    const icono = ICONO_FRANJA[franja.id] || ICONO_FRANJA.manana;
    const puedeAmpliar = typeof onAmpliarCupo === 'function';

    const abrirCupo = (clase) => {
        setMsg(null);
        setAbierto(abierto === clase.id ? null : clase.id);
        setExtra(Math.max(1, Math.min(2, extraMaximo(clase, cupos))));
    };

    const confirmarCupo = async (clase) => {
        setEnviando(true);
        setMsg(null);
        try {
            const r = await onAmpliarCupo(clase, extra);
            setCupos((prev) => ({ ...prev, [clase.id]: r.cupo_maximo }));
            setMsg({ claseId: clase.id, tipo: 'exito', texto: `Cupo ampliado a ${r.cupo_maximo} (quedan ${r.extra_disponible} extra)` });
            setAbierto(null);
        } catch (e) {
            const s = e.response?.status;
            setMsg({
                claseId: clase.id,
                tipo: 'error',
                texto: s === 409 ? 'Tope alcanzado (+10 sobre el original)'
                    : s === 403 ? 'Solo puedes ampliar el cupo de tus clases o disciplinas'
                        : s === 422 ? 'Cupos extra debe estar entre 1 y 10'
                            : (e.response?.data?.detail || 'No se pudo ampliar el cupo'),
            });
        }
        setEnviando(false);
    };

    return (
        <section className="space-y-2" data-testid={`franja-${franja.id}`}>
            <div className="flex items-center gap-2 px-1">
                <svg
                    viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                    strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"
                    className={icono.color}
                >
                    {icono.cuerpo}
                </svg>
                <span className={`text-xs font-semibold uppercase tracking-wide ${osc ? 'text-zinc-400' : 'text-gray-500'}`}>
                    {franja.label}
                </span>
            </div>

            {clases.map((clase) => {
                const estado = estadoFila(clase);
                const conReservas = reservasDe(clase) > 0;
                const cupo = cupoActual(clase, cupos);
                const libre = extraMaximo(clase, cupos);
                const enCurso = estado === 'en-curso';
                return (
                    <div
                        key={clase.id}
                        data-testid={`franja-clase-${clase.id}`}
                        className={`flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2.5 ${
                            enCurso
                                ? (osc ? 'bg-red-950/30 border-red-900' : 'bg-red-50 border-red-200')
                                : (osc ? 'bg-zinc-900 border-zinc-800' : 'bg-white border-gray-100')
                        }`}
                    >
                        <span className={`w-1 self-stretch rounded-full shrink-0 ${BARRA[estado]}`} />
                        <div className="min-w-0 flex-1">
                            <p className={`text-sm font-semibold ${osc ? 'text-zinc-100' : 'text-gray-800'}`}>
                                {formatearHora(clase.hora_inicio)} · {clase.disciplina_nombre}
                            </p>
                            <p className={`text-xs ${enCurso
                                ? (osc ? 'text-red-300' : 'text-red-700')
                                : (osc ? 'text-zinc-500' : 'text-gray-500')}`}>
                                {textoProgreso(clase, cupo)}
                            </p>
                        </div>

                        {conReservas ? (
                            <span
                                data-testid={`franja-estado-${clase.id}`}
                                className={`inline-flex items-center px-2 py-1 text-xs font-medium rounded-full shrink-0 ${
                                    estado === 'hecha'
                                        ? (osc ? 'bg-green-500/20 text-green-400' : 'bg-green-100 text-green-700')
                                        : enCurso
                                            ? (osc ? 'bg-red-500/20 text-red-300' : 'bg-red-100 text-red-700')
                                            : (osc ? 'bg-orange-500/20 text-orange-400' : 'bg-orange-100 text-orange-700')
                                }`}
                            >
                                {etiquetaEstado(estado)}
                            </span>
                        ) : (
                            <span className={`text-xs shrink-0 ${osc ? 'text-zinc-600' : 'text-gray-400'}`}>
                                Sin reservas
                            </span>
                        )}

                        {puedeAmpliar && (
                            <button
                                onClick={() => abrirCupo(clase)}
                                disabled={libre === 0}
                                title={libre === 0
                                    ? `En el tope: +10 sobre el original (${cupoTope(clase)})`
                                    : `Quedan ${libre} cupos extra (original ${cupoOriginal(clase)})`}
                                data-testid={`franja-cupo-${clase.id}`}
                                className={`px-3 py-1.5 rounded-lg text-xs font-medium shrink-0 transition-colors ${
                                    libre === 0
                                        ? (osc ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed' : 'bg-gray-100 text-gray-400 cursor-not-allowed')
                                        : (osc ? 'bg-blue-900 text-blue-100 hover:bg-blue-800' : 'bg-blue-100 text-blue-800 hover:bg-blue-200')
                                }`}
                            >
                                + cupo
                            </button>
                        )}

                        <button
                            onClick={() => onAbrir(clase)}
                            data-testid={`franja-marcar-${clase.id}`}
                            className="px-3 py-1.5 bg-orange-500 text-white rounded-lg text-xs font-bold hover:bg-orange-600 transition-colors shrink-0"
                        >
                            Marcar
                        </button>

                        {abierto === clase.id && (
                            <div className={`w-full mt-1 p-3 rounded-lg border flex flex-wrap items-center gap-3 ${osc ? 'bg-zinc-800/60 border-zinc-700' : 'bg-gray-50 border-gray-200'}`}>
                                <span className={`text-xs ${osc ? 'text-zinc-300' : 'text-gray-600'}`}>
                                    Original {cupoOriginal(clase)} / tope +10 = {cupoTope(clase)} / quedan <b>{libre}</b>
                                </span>
                                {[1, 2, 3].map((n) => (
                                    <button
                                        key={n}
                                        onClick={() => setExtra(n)}
                                        disabled={libre < n}
                                        className={`px-2.5 py-1 rounded text-xs font-bold ${
                                            extra === n ? 'bg-orange-500 text-white' : (osc ? 'bg-zinc-700 text-zinc-200' : 'bg-white text-gray-700 border border-gray-300')
                                        }`}
                                    >
                                        +{n}
                                    </button>
                                ))}
                                <input
                                    type="number"
                                    min="1"
                                    max={libre}
                                    value={extra}
                                    onChange={(e) => setExtra(acotarExtra(e.target.value, clase, cupos))}
                                    className={`w-16 px-2 py-1 rounded text-xs border ${osc ? 'bg-zinc-900 border-zinc-700 text-zinc-100' : 'bg-white border-gray-300'}`}
                                />
                                <button
                                    onClick={() => confirmarCupo(clase)}
                                    disabled={enviando || extra < 1 || extra > libre}
                                    className="px-3 py-1.5 bg-orange-500 text-white rounded text-xs font-bold hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {enviando ? 'Guardando...' : 'Confirmar'}
                                </button>
                                <button
                                    onClick={() => { setAbierto(null); setMsg(null); }}
                                    className={`px-3 py-1.5 rounded text-xs font-medium ${osc ? 'text-zinc-300 hover:bg-zinc-700' : 'text-gray-600 hover:bg-gray-200'}`}
                                >
                                    Cancelar
                                </button>
                            </div>
                        )}

                        {msg && msg.claseId === clase.id && (
                            <div className={`w-full mt-1 px-3 py-2 rounded-lg text-xs border-l-4 ${msg.tipo === 'exito'
                                ? (osc ? 'bg-green-500/10 border-green-500 text-green-300' : 'bg-green-50 border-green-500 text-green-700')
                                : (osc ? 'bg-red-500/10 border-red-500 text-red-300' : 'bg-red-50 border-red-500 text-red-700')}`}>
                                {msg.texto}
                            </div>
                        )}
                    </div>
                );
            })}
        </section>
    );
};

export default AsistenciaFranja;
