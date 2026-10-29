import React, { useMemo, useState } from 'react';
// El mes entero (clases + alumnos) sale de UNA consulta cacheada: abrir un día del calendario
// no vuelve a pegarle a la API.
import { useHistorialAsistencia } from '../hooks/queries';
// Todas las cuentas (anillos, totales, grilla del calendario) viven en el util COMPARTIDO y
// puro: la pantalla no hace aritmética propia (ver `utils/historialAsistencia.js`).
import {
    DIAS_SEMANA, aniosDisponibles, calendarioDelMes, clasesOcurridas, fechaSola,
    filtrarPorHorario, horariosDe, mesesDelAnio, nombreMes, resumenDia,
    resumenPorDiaSemana, totalesDe,
} from '../utils/historialAsistencia';
// El criterio de disciplina es el MISMO del resto del panel (`disciplina_nombre` que ya
// devuelve el backend): no hay catálogo propio ni una segunda forma de comparar.
import { TODAS, disciplinasDe, filtroEfectivo, filtrarPorDisciplina } from '../utils/filtroDisciplina';

/**
 * "Historial de Asistencia" (coach + admin) — SÓLO LECTURA.
 *
 * Tres niveles del mismo mes, sin volver a pedir datos:
 *   1. el ANILLO de cada día de la semana (lunes→domingo): % de asistencia contra los CUPOS
 *      de las clases YA OCURRIDAS de ese día de la semana en el mes; al tocarlo se abren las
 *      dos listas del mockup (quiénes vinieron y quiénes no, con la cantidad de veces de cada
 *      uno);
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
 *
 * Prop:
 *   permitirFiltros — false (default): el coach sigue viendo el mes completo tal cual.
 *             true: el admin suma los selectores "Disciplina" y "Horario" y el recorte
 *             alimenta TODAS las vistas (anillos, calendario, totales y detalle). Anillos
 *             y totales además miran sólo clases ya ocurridas; el calendario y el detalle
 *             del día conservan el mes entero. El filtro es en memoria: el mes ya se pidió
 *             UNA vez.
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
    // Sin cupo (Musculación / Open Box, migración 066): no hay % que colorear.
    if (totales.pct === null) return 'bg-sky-500/10';
    if (totales.pct >= 80) return 'bg-emerald-500/15';
    if (totales.pct >= 60) return 'bg-[#D7FF4A]/15';
    if (totales.pct > 0) return 'bg-amber-500/15';
    return 'bg-zinc-800/50';
};

/**
 * El % de un conjunto de totales, o "sin cupo" cuando NINGUNA de sus clases tiene
 * tope (migración 066). No se inventa un 0 %: no hay denominador.
 */
const textoPct = (totales) => (totales?.pct === null ? 'sin cupo' : `${totales?.pct}%`);

/**
 * Texto corto de los cupos de un conjunto: con tope, "presentes de cupos"; con
 * clases de acceso libre, sus reservas como conteo aparte.
 */
const textoCupos = (totales) => {
    if (totales.pct === null) return `${totales.reservasSinTope} reservas (sin cupo)`;
    const base = `${totales.presentesConTope} de ${totales.cupos} cupos`;
    return totales.reservasSinTope > 0
        ? `${base} + ${totales.reservasSinTope} sin cupo`
        : base;
};

