import React, { useMemo, useState } from 'react';
// El mes entero (clases + alumnos) sale de UNA consulta cacheada: abrir un día del calendario
// no vuelve a pegarle a la API.
import { useHistorialAsistencia } from '../hooks/queries';
// Todas las cuentas (anillos, totales, grilla del calendario) viven en el util COMPARTIDO y
// puro: la pantalla no hace aritmética propia (ver `utils/historialAsistencia.js`).
import {
    DIAS_SEMANA, aniosDisponibles, calendarioDelMes, fechaSola, mesesDelAnio,
    nombreMes, resumenDia, resumenPorDiaSemana, totalesDe,
} from '../utils/historialAsistencia';

/**
 * "Historial de Asistencia" (coach + admin) — SÓLO LECTURA.
 *
 * Tres niveles del mismo mes, sin volver a pedir datos:
 *   1. el ANILLO de cada día de la semana (lunes→domingo): % de asistencia contra los CUPOS de
 *      ese día de la semana en el mes; al tocarlo se abren las dos listas del mockup (quiénes
 *      vinieron y quiénes no, con la cantidad de veces de cada uno);
 *   2. el CALENDARIO del mes: cada día con su % y sus contadores; se elige un día para verlo;
 *   3. el DETALLE de ese día: bloque por bloque (cada clase del día) con hora, disciplina,
 *      coach y la lista de alumnos con su ✓/✗.
 *
 * Esta pantalla NO marca nada: marcar la asistencia sigue siendo la pestaña "Asistencia"
 * (`AsistenciaClases`), que ya tiene los candados del backend. Acá se mira lo que quedó.
 *
 * Colores: la paleta oscura del mockup (bg #0E0E10 · tarjetas #18181B · bordes #2A2A2E ·
 * acento lima #D7FF4A). No hay variante clara porque los DOS paneles que la montan (el del
 * coach y el del admin) ya son oscuros.
 */
const TARJETA = 'rounded-[18px] border border-[#2A2A2E] bg-[#18181B]';
const ROTULO = 'text-[10.5px] font-extrabold uppercase tracking-[0.06em] text-zinc-500';
const CONTROL = 'rounded-[10px] border border-[#2A2A2E] bg-[#0E0E10] px-2.5 py-1.5 text-[12.5px] font-semibold text-zinc-200 focus:border-[#D7FF4A] focus:outline-none';

// Color del porcentaje (clases COMPLETAS en la grilla: Tailwind necesita las clases escritas).
const COLOR_PCT = (pct) => {
    if (pct >= 80) return 'text-emerald-300';
    if (pct >= 50) return 'text-[#D7FF4A]';
    if (pct > 0) return 'text-amber-200';
    return 'text-zinc-600';
};

/**
 * Anillo de ocupación (SVG propio, sin librerías — mismo cálculo que el donut del Resumen del
 * coach). `pct` es 0-100; el texto del medio lo pone quien lo usa.
 */
const Anillo = ({ pct = 0, tamano = 92, grosor = 10, children }) => {
    const limpio = Math.min(Math.max(Number(pct) || 0, 0), 100);
    const radio = (tamano - grosor) / 2;
    const circunferencia = 2 * Math.PI * radio;
    const centro = tamano / 2;
    return (
        <div className="relative" style={{ width: tamano, height: tamano }}>
            <svg width={tamano} height={tamano} className="-rotate-90"
                role="img" aria-label={`${limpio}% de asistencia`}>
                <circle cx={centro} cy={centro} r={radio} fill="none"
                    stroke="#2A2A2E" strokeWidth={grosor} />
                <circle cx={centro} cy={centro} r={radio} fill="none"
                    stroke="#D7FF4A" strokeWidth={grosor} strokeLinecap="round"
                    strokeDasharray={circunferencia}
                    strokeDashoffset={circunferencia * (1 - limpio / 100)} />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
                {children}
            </div>
        </div>
    );
};

/** Un número con su rótulo (los contadores se leen igual en toda la pantalla). */
const Contador = ({ valor, label, color = 'text-zinc-100' }) => (
    <span className="block text-center">
        <span className={`block text-xl font-black ${color}`}>{valor}</span>
        <span className="block text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
    </span>
);

/** Estado de la clase tal como lo devuelve la API (hora de Chile). */
const ETIQUETA_ESTADO = {
    realizada: 'Realizada',
    en_curso: 'En curso',
    proxima: 'Por venir',
    cancelada: 'Cancelada',
};

