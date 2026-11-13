import React from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import {
    useRegistrarResultadoWod, useWodsHistorial, useWodsPendientes,
} from '../../hooks/queries';
import { fmtFechaCortaChile } from '../../utils/fecha';

// ── Reglas puras del formulario (mismo criterio que el backend) ──────────────
// El tipo de metcon decide qué campo pide el modal: tiempo para FOR TIME/RFT,
// rondas para AMRAP/EMOM. Sin tipo definido, el alumno elige cuál registrar.
const GRUPO_POR_TIPO = {
    'FOR TIME': 'tiempo',
    FORTIME: 'tiempo',
    RFT: 'tiempo',
    AMRAP: 'rondas',
    EMOM: 'rondas',
};

function grupoResultado(tipo) {
    const normalizado = String(tipo || '')
        .trim().toUpperCase().replace(/_/g, ' ').replace(/\s+/g, ' ');
    // `tipo_metcon` es texto libre: "AMRAP 12" o "FOR TIME (cap)" son variantes
    // reales. Se comparan por prefijo para no caer en el selector "libre".
    if (GRUPO_POR_TIPO[normalizado] === 'tiempo' || normalizado.startsWith('FOR TIME')) {
        return 'tiempo';
    }
    if (GRUPO_POR_TIPO[normalizado] === 'rondas'
        || normalizado.startsWith('AMRAP') || normalizado.startsWith('EMOM')) {
        return 'rondas';
    }
    return 'libre';
}

// Segundos -> "m:ss" (12:30). El formato vive acá y lo usan la tarjeta y el modal.
function formatTiempo(segundos) {
    if (segundos === null || segundos === undefined) return '—';
    const total = Math.max(0, Number(segundos));
    const minutos = Math.floor(total / 60);
    const resto = total % 60;
    return `${minutos}:${String(resto).padStart(2, '0')}`;
}

// "mm:ss" -> segundos, o null si el texto no tiene ese formato. Acepta "9:05"
// y "09:05"; los segundos tienen que ser 00-59 y el tiempo mayor que cero.
function parseTiempo(texto) {
    const match = /^(\d{1,3}):([0-5]\d)$/.exec(String(texto || '').trim());
    if (!match) return null;
    const segundos = Number(match[1]) * 60 + Number(match[2]);
    return segundos > 0 ? segundos : null;
}

function resultadoReal(item) {
    if (item?.tiempo_segundos !== null && item?.tiempo_segundos !== undefined) {
        return formatTiempo(item.tiempo_segundos);
    }
    if (item?.rondas !== null && item?.rondas !== undefined) {
        const reps = item.reps_extra ? ` + ${item.reps_extra} reps` : '';
        return `${item.rondas} ronda${item.rondas === 1 ? '' : 's'}${reps}`;
    }
    return 'Sin dato';
}

function fechaWod(fecha) {
    return fmtFechaCortaChile(fecha) || '—';
}

function mensajeDeError(error) {
    const detalle = error?.response?.data?.detail;
    if (typeof detalle === 'string') return detalle;
    if (Array.isArray(detalle) && detalle[0]?.msg) return detalle[0].msg;
    return 'No pudimos guardar tu resultado. Intenta de nuevo.';
}

const CLASES_BADGE = 'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold';

function BadgeModo({ modo }) {
    const rx = modo === 'rx';
    return (
        <span
            className={`${CLASES_BADGE} ${rx
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-amber-50 text-amber-700'}`}
            data-testid={`badge-modo-${modo}`}
        >
            {rx ? 'RX' : 'Escalado'}
        </span>
    );
}

function TipoBadge({ tipo }) {
    if (!tipo) return null;
    return (
        <span className={`${CLASES_BADGE} bg-zinc-100 text-zinc-600`}>
            {tipo}
        </span>
    );
}

function TarjetaPendiente({ item, onRegistrar }) {
    return (
        <article className="bg-white rounded-xl border border-gray-200 shadow-sm border-l-4 border-l-orange-500 p-4 flex flex-col">
            <div className="flex items-center justify-between gap-2">
                <span className={`${CLASES_BADGE} bg-zinc-100 text-zinc-600`}>
                    Sin registrar
                </span>
                <span className="text-xs font-semibold text-gray-400">
                    {fechaWod(item.fecha)}
                </span>
            </div>
            <div className="mt-3 flex items-start justify-between gap-2">
                <h3 className="font-bold text-gray-800 text-lg leading-tight">
                    {item.titulo || 'WOD'}
                </h3>
                <TipoBadge tipo={item.tipo_metcon} />
            </div>
            {item.wod_principal && (
                <p className="mt-2 text-sm text-gray-500 whitespace-pre-line line-clamp-3 break-words">
                    {item.wod_principal}
                </p>
            )}
            <button
                type="button"
                onClick={() => onRegistrar(item)}
                className="mt-4 w-full rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 transition-colors"
            >
                Registrar mi resultado
            </button>
        </article>
    );
}