const HistorialAsistencia = ({ permitirFiltros = false } = {}) => {
    const hoy = fechaSola();
    // El mes arranca en el ACTUAL (el panel del coach vive en "hoy"); el usuario lo mueve con
    // los dos selectores.
    const [anio, setAnio] = useState(() => Number(hoy.slice(0, 4)));
    const [mes, setMes] = useState(() => Number(hoy.slice(5, 7)));
    // Filtros del admin (en memoria): disciplina y horario de inicio del mes.
    const [filtroDisciplina, setFiltroDisciplina] = useState(TODAS);
    const [filtroHorario, setFiltroHorario] = useState('');
    // Lo que el usuario tiene abierto: un día de la semana (el anillo) y un día del calendario.
    const [diaSemana, setDiaSemana] = useState(null);
    const [fecha, setFecha] = useState(null);

    const historialQ = useHistorialAsistencia(anio, mes);
    // Memorizado: el `|| []` crea un array NUEVO en cada render (mientras carga o si falla), y
    // los cálculos de abajo —que sí valen la pena memorizar— se reharían en cada pasada.
    const clases = useMemo(() => historialQ.data?.clases || [], [historialQ.data]);
    // Opciones del mes completo: elegir una disciplina no hace desaparecer los horarios (ni al
    // revés). Si el mes cambia y la opción ya no existe, se cae a "Todas"/"Todos".
    const disciplinasDisponibles = useMemo(() => disciplinasDe(clases), [clases]);
    const horariosDisponibles = useMemo(() => horariosDe(clases), [clases]);
    const disciplinaEfectiva = filtroEfectivo(filtroDisciplina, disciplinasDisponibles);
    const horarioEfectivo = filtroHorario && horariosDisponibles.includes(filtroHorario)
        ? filtroHorario
        : '';
    // El recorte alimenta TODAS las vistas: anillos, totales, calendario y detalle. Sin la
    // prop (coach) los dos filtros valen "Todas"/"Todos" y la lista queda igual.
    const visibles = useMemo(
        () => filtrarPorHorario(
            filtrarPorDisciplina(clases, disciplinaEfectiva), horarioEfectivo,
        ),
        [clases, disciplinaEfectiva, horarioEfectivo],
    );
    const error = historialQ.isError
        ? (historialQ.error?.response?.data?.detail || 'No se pudo cargar el historial del mes')
        : null;

    // El selector de años nunca queda vacío y siempre incluye el que está elegido.
    const anios = useMemo(() => {
        const lista = aniosDisponibles(anio);
        return lista.length ? lista : [anio];
    }, [anio]);
    const meses = useMemo(() => mesesDelAnio(), []);

    // Anillos y totales: sólo clases ya ocurridas (fecha <= hoy). El calendario y el detalle
    // siguen usando `visibles` completo: el mes se muestra entero, incluso lo que está por venir.
    const ocurridas = useMemo(() => clasesOcurridas(visibles, hoy), [visibles, hoy]);
    const totalMes = useMemo(() => totalesDe(ocurridas), [ocurridas]);
    const semana = useMemo(() => resumenPorDiaSemana(ocurridas), [ocurridas]);
    const semanas = useMemo(
        () => calendarioDelMes(anio, mes, visibles, hoy), [anio, mes, visibles, hoy],
    );
    const detalle = useMemo(() => (fecha ? resumenDia(visibles, fecha) : null), [visibles, fecha]);
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

            {permitirFiltros && (
                <div className={`${TARJETA} flex flex-wrap items-end gap-3 p-4`}
                    data-testid="historial-filtros">
                    <div>
                        <label className={`${ROTULO} mb-1 block`} htmlFor="historial-filtro-disciplina">
                            Disciplina
                        </label>
                        <select id="historial-filtro-disciplina" className={CONTROL}
                            value={disciplinaEfectiva}
                            onChange={(e) => {
                                setFiltroDisciplina(e.target.value);
                                setFecha(null);
                            }}
                            data-testid="historial-filtro-disciplina">
                            <option value={TODAS}>Todas</option>
                            {disciplinasDisponibles.map((d) => (
                                <option key={d} value={d}>{d}</option>
                            ))}
                        </select>
                    </div>
                    <div>
                        <label className={`${ROTULO} mb-1 block`} htmlFor="historial-filtro-horario">
                            Horario
                        </label>
                        <select id="historial-filtro-horario" className={CONTROL}
                            value={horarioEfectivo}
                            onChange={(e) => {
                                setFiltroHorario(e.target.value);
                                setFecha(null);
                            }}
                            data-testid="historial-filtro-horario">
                            <option value="">Todos</option>
                            {horariosDisponibles.map((h) => (
                                <option key={h} value={h}>{h}</option>
                            ))}
                        </select>
                    </div>
                    <p className="text-[11px] text-zinc-500 sm:ml-auto">
                        {visibles.length} clase{visibles.length === 1 ? '' : 's'} con los filtros
                    </p>
                </div>
            )}

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
                    {/* ── 2. Totales del mes elegido (sólo clases ya ocurridas; el % es contra
                        los CUPOS, igual que los anillos) ── */}
                    <div className={`${TARJETA} flex flex-wrap items-center justify-between gap-5 p-4`}>
                        <div>
                            <p className={ROTULO}>Totales del mes (clases ya ocurridas)</p>
                            <p className="mt-1 text-2xl font-black text-white">
                                {nombreMes(mes)} {anio}
                            </p>
                            <p className="mt-1 text-[11.5px] text-zinc-500">
                                {totalMes.cupos} cupos ofrecidos en{' '}
                                {totalMes.clases - totalMes.clasesSinTope} clase
                                {totalMes.clases - totalMes.clasesSinTope === 1 ? '' : 's'} con cupo
                                {totalMes.clasesSinTope > 0 && (
                                    <>
                                        {' · '}{totalMes.reservasSinTope} reservas en{' '}
                                        {totalMes.clasesSinTope} clase
                                        {totalMes.clasesSinTope === 1 ? '' : 's'} de acceso libre (sin cupo)
                                    </>
                                )}
                                {' · '}{totalMes.cerradas} con la asistencia cerrada
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-6">
                            <Contador valor={totalMes.clases} label="clases" />
                            <Contador valor={totalMes.presentes} label="presentes"
                                color="text-[#D7FF4A]" />
                            <Contador valor={totalMes.ausentes} label="no shows"
                                color="text-amber-200" />
                            <Contador valor={`${textoPct(totalMes)}`} label="asistencia (con cupo)" />
                            {totalMes.reservasSinTope > 0 && (
                                <Contador valor={totalMes.reservasSinTope} label="reservas sin cupo"
                                    color="text-sky-300" />
                            )}
                        </div>
                    </div>

                    {visibles.length === 0 && (
                        <p className="rounded-[14px] border border-[#2A2A2E] bg-[#18181B] p-4 text-[13px] text-zinc-400">
                            {clases.length === 0
                                ? `${nombreMes(mes)} ${anio} no tiene clases cargadas.`
                                : 'No hay clases con los filtros elegidos.'}
                            {clases.length === 0 && (historialQ.data?.alcance === 'coach'
                                ? ' Probá con otro mes: acá sólo aparecen las clases tuyas.'
                                : ' Probá con otro mes del selector.')}
                        </p>
                    )}

                    {/* ── 3. Un anillo por día de la semana (lunes→domingo) ──
                        El % es contra los CUPOS de las clases YA OCURRIDAS de ese día de la
                        semana en el mes: un martes con tres bloques no se mira contra un domingo
                        de uno. Las clases futuras no tienen asistencia que medir y no inflan el
                        denominador. Tocar un círculo abre sus dos listas (vinieron / no vinieron). */}
                    <div className={`${TARJETA} p-4`}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className={ROTULO}>Asistencia del mes por día de la semana</p>
                            <p className="text-[11px] text-zinc-500">
                                Sólo clases ya ocurridas · Toca un círculo para ver quiénes vinieron
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
                                        title={`${d.largo}: ${textoCupos(d.totales)} en ${d.totales.clases} clase(s) ya ocurridas del mes`}
                                        data-testid={`historial-anillo-${d.clave}`}
                                        className={`flex flex-col items-center gap-1.5 rounded-[14px] border px-1 py-2.5 transition-colors ${
                                            activo
                                                ? 'border-[#D7FF4A] bg-[#1F2412]'
                                                : 'border-[#2A2A2E] bg-[#121214] hover:border-zinc-600'
                                        }`}>
                                        {/* Sin cupo (migración 066): el anillo queda vacío y el
                                            centro muestra el CONTEO de reservas, no un %. */}
                                        <Anillo pct={d.pct ?? 0} tamano={78} grosor={9}>
                                            <span className={`text-[15px] font-black ${
                                                vacio ? 'text-zinc-600'
                                                    : d.pct === null ? 'text-sky-300'
                                                        : COLOR_PCT(d.pct)}`}>
                                                {vacio ? '—' : d.pct === null
                                                    ? d.totales.reservasSinTope
                                                    : `${d.pct}%`}
                                            </span>
                                        </Anillo>
                                        <span className="text-[12px] font-extrabold uppercase tracking-wide text-zinc-300">
                                            {d.label}
                                        </span>
                                        <span className="text-[10.5px] text-zinc-500">
                                            {vacio
                                                ? 'sin clases'
                                                // El denominador son los cupos de las clases CON TOPE ya
                                                // ocurridas de ESE día de la semana EN EL MES (5 jueves ×
                                                // ~24 clases). Las salas de acceso libre no suman cupos:
                                                // sus reservas van aparte, como conteo.
                                                : d.pct === null
                                                    ? `${d.totales.reservasSinTope} reservas (sin cupo)`
                                                    : `${d.totales.presentesConTope} de ${d.totales.cupos} cupos (mes)${
                                                        d.totales.reservasSinTope > 0
                                                            ? ` + ${d.totales.reservasSinTope} sin cupo`
                                                            : ''}`}
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
                                        {anilloAbierto.totales.clases === 1 ? '' : 's'} ya ocurridas en {nombreMes(mes)}
                                    </p>
                                    <p className="text-[11.5px] text-zinc-500">
                                        {anilloAbierto.totales.presentes} vinieron ·{' '}
                                        {anilloAbierto.totales.ausentes} no vinieron ·{' '}
                                        {textoPct(anilloAbierto.totales)} del cupo
                                        {anilloAbierto.totales.reservasSinTope > 0 && (
                                            <> · {anilloAbierto.totales.reservasSinTope} reservas sin cupo</>
                                        )}
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
                                                    ? `${celda.fecha} · ${textoCupos(celda.totales)} · ${textoPct(celda.totales)}`
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
                                                        {/* Sin cupo: el número grande son las reservas (no un %). */}
                                                        <span className={`text-[12.5px] font-black ${
                                                            celda.totales.pct === null
                                                                ? 'text-sky-300'
                                                                : COLOR_PCT(celda.totales.pct)}`}>
                                                            {celda.totales.pct === null
                                                                ? celda.totales.reservasSinTope
                                                                : `${celda.totales.pct}%`}
                                                        </span>
                                                        <span className="text-[10px] text-zinc-500">
                                                            {celda.totales.pct === null
                                                                ? 'reservas'
                                                                : `${celda.totales.presentesConTope}/${celda.totales.cupos}`}
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
                                                {/* Migración 066: una sala de acceso libre no tiene
                                                    cupos ni "% del cupo"; se dice tal cual. */}
                                                <Contador valor={f.sinTope ? '—' : f.cupos}
                                                    label={f.sinTope ? 'sin cupo' : 'cupos'} />
                                                <Contador valor={f.pct === null ? '—' : `${f.pct}%`}
                                                    label={f.sinTope ? 'acceso libre' : 'del cupo'} />
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