/** Una de las dos listas de alumnos: los que vinieron (✓) o los que no (✗). */
const ListaAlumnos = ({ items = [], tono = 'ok', vacio = 'Sin alumnos', extra = 0 }) => {
    const ok = tono === 'ok';
    const bola = ok ? 'bg-[#D7FF4A] text-[#0E0E10]' : 'bg-zinc-700 text-zinc-300';
    return (
        <div className="rounded-[14px] border border-[#2A2A2E] bg-[#121214] p-3">
            <ul className="space-y-1.5">
                {items.length === 0 && <li className="text-[12.5px] text-zinc-500">{vacio}</li>}
                {items.map((a, i) => (
                    <li key={`${a?.alumno_id ?? a?.nombre ?? 'alumno'}-${i}`}
                        className="flex items-center justify-between gap-2 text-[13px]">
                        <span className="flex items-center gap-2 text-zinc-200">
                            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-black ${bola}`}>
                                {ok ? '✓' : '✗'}
                            </span>
                            {a?.nombre || 'Alumno'}
                        </span>
                        {Number(a?.veces) > 0 && (
                            <span className="shrink-0 text-[11.5px] font-bold text-zinc-500">
                                {a.veces}×
                            </span>
                        )}
                    </li>
                ))}
                {extra > 0 && (
                    <li className="text-[11.5px] text-zinc-500">y {extra} más sin detalle</li>
                )}
            </ul>
        </div>
    );
};

/** Tinte de la celda del calendario según el % de asistencia del día. */
const tinteDia = (totales) => {
    if (totales.clases === 0) return 'bg-transparent';
    if (totales.pct >= 80) return 'bg-emerald-500/15';
    if (totales.pct >= 60) return 'bg-[#D7FF4A]/15';
    if (totales.pct > 0) return 'bg-amber-500/15';
    return 'bg-zinc-800/50';
};

const HistorialAsistencia = () => {
    const hoy = fechaSola();
    // El mes arranca en el ACTUAL (el panel del coach vive en "hoy"); el usuario lo mueve con
    // los dos selectores.
    const [anio, setAnio] = useState(() => Number(hoy.slice(0, 4)));
    const [mes, setMes] = useState(() => Number(hoy.slice(5, 7)));
    // Lo que el usuario tiene abierto: un día de la semana (el anillo) y un día del calendario.
    const [diaSemana, setDiaSemana] = useState(null);
    const [fecha, setFecha] = useState(null);

    const historialQ = useHistorialAsistencia(anio, mes);
    // Memorizado: el `|| []` crea un array NUEVO en cada render (mientras carga o si falla), y
    // los cálculos de abajo —que sí valen la pena memorizar— se reharían en cada pasada.
    const clases = useMemo(() => historialQ.data?.clases || [], [historialQ.data]);
    const error = historialQ.isError
        ? (historialQ.error?.response?.data?.detail || 'No se pudo cargar el historial del mes')
        : null;

    // El selector de años nunca queda vacío y siempre incluye el que está elegido.
    const anios = useMemo(() => {
        const lista = aniosDisponibles(anio);
        return lista.length ? lista : [anio];
    }, [anio]);
    const meses = useMemo(() => mesesDelAnio(), []);

    const totalMes = useMemo(() => totalesDe(clases), [clases]);
    const semana = useMemo(() => resumenPorDiaSemana(clases), [clases]);
    const semanas = useMemo(
        () => calendarioDelMes(anio, mes, clases, hoy), [anio, mes, clases, hoy],
    );
    const detalle = useMemo(() => (fecha ? resumenDia(clases, fecha) : null), [clases, fecha]);
    const anilloAbierto = diaSemana === null ? null : semana[diaSemana];

    // Cambiar de mes cierra lo abierto: lo elegido era de OTRO mes (y quedaría vacío).
    const cambiarMes = (valor) => { setMes(valor); setDiaSemana(null); setFecha(null); };
    const cambiarAnio = (valor) => { setAnio(valor); setDiaSemana(null); setFecha(null); };

    return (
        <div className="space-y-5" data-testid="historial-asistencia">
            {/* ── 1. Encabezado + selectores de mes y año ── */}
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                    <h2 className="text-2xl font-black uppercase tracking-tight text-white">
                        Historial de Asistencia
                    </h2>
                    <p className="mt-1 text-[12.5px] text-zinc-400">
                        {historialQ.data?.alcance === 'box' ? 'Todo el box' : 'Tus clases'}
                        {' · '}sólo lectura: acá no se marca asistencia
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <label className="sr-only" htmlFor="historial-mes">Mes</label>
                    <select id="historial-mes" className={CONTROL} value={mes}
                        onChange={(e) => cambiarMes(Number(e.target.value))}
                        data-testid="historial-selector-mes">
                        {meses.map((m) => (
                            <option key={m.valor} value={m.valor}>{m.label}</option>
                        ))}
                    </select>
                    <label className="sr-only" htmlFor="historial-anio">Año</label>
                    <select id="historial-anio" className={CONTROL} value={anio}
                        onChange={(e) => cambiarAnio(Number(e.target.value))}
                        data-testid="historial-selector-anio">
                        {anios.map((a) => <option key={a} value={a}>{a}</option>)}
                    </select>
                </div>
            </div>

            {error && (
                <div className="rounded-[14px] border-l-4 border-red-500 bg-red-500/10 p-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {historialQ.isPending ? (
                <div className="flex h-40 items-center justify-center">
                    <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-[#D7FF4A]" />
                </div>
            ) : (
                <>
                    {/* ── 2. Totales del mes elegido (el % es contra los CUPOS, igual que los anillos) ── */}
                    <div className={`${TARJETA} flex flex-wrap items-center justify-between gap-5 p-4`}>
                        <div>
                            <p className={ROTULO}>Totales del mes</p>
                            <p className="mt-1 text-2xl font-black text-white">
                                {nombreMes(mes)} {anio}
                            </p>
                            <p className="mt-1 text-[11.5px] text-zinc-500">
                                {totalMes.cupos} cupos en el mes · {totalMes.cerradas} clase
                                {totalMes.cerradas === 1 ? '' : 's'} con la asistencia cerrada
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-6">
                            <Contador valor={totalMes.clases} label="clases" />
                            <Contador valor={totalMes.presentes} label="presentes"
                                color="text-[#D7FF4A]" />
                            <Contador valor={totalMes.ausentes} label="no shows"
                                color="text-amber-200" />
                            <Contador valor={`${totalMes.pct}%`} label="asistencia" />
                        </div>
                    </div>

                    {clases.length === 0 && (
                        <p className="rounded-[14px] border border-[#2A2A2E] bg-[#18181B] p-4 text-[13px] text-zinc-400">
                            {nombreMes(mes)} {anio} no tiene clases cargadas.
                            {historialQ.data?.alcance === 'coach'
                                ? ' Probá con otro mes: acá sólo aparecen las clases tuyas.'
                                : ' Probá con otro mes del selector.'}
                        </p>
                    )}

                    {/* ── 3. Un anillo por día de la semana (lunes→domingo) ──
                        El % es contra los CUPOS de TODAS las clases de ese día de la semana en
                        el mes: un martes con tres bloques no se mira contra un domingo de uno.
                        Tocar un círculo abre sus dos listas (vinieron / no vinieron). */}
                    <div className={`${TARJETA} p-4`}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className={ROTULO}>Asistencia por día de la semana</p>
                            <p className="text-[11px] text-zinc-500">
                                Toca un círculo para ver quiénes vinieron y quiénes no
                            </p>
                        </div>
                        <div className="mt-4 grid grid-cols-4 gap-2 sm:grid-cols-7 sm:gap-3">
                            {semana.map((d) => {
                                const activo = diaSemana === d.indice;
                                const vacio = d.totales.clases === 0;
                                return (
                                    <button key={d.clave} type="button"
                                        onClick={() => setDiaSemana(activo ? null : d.indice)}
                                        aria-pressed={activo}
                                        title={`${d.largo}: ${d.totales.clases} clase(s)`}
                                        data-testid={`historial-anillo-${d.clave}`}
                                        className={`flex flex-col items-center gap-1.5 rounded-[14px] border px-1 py-2.5 transition-colors ${
                                            activo
                                                ? 'border-[#D7FF4A] bg-[#1F2412]'
                                                : 'border-[#2A2A2E] bg-[#121214] hover:border-zinc-600'
                                        }`}>
                                        <Anillo pct={d.pct} tamano={78} grosor={9}>
                                            <span className={`text-[15px] font-black ${vacio ? 'text-zinc-600' : COLOR_PCT(d.pct)}`}>
                                                {vacio ? '—' : `${d.pct}%`}
                                            </span>
                                        </Anillo>
                                        <span className="text-[12px] font-extrabold uppercase tracking-wide text-zinc-300">
                                            {d.label}
                                        </span>
                                        <span className="text-[10.5px] text-zinc-500">
                                            {vacio
                                                ? 'sin clases'
                                                : `${d.totales.presentes}/${d.totales.cupos} cupos`}
                                        </span>
                                    </button>
                                );
                            })}
                        </div>

                        {anilloAbierto && (
                            <div className="mt-4 border-t border-[#2A2A2E] pt-4"
                                data-testid="historial-dia-semana-abierto">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <p className="text-[13px] font-bold text-white">
                                        {anilloAbierto.largo} · {anilloAbierto.totales.clases} clase
                                        {anilloAbierto.totales.clases === 1 ? '' : 's'} en {nombreMes(mes)}
                                    </p>
                                    <p className="text-[11.5px] text-zinc-500">
                                        {anilloAbierto.totales.presentes} vinieron ·{' '}
                                        {anilloAbierto.totales.ausentes} no vinieron ·{' '}
                                        {anilloAbierto.pct}% del cupo
                                    </p>
                                </div>
                                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                                    <ListaAlumnos tono="ok" items={anilloAbierto.alumnosPresentes}
                                        vacio="Nadie marcó asistencia este día de la semana" />
                                    <ListaAlumnos tono="no" items={anilloAbierto.alumnosAusentes}
                                        extra={anilloAbierto.sinNombre}
                                        vacio="Nadie faltó: no hay no shows" />
                                </div>
                            </div>
                        )}
                    </div>

                    {/* ── 4. El calendario del mes: un casillero por día ──
                        El tinte y el % salen de los CUPOS del día (misma cuenta que los anillos).
                        Un día sin clases queda apagado y no se puede abrir. */}
                    <div className={`${TARJETA} p-4`}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className={ROTULO}>Día por día de {nombreMes(mes)}</p>
                            <p className="text-[11px] text-zinc-500">
                                Toca un día con clases para ver el detalle por bloque
                            </p>
                        </div>
                        <div className="mt-3 grid grid-cols-7 gap-1.5">
                            {DIAS_SEMANA.map((d) => (
                                <span key={d.clave}
                                    className="text-center text-[10.5px] font-extrabold uppercase tracking-wide text-zinc-500">
                                    {d.label}
                                </span>
                            ))}
                        </div>
                        <div className="mt-1.5 space-y-1.5">
                            {semanas.map((linea, i) => (
                                <div key={i} className="grid grid-cols-7 gap-1.5">
                                    {linea.map((celda, j) => {
                                        if (celda === null) {
                                            return (
                                                <span key={`hueco-${i}-${j}`} aria-hidden="true"
                                                    className="rounded-[12px] border border-transparent" />
                                            );
                                        }
                                        const conClases = celda.totales.clases > 0;
                                        const elegido = fecha === celda.fecha;
                                        return (
                                            <button key={celda.fecha} type="button"
                                                disabled={!conClases}
                                                onClick={() => setFecha(elegido ? null : celda.fecha)}
                                                aria-pressed={elegido}
                                                title={conClases
                                                    ? `${celda.fecha} · ${celda.totales.presentes}/${celda.totales.cupos} · ${celda.totales.pct}%`
                                                    : `${celda.fecha} · sin clases`}
                                                data-testid={`historial-dia-${celda.fecha}`}
                                                className={`flex min-h-[62px] flex-col items-start gap-0.5 rounded-[12px] border p-1.5 text-left transition-colors ${
                                                    elegido
                                                        ? 'border-[#D7FF4A]'
                                                        : celda.hoy
                                                            ? 'border-[#D7FF4A]/60'
                                                            : 'border-[#2A2A2E]'
                                                } ${tinteDia(celda.totales)} ${
                                                    conClases ? 'hover:border-zinc-500' : 'cursor-default opacity-60'
                                                }`}>
                                                <span className={`text-[11.5px] font-black ${
                                                    celda.hoy ? 'text-[#D7FF4A]' : 'text-zinc-300'
                                                }`}>
                                                    {celda.dia}
                                                </span>
                                                {conClases ? (
                                                    <>
                                                        <span className={`text-[12.5px] font-black ${COLOR_PCT(celda.totales.pct)}`}>
                                                            {celda.totales.pct}%
                                                        </span>
                                                        <span className="text-[10px] text-zinc-500">
                                                            {celda.totales.presentes}/{celda.totales.cupos}
                                                        </span>
                                                    </>
                                                ) : (
                                                    <span className="text-[10px] text-zinc-600">
                                                        {celda.esFuturo ? 'por venir' : 'sin clases'}
                                                    </span>
                                                )}
                                            </button>
                                        );
                                    })}
                                </div>
                            ))}
                        </div>
                        <p className="mt-3 flex flex-wrap items-center gap-3 text-[10.5px] text-zinc-500">
                            <span className="flex items-center gap-1.5">
                                <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500/60" /> 80% o más
                            </span>
                            <span className="flex items-center gap-1.5">
                                <span className="h-2.5 w-2.5 rounded-sm bg-[#D7FF4A]/60" /> 60% a 79%
                            </span>
                            <span className="flex items-center gap-1.5">
                                <span className="h-2.5 w-2.5 rounded-sm bg-amber-500/60" /> menos de 60%
                            </span>
                        </p>
                    </div>

                    {/* ── 5. El detalle del día elegido: bloque por bloque ── */}
                    {detalle && (
                        <div className={`${TARJETA} p-4`} data-testid="historial-detalle-dia">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div>
                                    <p className={ROTULO}>Detalle del día</p>
                                    <p className="mt-1 text-xl font-black text-white">{detalle.titulo}</p>
                                    <p className="mt-1 text-[11.5px] text-zinc-500">
                                        {detalle.totales.clases} clase
                                        {detalle.totales.clases === 1 ? '' : 's'} ·{' '}
                                        {detalle.totales.reservas} reservas ·{' '}
                                        {detalle.totales.libres} cupos libres
                                    </p>
                                </div>
                                <div className="flex flex-wrap items-center gap-5">
                                    <Contador valor={detalle.totales.presentes} label="presentes"
                                        color="text-[#D7FF4A]" />
                                    <Contador valor={detalle.totales.ausentes} label="no shows"
                                        color="text-amber-200" />
                                    <Contador valor={detalle.totales.cupos} label="cupos" />
                                    <Contador valor={`${detalle.totales.pct}%`} label="del cupo" />
                                    <button type="button" onClick={() => setFecha(null)}
                                        className="rounded-[10px] border border-[#2A2A2E] px-2.5 py-1.5 text-[11.5px] font-bold text-zinc-300 hover:border-zinc-500">
                                        Cerrar
                                    </button>
                                </div>
                            </div>

                            {detalle.fichas.length === 0 ? (
                                <p className="mt-4 text-[13px] text-zinc-500">
                                    Ese día no hubo clases.
                                </p>
                            ) : (
                                <div className="mt-4 space-y-3">
                                    {detalle.fichas.map((f) => (
                                        <div key={f.id}
                                            className="rounded-[14px] border border-[#2A2A2E] bg-[#121214] p-3.5"
                                            data-testid={`historial-bloque-${f.id}`}>
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                                <div>
                                                    <p className="text-[14px] font-black text-white">
                                                        {f.hora}–{f.horaFin} · {f.disciplina}
                                                    </p>
                                                    <p className="text-[11.5px] text-zinc-500">{f.coach}</p>
                                                </div>
                                                <div className="flex flex-wrap items-center gap-2 text-[10.5px] font-extrabold uppercase tracking-wide">
                                                    <span className={`rounded-full px-2 py-0.5 ${
                                                        f.marcada
                                                            ? 'bg-[#D7FF4A] text-[#0E0E10]'
                                                            : 'bg-zinc-800 text-zinc-300'
                                                    }`}>
                                                        {f.marcada ? 'Asistencia cerrada' : 'Sin cerrar'}
                                                    </span>
                                                    <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-zinc-300">
                                                        {ETIQUETA_ESTADO[f.estado] || 'Clase'}
                                                    </span>
                                                </div>
                                            </div>
                                            <div className="mt-2.5 flex flex-wrap items-center gap-5">
                                                <Contador valor={f.presentes} label="presentes"
                                                    color="text-[#D7FF4A]" />
                                                <Contador valor={f.ausentes} label="no shows"
                                                    color="text-amber-200" />
                                                <Contador valor={f.reservas} label="reservas" />
                                                <Contador valor={f.cupos} label="cupos" />
                                                <Contador valor={`${f.pct}%`} label="del cupo" />
                                            </div>
                                            <div className="mt-3 grid gap-3 lg:grid-cols-2">
                                                <ListaAlumnos tono="ok" items={f.alumnosPresentes}
                                                    vacio="Todavía no marcó nadie" />
                                                <ListaAlumnos tono="no" items={f.alumnosAusentes}
                                                    vacio="Nadie faltó en este bloque" />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

export default HistorialAsistencia;