function TarjetaHistorial({ item }) {
    return (
        <article className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <BadgeModo modo={item.modo} />
                    <TipoBadge tipo={item.tipo_metcon} />
                </div>
                <span className="text-xs font-semibold text-gray-400">
                    {fechaWod(item.fecha)}
                </span>
            </div>
            <h3 className="mt-2 font-bold text-gray-800 text-lg">{item.titulo || 'WOD'}</h3>
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="rounded-lg bg-zinc-50 p-3">
                    <p className="text-[11px] font-bold uppercase tracking-wide text-zinc-500">
                        Prescrito
                    </p>
                    <p className="mt-1 text-sm text-gray-600 whitespace-pre-line break-words">
                        {item.wod_principal || 'Sin detalle prescrito'}
                    </p>
                </div>
                <div className="rounded-lg bg-emerald-50 p-3">
                    <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">
                        Tu resultado
                    </p>
                    <p className="mt-1 text-2xl font-bold text-emerald-800">
                        {resultadoReal(item)}
                    </p>
                </div>
            </div>
            {item.nota && (
                <p className="mt-3 rounded-lg bg-zinc-50 px-3 py-2 text-sm text-gray-600 break-words">
                    {item.nota}
                </p>
            )}
        </article>
    );
}


function ModalRegistro({ pendiente, onClose, registrar }) {
    const grupo = grupoResultado(pendiente.tipo_metcon);
    const [modo, setModo] = React.useState('rx');
    // Sólo se usa cuando el WOD no trae `tipo_metcon`: el alumno elige qué registró.
    const [tipoLibre, setTipoLibre] = React.useState('tiempo');
    const [tiempo, setTiempo] = React.useState('');
    const [rondas, setRondas] = React.useState('');
    const [repsExtra, setRepsExtra] = React.useState('');
    const [nota, setNota] = React.useState('');
    const [errorLocal, setErrorLocal] = React.useState('');
    const efectivo = grupo === 'libre' ? tipoLibre : grupo;

    React.useEffect(() => {
        const alEscape = (evento) => {
            if (evento.key === 'Escape' && !registrar.isPending) onClose();
        };
        window.addEventListener('keydown', alEscape);
        return () => window.removeEventListener('keydown', alEscape);
    }, [onClose, registrar.isPending]);

    const enviar = (evento) => {
        evento.preventDefault();
        setErrorLocal('');
        const payload = { modo, nota: nota.trim() || null };

        if (efectivo === 'tiempo') {
            const segundos = parseTiempo(tiempo);
            if (!segundos) {
                setErrorLocal('Escribe el tiempo en formato mm:ss (por ejemplo 12:30).');
                return;
            }
            payload.tiempo_segundos = segundos;
        } else {
            const numeroRondas = Number(rondas);
            if (rondas === '' || !Number.isInteger(numeroRondas) || numeroRondas < 0) {
                setErrorLocal('Indica cuántas rondas completaste.');
                return;
            }
            payload.rondas = numeroRondas;
            if (repsExtra !== '') {
                const reps = Number(repsExtra);
                if (!Number.isInteger(reps) || reps < 0) {
                    setErrorLocal('Las reps extra tienen que ser un número entero.');
                    return;
                }
                payload.reps_extra = reps;
            }
        }

        registrar.mutate(
            { wodId: pendiente.wod_id, ...payload },
            { onSuccess: onClose },
        );
    };

    const claseInput = 'w-full rounded-xl border border-gray-300 px-3 py-2.5 text-sm text-gray-800 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-100';
    const errorVisible = errorLocal
        || (registrar.isError ? mensajeDeError(registrar.error) : '');

    return (
        <div
            className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 sm:items-center"
            onMouseDown={(evento) => {
                if (evento.target === evento.currentTarget && !registrar.isPending) onClose();
            }}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="titulo-modal-wod"
                className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white shadow-xl"
            >

                <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-5 py-4">
                    <div>
                        <p className="text-xs font-bold uppercase tracking-wide text-emerald-700">
                            Registrar resultado
                        </p>
                        <h2 id="titulo-modal-wod" className="text-xl font-bold text-gray-800">
                            {pendiente.titulo || 'WOD'}
                        </h2>
                        <p className="mt-0.5 text-xs font-semibold text-gray-400">
                            {fechaWod(pendiente.fecha)}
                            {pendiente.tipo_metcon ? ` · ${pendiente.tipo_metcon}` : ''}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={registrar.isPending}
                        aria-label="Cerrar"
                        className="min-h-9 min-w-9 rounded-lg text-xl leading-none text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                    >
                        ×
                    </button>
                </div>

                <form onSubmit={enviar} className="space-y-5 px-5 py-4">
                    <fieldset>
                        <legend className="mb-2 text-sm font-bold text-gray-700">
                            ¿Cómo lo hiciste?
                        </legend>
                        <div className="grid grid-cols-2 gap-2">
                            {[['rx', 'RX'], ['escalado', 'Escalado']].map(([valor, texto]) => {
                                const activo = modo === valor;
                                return (
                                    <button
                                        key={valor}
                                        type="button"
                                        aria-pressed={activo}
                                        onClick={() => setModo(valor)}
                                        className={`rounded-xl border px-3 py-2.5 text-sm font-bold transition-colors ${
                                            activo
                                                ? 'border-emerald-600 bg-emerald-50 text-emerald-700'
                                                : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'
                                        }`}
                                    >
                                        {texto}
                                    </button>
                                );
                            })}
                        </div>
                    </fieldset>

                    {grupo === 'libre' && (
                        <fieldset>
                            <legend className="mb-2 text-sm font-bold text-gray-700">
                                ¿Qué vas a registrar?
                            </legend>
                            <div className="grid grid-cols-2 gap-2">
                                {[['tiempo', 'Tiempo'], ['rondas', 'Rondas']].map(([valor, texto]) => (
                                    <button
                                        key={valor}
                                        type="button"
                                        aria-pressed={tipoLibre === valor}
                                        onClick={() => setTipoLibre(valor)}
                                        className={`rounded-xl border px-3 py-2 text-sm font-bold transition-colors ${
                                            tipoLibre === valor
                                                ? 'border-emerald-600 bg-emerald-50 text-emerald-700'
                                                : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'
                                        }`}
                                    >
                                        {texto}
                                    </button>
                                ))}
                            </div>
                        </fieldset>
                    )}

                    {efectivo === 'tiempo' ? (
                        <div>
                            <label htmlFor="tiempo-wod" className="mb-1 block text-sm font-bold text-gray-700">
                                Tiempo (mm:ss)
                            </label>
                            <input
                                id="tiempo-wod"
                                value={tiempo}
                                onChange={(evento) => setTiempo(evento.target.value)}
                                inputMode="numeric"
                                placeholder="12:30"
                                className={claseInput}
                            />
                            <p className="mt-1 text-xs text-gray-400">
                                Minutos y segundos. Ejemplo: 12:30
                            </p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <label htmlFor="rondas-wod" className="mb-1 block text-sm font-bold text-gray-700">
                                    Rondas
                                </label>
                                <input
                                    id="rondas-wod"
                                    value={rondas}
                                    onChange={(evento) => setRondas(evento.target.value)}
                                    inputMode="numeric"
                                    min="0"
                                    placeholder="7"
                                    className={claseInput}
                                />
                            </div>
                            <div>
                                <label htmlFor="reps-wod" className="mb-1 block text-sm font-bold text-gray-700">
                                    Reps extra
                                </label>
                                <input
                                    id="reps-wod"
                                    value={repsExtra}
                                    onChange={(evento) => setRepsExtra(evento.target.value)}
                                    inputMode="numeric"
                                    min="0"
                                    placeholder="Opcional"
                                    className={claseInput}
                                />
                            </div>
                        </div>
                    )}

                    <div>
                        <label htmlFor="nota-wod" className="mb-1 block text-sm font-bold text-gray-700">
                            Nota <span className="font-normal text-gray-400">(opcional)</span>
                        </label>
                        <textarea
                            id="nota-wod"
                            value={nota}
                            onChange={(evento) => setNota(evento.target.value.slice(0, 500))}
                            rows={3}
                            maxLength={500}
                            placeholder="Cómo te sentiste, qué escalaste, etc."
                            className={`${claseInput} resize-none`}
                        />
                        <p className="mt-1 text-right text-xs text-gray-400">{nota.length}/500</p>
                    </div>

                    {errorVisible && (
                        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                            {errorVisible}
                        </p>
                    )}

                    <div className="flex items-center justify-end gap-2 border-t border-gray-100 pt-4">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={registrar.isPending}
                            className="rounded-xl px-4 py-2.5 text-sm font-bold text-gray-500 hover:bg-gray-100"
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={registrar.isPending}
                            className="rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {registrar.isPending ? 'Guardando...' : 'Guardar resultado'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}


const MisWods = () => {
    const navigate = useNavigate();
    const pendientesQ = useWodsPendientes();
    const historialQ = useWodsHistorial(20);
    const registrar = useRegistrarResultadoWod();
    const [seleccionado, setSeleccionado] = React.useState(null);

    const pendientes = pendientesQ.data || [];
    const historial = historialQ.data || [];
    const loading = pendientesQ.isPending || historialQ.isPending;

    const erroresCarga = React.useMemo(() => {
        const fallaron = [];
        if (pendientesQ.isError) fallaron.push('tus WODs pendientes');
        if (historialQ.isError) fallaron.push('tu historial de WODs');
        return fallaron;
    }, [pendientesQ.isError, historialQ.isError]);

    const cargarTodo = () => {
        pendientesQ.refetch();
        historialQ.refetch();
    };

    const abrirModal = (item) => {
        registrar.reset();
        setSeleccionado(item);
    };

    const cerrarModal = () => {
        // Los botones/backdrop/ESC ya bloquean el cierre mientras se guarda; acá
        // cerramos también desde el `onSuccess` de la mutación, cuando `isPending`
        // puede seguir siendo true por un instante.
        setSeleccionado(null);
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex h-96 items-center justify-center">
                    <div className="h-12 w-12 animate-spin rounded-full border-b-2 border-emerald-500" />
                </div>
            </Layout>
        );
    }

    const mostrarVacio = pendientes.length === 0 && historial.length === 0
        && erroresCarga.length === 0;

    return (
        <Layout>
            <div className="mx-auto max-w-4xl">
                {erroresCarga.length > 0 && (
                    <div
                        role="alert"
                        className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
                    >
                        <span>
                            No se pudieron cargar: <strong>{erroresCarga.join(', ')}</strong>.
                            Lo que ves puede estar incompleto.
                        </span>
                        <button
                            type="button"
                            onClick={cargarTodo}
                            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 transition-colors"
                        >
                            Reintentar
                        </button>
                    </div>
                )}

                <div className="mb-6 flex items-center gap-3">
                    <BotonVolver fallback="/alumno/performance-hub" />
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Mis WODs</h1>
                        <p className="text-sm text-gray-500">
                            Registra cómo te fue y compáralo con lo prescrito
                        </p>
                    </div>
                </div>

                {mostrarVacio ? (
                    <div className="rounded-xl border border-gray-200 bg-white px-6 py-14 text-center shadow-sm">
                        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-zinc-100 text-xl font-bold text-zinc-500">
                            W
                        </div>
                        <h2 className="mt-4 text-xl font-bold text-gray-800">
                            Todavía no registraste ningún WOD
                        </h2>
                        <p className="mx-auto mt-2 max-w-md text-sm text-gray-500">
                            Cuando asistas a una clase con WOD, aparecerá acá para que anotes
                            tu tiempo o tus rondas y lo compares con lo prescrito.
                        </p>
                        <button
                            type="button"
                            onClick={() => navigate('/alumno/mis-reservas')}
                            className="mt-6 rounded-xl bg-emerald-600 px-6 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 transition-colors"
                        >
                            Ver mis reservas
                        </button>
                    </div>
                ) : (

                    <div className="space-y-8">
                        <section>
                            <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                                <div>
                                    <h2 className="text-xl font-bold text-gray-800">
                                        Pendientes de registrar
                                    </h2>
                                    <p className="text-sm text-gray-500">
                                        WODs de los últimos 14 días a los que asististe.
                                    </p>
                                </div>
                                {pendientes.length > 0 && (
                                    <span className="rounded-full bg-orange-50 px-2.5 py-0.5 text-xs font-bold text-orange-700">
                                        {pendientes.length}
                                    </span>
                                )}
                            </div>
                            {pendientes.length === 0 ? (
                                <p className="rounded-xl border border-dashed border-gray-300 bg-white px-4 py-6 text-center text-sm text-gray-500">
                                    No tienes WODs pendientes.
                                </p>
                            ) : (
                                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                    {pendientes.map((item) => (
                                        <TarjetaPendiente
                                            key={item.wod_id}
                                            item={item}
                                            onRegistrar={abrirModal}
                                        />
                                    ))}
                                </div>
                            )}
                        </section>

                        <section>
                            <div className="mb-3">
                                <h2 className="text-xl font-bold text-gray-800">
                                    Ya registrados
                                </h2>
                                <p className="text-sm text-gray-500">
                                    Tu resultado real junto a lo que decía el WOD.
                                </p>
                            </div>
                            {historial.length === 0 ? (
                                <p className="rounded-xl border border-dashed border-gray-300 bg-white px-4 py-6 text-center text-sm text-gray-500">
                                    Todavía no registraste resultados.
                                </p>
                            ) : (
                                <div className="grid grid-cols-1 gap-3">
                                    {historial.map((item) => (
                                        <TarjetaHistorial key={item.id} item={item} />
                                    ))}
                                </div>
                            )}
                        </section>
                    </div>
                )}
            </div>

            {seleccionado && (
                <ModalRegistro
                    key={seleccionado.wod_id}
                    pendiente={seleccionado}
                    onClose={cerrarModal}
                    registrar={registrar}
                />
            )}
        </Layout>
    );
};

export default MisWods;

