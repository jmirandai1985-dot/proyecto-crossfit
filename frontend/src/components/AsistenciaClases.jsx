import React, { useEffect, useMemo, useRef, useState } from 'react';
// Deep-link del botón "Marcar asistencia" del Resumen del coach: llega con `?clase=<id>` y esa
// clase se abre sola (ver el efecto de más abajo). Va por query y NO por prop: la firma de este
// componente la fijan los tests de franjas/walk-in y el admin lo monta sin argumentos.
import { useLocation } from 'react-router-dom';
import AsistenciaGrupoDisciplina from './AsistenciaGrupoDisciplina';
import AsistenciaFranja from './AsistenciaFranja';
// El corte por franja (Mañana/Tarde/Noche) vive en un util compartido con test propio:
// el Inicio móvil del admin y esta pestaña no pueden decir cosas distintas del mismo día.
import { FRANJAS, agruparPorFranja } from '../utils/franjasAsistencia';
// Filtro por disciplina del panel del admin: mismo criterio de datos que el resto del panel
// (`disciplina_nombre` de cada clase), sin catálogo propio ni request extra.
import {
    TODAS, disciplinasDe, filtroEfectivo, filtrarPorDisciplina, hayQueFiltrar,
} from '../utils/filtroDisciplina';
// Fase 2 (Bloque 2): las clases del día y el detalle de cada una salen de la caché
// compartida (la pestaña Asistencia del coach y del admin piden lo MISMO) y confirmar la
// asistencia es una mutación que invalida la familia `['asistencia']`.
import {
    useAlumnosDeClase, useAmpliarCupo, useClasesAsistenciaHoy, useConfirmarAsistenciaClase,
} from '../hooks/queries';
// Walk-in del coach ("+ Agregar alumno sin reserva"): reserva normal si el alumno tiene
// créditos, presencia sin cargo si no. El admin NO lo monta (ver la prop).
import ModalAgregarSinReserva from './ModalAgregarSinReserva';
// Bloque 2: el resultado del walk-in se avisa con un toast (el texto lo arma el modal).
import Toast from './Toast';

/**
 * Pestaña "Asistencia" (compartida coach + admin, Fase 1).
 *
 * Muestra TODAS las clases del día actual (America/Santiago) —pasadas, en curso y por
 * venir—. El backend filtra por rol: el coach ve las suyas (las tres vías de "mis clases":
 * asignadas a él, de su horario vigente o de una disciplina que dicta, igual que su
 * Resumen); el admin/administrador ve TODAS las clases del tenant.
 * Al abrir una clase, lista las reservas con checks PRE-MARCADOS (si la clase
 * aún no fue marcada) y un botón único "Confirmar" que envía el batch a
 * POST /api/v1/asistencia/clases/{id}/confirmar (el backend registra la marca
 * como "via=admin" cuando la hace un admin).
 *
 * Prop:
 *   variant — 'light' (default, paneles claros, usado en el Dashboard Coach)
 *             | 'dark' (paneles zinc, usado en el panel de Administración)
 *   franjas — false (default): el acordeón por disciplina, en cualquier ancho.
 *             true: en <768px las clases del día se agrupan por franja (Mañana/Tarde/
 *             Noche) al estilo del mockup 6b, con la fila compacta por clase (y sus
 *             contadores "con reserva / ya marcaron / faltan") y un selector de 4 pestañas
 *             que FILTRA la lista (deja a la vista sólo la franja elegida; "Todas" las
 *             muestra juntas); en ≥768px (tablet y escritorio) sigue EXACTAMENTE el acordeón
 *             por disciplina.
 *             Lo pide el coach (`DashboardCoach`, ?tab=asistencia) y NO el admin: su
 *             pestaña Asistencia monta el componente sin la prop y no cambia nada.
 *   permitirSinReserva — false (default): agrega el botón "+ Agregar alumno sin reserva"
 *             dentro del detalle de la clase, que abre `ModalAgregarSinReserva` (el
 *             walk-in: reserva normal si el alumno tiene créditos, presencia sin cargo si
 *             no). Lo pide el coach; el admin monta el componente sin la prop, así que su
 *             pestaña Asistencia queda EXACTAMENTE igual (mismo DOM).
 *   permitirFiltroDisciplina — false (default): muestra el selector "Disciplina" sobre la
 *             lista del día (sólo si hay más de una). Lo pide el admin; el coach conserva
 *             su pantalla sin controles extra. El filtro es en memoria: la lista del día ya
 *             vino completa y `disciplina_nombre` es el mismo dato que agrupa el acordeón.
 */
const AsistenciaClases = ({
    variant = 'light', franjas = false, permitirSinReserva = false,
    permitirFiltroDisciplina = false,
} = {}) => {
    const osc = variant === 'dark';

    // ─── Clases de hoy (React Query) ───────────────────────────────────
    const clasesQ = useClasesAsistenciaHoy();
    // Memorizado porque el `|| []` fabrica un array NUEVO en cada render: sin esto, el
    // `useMemo` de `grupos` y el efecto del deep-link `?clase=` (más abajo) dependerían de un
    // valor distinto en cada pasada (ver el lint del archivo).
    const clases = useMemo(() => clasesQ.data || [], [clasesQ.data]);
    // Filtro del panel del admin: las opciones salen de las MISMAS clases del día y el valor
    // elegido se cae a "Todas" si esa disciplina ya no está (p. ej. cambió el día).
    const [filtroDisciplina, setFiltroDisciplina] = useState(TODAS);
    const disciplinasDisponibles = useMemo(() => disciplinasDe(clases), [clases]);
    const disciplinaEfectiva = filtroEfectivo(filtroDisciplina, disciplinasDisponibles);
    const visibles = useMemo(
        () => (permitirFiltroDisciplina
            ? filtrarPorDisciplina(clases, disciplinaEfectiva)
            : clases),
        [clases, permitirFiltroDisciplina, disciplinaEfectiva],
    );
    const cargando = clasesQ.isPending;
    const error = clasesQ.isError
        ? (clasesQ.error?.response?.data?.detail || 'Error al cargar las clases de hoy')
        : null;

    // ─── Clase abierta ─────────────────────────────────────────────────
    const [claseSeleccionada, setClaseSeleccionada] = useState(null);
    const [aviso, setAviso] = useState(null);
    // Bloque 2: el walk-in avisa con un toast (el texto viaja en `alumno.mensaje`, escrito por
    // el modal pegado a la rama que se ejecutó de verdad). `aviso` sigue siendo el bloque de
    // "Asistencia guardada" y el error del detalle de la clase.
    const [toast, setToast] = useState(null);
    // Walk-in: el modal "Agregar alumno sin reserva" de la clase abierta (sólo coach).
    const [modalSinReserva, setModalSinReserva] = useState(false);
    // Bloque 4 + punto 1 del reporte móvil: franja elegida en el selector del teléfono.
    // 'todas' = las tres franjas; cualquier otro valor FILTRA la lista y deja a la vista sólo
    // esa franja. El agrupamiento y los contadores siguen saliendo de `franjasConClases` (nada
    // se recalcula): filtrar es elegir qué secciones se dibujan.
    const [franjaActiva, setFranjaActiva] = useState('todas');

    const alumnosQ = useAlumnosDeClase(claseSeleccionada?.id);
    const reservas = useMemo(() => alumnosQ.data?.reservas || [], [alumnosQ.data]);
    const marcada = !!alumnosQ.data?.marcada;
    const cargandoReservas = Boolean(claseSeleccionada) && alumnosQ.isPending;

    // Si el detalle de la clase falla, el aviso del modal lo dice (mismo texto de antes).
    const mensaje = alumnosQ.isError
        ? {
            tipo: 'error',
            texto: alumnosQ.error?.response?.data?.detail || 'Error al cargar los alumnos de la clase',
        }
        : aviso;

    const confirmarAsistencia = useConfirmarAsistenciaClase();
    const ampliarCupoMut = useAmpliarCupo();
    const confirmando = confirmarAsistencia.isPending;

    // El marcado: la BASE es lo que dice el backend (si la clase ya fue marcada, lo
    // guardado; si no, NINGUNO — así un clic en Confirmar no marca la clase entera por
    // accidente) y `overrides` guarda SÓLO las decisiones del usuario. Sin estado que
    // haya que sembrar cuando llega la respuesta.
    const [overrides, setOverrides] = useState({});
    const guardado = useMemo(() => {
        const m = {};
        reservas.forEach((a) => { m[a.reserva_id] = !!a.asistio; });
        return m;
    }, [reservas]);
    const valor = (reservaId) => (
        reservaId in overrides ? overrides[reservaId] : (marcada ? !!guardado[reservaId] : false)
    );

    const formatearHora = (h) => {
        if (!h) return '';
        const partes = h.split(':');
        if (partes.length >= 2) return `${partes[0]}:${partes[1]}`;
        return h;
    };

    const abrirClase = (clase) => {
        setAviso(null);
        setOverrides({});   // cada clase arranca con su propio marcado
        setClaseSeleccionada(clase);
    };

    // ─── Deep-link `?clase=<id>` (el botón "Marcar asistencia" del Resumen) ────────────────
    // Abre el detalle de la clase pedida cuando la lista del día ya llegó. El guardia es el
    // `key` de la entrada de historial —una por navegación, incluso repitiendo la misma URL—:
    // así un refetch (el latido del reloj invalida `['asistencia']`) no vuelve a abrir el modal
    // que el usuario acaba de cerrar, pero volver a tocar el botón para la MISMA clase sí lo
    // reabre. Se escriben los tres setters a mano (en vez de llamar a `abrirClase`) para que la
    // lista de dependencias quede completa sin atar el efecto a una función nueva por render.
    const location = useLocation();
    const clasePedida = new URLSearchParams(location.search).get('clase');
    const pedidoAbiertoRef = useRef(null);
    useEffect(() => {
        if (!clasePedida || cargando) return;
        if (pedidoAbiertoRef.current === location.key) return;
        const encontrada = clases.find((c) => String(c.id) === clasePedida);
        if (!encontrada) return;
        pedidoAbiertoRef.current = location.key;
        setAviso(null);
        setOverrides({});
        setClaseSeleccionada(encontrada);
    }, [clasePedida, location.key, cargando, clases]);

    const cerrarClase = () => {
        setClaseSeleccionada(null);
        setOverrides({});
        setAviso(null);
        setModalSinReserva(false);
    };

    const toggle = (reservaId) => {
        setOverrides((prev) => ({ ...prev, [reservaId]: !valor(reservaId) }));
    };

    const marcarTodos = (valorNuevo) => {
        const nuevo = {};
        reservas.forEach((a) => { nuevo[a.reserva_id] = valorNuevo; });
        setOverrides(nuevo);
    };

    const confirmar = async () => {
        if (!claseSeleccionada) return;
        setAviso(null);
        try {
            const asistencias = reservas.map((a) => ({
                reserva_id: parseInt(a.reserva_id, 10),
                asistio: !!valor(a.reserva_id),
            }));
            const r = await confirmarAsistencia.mutateAsync({
                claseId: claseSeleccionada.id,
                asistencias,
            });
            const confirmados = r?.confirmados ?? asistencias.length;
            cerrarClase();
            // La lista del día y el detalle de la clase se refrescan SOLOS (la mutación
            // invalida `['asistencia']`): la misma verdad para el panel del admin.
            setAviso({ tipo: 'exito', texto: `✅ Asistencia guardada (${confirmados} alumno(s))` });
        } catch (e) {
            setAviso({ tipo: 'error', texto: e.response?.data?.detail || 'Error al guardar la asistencia' });
        }
    };

    // Fase 2: agrupacion por disciplina respetando el orden del backend (dentro de
    // cada grupo tambien). El acordeon arranca abierto y el estado es local, no
    // persistido: al recargar vuelven a estar todos abiertos.
    const [cerradas, setCerradas] = useState({});
    const estaAbierta = (disciplina) => !cerradas[disciplina];
    const toggleGrupo = (disciplina) =>
        setCerradas((prev) => ({ ...prev, [disciplina]: !prev[disciplina] }));

    const grupos = useMemo(() => {
        const m = new Map();
        for (const c of visibles) {
            const k = c.disciplina_nombre || 'Sin disciplina';
            if (!m.has(k)) m.set(k, []);
            m.get(k).push(c);
        }
        return [...m.entries()].map(([disciplina, items]) => ({ disciplina, clases: items }));
    }, [visibles]);

    // Vista de teléfono (mockup 6b): las MISMAS clases del día repartidas por franja. El
    // corte lo hace el util compartido y acá sólo se eligen las franjas con clases (una
    // franja vacía no se dibuja: en el teléfono cada bloque ocupa media pantalla).
    // Sin `useMemo`: el corte de `agruparPorFranja` es barato y `clases` sólo cambia cuando
    // llega dato nuevo, así que memorizarlo no ahorraría nada (ver el lint del archivo).
    const porFranja = franjas ? agruparPorFranja(visibles) : null;
    const franjasConClases = porFranja
        ? FRANJAS.filter((f) => (porFranja[f.id] || []).length > 0)
        : [];

    // ── Bloque 4 + punto 1: el selector de franja (sólo teléfono, dentro del bloque de franjas) ──
    // Cuántas clases tiene cada franja: sale del MISMO `agruparPorFranja` que dibuja las
    // secciones, así el número del botón y el contenido de la sección no pueden diferir.
    const totalesFranja = (id) => (porFranja?.[id] || []).length;
    // Punto 1 del reporte móvil: lo que se dibuja es la franja ELEGIDA (o todas). Una franja
    // sin clases no se dibuja nunca, así que la lista sale de `franjasConClases`.
    const franjasVisibles = franjaActiva === 'todas'
        ? franjasConClases
        : franjasConClases.filter((f) => f.id === franjaActiva);
    // Estilo de cada pestaña: dos renglones (rótulo + cuántas clases) y ancho parejo. Antes las
    // cuatro iban en una fila `flex-none` que no entraba en 360px: el rótulo se veía apretado y
    // la última quedaba cortada contra el borde del panel. Con la grilla de 4 columnas iguales
    // ninguna se recorta y el número tiene su propio renglón.
    const tabFranja = (activo) => `flex min-w-0 flex-col items-center justify-center rounded-xl border px-1 py-1.5 leading-tight transition-colors ${activo
        ? (osc ? 'border-orange-500 bg-orange-500/15 text-orange-300' : 'border-orange-500 bg-orange-50 text-orange-700')
        : (osc ? 'border-zinc-800 bg-zinc-900 text-zinc-400' : 'border-gray-200 bg-white text-gray-500')}`;
    // Punto 1: cambiar de pestaña FILTRA (ya no salta a la sección). Como el contenido de abajo
    // pasa a ser otro, se vuelve al tope del contenedor —el que scrollea es el `main` del
    // Layout— para que la primera clase de la franja elegida quede a la vista.
    const irAFranja = (id) => {
        setFranjaActiva(id);
        document.querySelector('main')?.scrollTo({ top: 0, behavior: 'smooth' });
    };

    // Ampliar cupo de UNA clase puntual (el backend valida permisos y el tope +10).
    // Devuelve la promesa: el hijo pinta el cupo nuevo con la respuesta.
    const ampliarCupo = (clase, extra) => ampliarCupoMut.mutateAsync({ claseId: clase.id, extra });

    return (
        <div className="space-y-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 className={`text-2xl font-bold ${osc ? 'text-zinc-100' : 'text-gray-900'}`}>📋 Asistencia de Hoy</h2>
                    <p className={`mt-1 ${osc ? 'text-zinc-400' : 'text-gray-600'}`}>
                        Clases de HOY (hora de Chile): las que ya pasaron, la que está en curso y
                        las que vienen. Confirma la asistencia de cada clase con un clic.
                    </p>
                </div>
                {permitirFiltroDisciplina && hayQueFiltrar(disciplinasDisponibles) && (
                    <div className="flex items-center gap-2">
                        <label htmlFor="asistencia-filtro-disciplina"
                            className={`text-xs font-medium ${osc ? 'text-zinc-400' : 'text-gray-500'}`}>
                            Disciplina
                        </label>
                        <select id="asistencia-filtro-disciplina"
                            data-testid="admin-asistencia-filtro-disciplina"
                            value={disciplinaEfectiva}
                            onChange={(e) => setFiltroDisciplina(e.target.value)}
                            className={`rounded-lg border px-3 py-1.5 text-sm focus:outline-none ${osc
                                ? 'border-zinc-700 bg-zinc-900 text-zinc-200 focus:border-orange-500'
                                : 'border-gray-300 bg-white text-gray-700 focus:border-orange-500'}`}>
                            <option value={TODAS}>Todas</option>
                            {disciplinasDisponibles.map((d) => (
                                <option key={d} value={d}>{d}</option>
                            ))}
                        </select>
                    </div>
                )}
            </div>

            {error && (
                <div className={`border-l-4 rounded-lg p-4 text-sm ${osc ? 'bg-red-500/10 border-red-500 text-red-300' : 'bg-red-50 border-red-500 text-red-700'}`}>
                    {error}
                </div>
            )}

            {cargando ? (
                <div className="flex items-center justify-center h-40">
                    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500"></div>
                </div>
            ) : clases.length === 0 ? (
                <div className={`text-center py-16 rounded-xl shadow-sm border ${osc ? 'bg-zinc-900 border-zinc-800' : 'bg-white border-gray-100'}`}>
                    <p className="text-5xl mb-4">📭</p>
                    <p className={`text-xl font-bold ${osc ? 'text-zinc-200' : 'text-gray-700'}`}>Sin clases hoy</p>
                    <p className={`text-sm mt-2 ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>
                        No hay clases de hoy en tus clases asignadas ni en tus disciplinas.
                    </p>
                </div>
            ) : (
                <>
                    {/* <768px (sólo con `franjas`): las clases del día por franja (mockup 6b). */}
                    {franjas && (
                        <div className="md:hidden space-y-5" data-testid="asistencia-franjas">
                            {/* Bloque 4 + punto 1: elegir la franja. Va pegado arriba
                                (`sticky`) porque el que scrollea es el contenedor del Layout y
                                en >=768px no existe (esta rama es `md:hidden`), así que la vista
                                de escritorio no cambia. */}
                            <div
                                data-testid="selector-franja"
                                className={`sticky top-0 z-10 -mx-1 grid grid-cols-4 gap-1.5 px-1 py-1.5 ${osc ? 'bg-zinc-950' : 'bg-white'}`}
                            >
                                <button
                                    type="button"
                                    onClick={() => irAFranja('todas')}
                                    aria-pressed={franjaActiva === 'todas'}
                                    data-testid="franja-tab-todas"
                                    className={tabFranja(franjaActiva === 'todas')}
                                >
                                    <span className="max-w-full truncate text-[11.5px] font-bold">Todas</span>
                                    <span className="text-[10px] font-semibold opacity-70">{clases.length}</span>
                                </button>
                                {FRANJAS.map((f) => {
                                    const n = totalesFranja(f.id);
                                    return (
                                        <button
                                            key={f.id}
                                            type="button"
                                            onClick={() => irAFranja(f.id)}
                                            disabled={n === 0}
                                            title={n === 0 ? `Sin clases en la franja ${f.label}` : undefined}
                                            aria-pressed={franjaActiva === f.id}
                                            data-testid={`franja-tab-${f.id}`}
                                            className={`${tabFranja(franjaActiva === f.id)} disabled:opacity-40 disabled:cursor-not-allowed`}
                                        >
                                            <span className="max-w-full truncate text-[11.5px] font-bold">{f.label}</span>
                                            <span className="text-[10px] font-semibold opacity-70">{n}</span>
                                        </button>
                                    );
                                })}
                            </div>
                            {franjasVisibles.map((f) => (
                                <AsistenciaFranja
                                    key={f.id}
                                    franja={f}
                                    clases={porFranja[f.id]}
                                    osc={osc}
                                    formatearHora={formatearHora}
                                    onAbrir={abrirClase}
                                    onAmpliarCupo={ampliarCupo}
                                />
                            ))}
                        </div>
                    )}

                    {/* ≥768px (y siempre que no se pida `franjas`): el acordeón por disciplina. */}
                    <div className={franjas ? 'hidden md:block space-y-4' : 'space-y-4'}>
                        {grupos.map((grupo) => (
                            <AsistenciaGrupoDisciplina
                                key={grupo.disciplina}
                                grupo={grupo}
                                osc={osc}
                                abierta={estaAbierta(grupo.disciplina)}
                                onToggle={() => toggleGrupo(grupo.disciplina)}
                                onAbrir={abrirClase}
                                formatearHora={formatearHora}
                                onAmpliarCupo={ampliarCupo}
                            />
                        ))}
                    </div>
                </>
            )}


            {/* Modal de confirmación por clase */}
            {claseSeleccionada && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className={`rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col ${osc ? 'bg-zinc-900 border border-zinc-800' : 'bg-white'}`}>
                        <div className={`px-6 py-4 border-b flex items-center justify-between ${osc ? 'border-zinc-800' : 'border-gray-200'}`}>
                            <div>
                                <h3 className={`text-lg font-bold ${osc ? 'text-zinc-100' : 'text-gray-900'}`}>
                                    {claseSeleccionada.disciplina_nombre}
                                </h3>
                                <p className={`text-sm ${osc ? 'text-zinc-400' : 'text-gray-600'}`}>
                                    🕐 {formatearHora(claseSeleccionada.hora_inicio)} -{' '}
                                    {formatearHora(claseSeleccionada.hora_fin)} · {reservas.length} reservas
                                </p>
                            </div>
                            <button
                                onClick={cerrarClase}
                                className={`text-2xl leading-none ${osc ? 'text-zinc-500 hover:text-zinc-300' : 'text-gray-400 hover:text-gray-600'}`}
                                aria-label="Cerrar"
                            >
                                ×
                            </button>
                        </div>

                        <div className="px-6 py-4 overflow-y-auto">
                            {mensaje && (
                                <div
                                    data-testid="aviso-asistencia"
                                    className={`mb-3 px-3 py-2 rounded-md text-sm font-medium border ${
                                        mensaje.tipo === 'exito'
                                            ? (osc ? 'bg-green-500/10 text-green-400 border-green-500/30' : 'bg-green-50 text-green-700 border-green-200')
                                            : (osc ? 'bg-red-500/10 text-red-400 border-red-500/30' : 'bg-red-50 text-red-700 border-red-200')
                                    }`}
                                >
                                    {mensaje.texto}
                                </div>
                            )}

                            <p className={`text-sm font-medium mb-3 ${osc ? 'text-zinc-300' : 'text-gray-700'}`}>
                                {marcada
                                    ? 'Asistencia ya guardada — corrige si hace falta y reconfirma.'
                                    : 'Todos los alumnos vienen marcados por defecto.'}
                            </p>

                            <div className="flex gap-2 mb-3">
                                <button
                                    onClick={() => marcarTodos(true)}
                                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                                        osc ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-green-100 text-green-700 hover:bg-green-200'
                                    }`}
                                >
                                    ✓ Todos asistieron
                                </button>
                                <button
                                    onClick={() => marcarTodos(false)}
                                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                                        osc ? 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                                    }`}
                                >
                                    ✗ Ninguno
                                </button>
                            </div>

                            {cargandoReservas ? (
                                <div className="flex items-center justify-center py-10">
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                                </div>
                            ) : reservas.length === 0 ? (
                                <p className={`text-center py-10 text-sm ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>
                                    Esta clase no tiene reservas activas.
                                </p>
                            ) : (
                                <ul className="space-y-2">
                                    {reservas.map((a) => (
                                        <li
                                            key={a.reserva_id}
                                            className={`flex items-center justify-between p-3 rounded-lg border ${osc ? 'border-zinc-800' : 'border-gray-200'}`}
                                        >
                                            <span className={`text-sm font-medium ${osc ? 'text-zinc-200' : 'text-gray-800'}`}>{a.nombre}</span>
                                            <label className="flex items-center gap-2 cursor-pointer select-none">
                                                <span className={`text-xs ${osc ? 'text-zinc-500' : 'text-gray-500'}`}>Asistió</span>
                                                <input
                                                    type="checkbox"
                                                    checked={valor(a.reserva_id)}
                                                    onChange={() => toggle(a.reserva_id)}
                                                    className="w-5 h-5 accent-orange-500"
                                                />
                                            </label>
                                        </li>
                                    ))}
                                </ul>
                            )}

                            {/* Walk-in del coach: se ofrece DESPUÉS de la lista de reservas
                                ("reviso a quien falta y lo agrego"), igual que el mockup. */}
                            {permitirSinReserva && (
                                <button
                                    type="button"
                                    onClick={() => setModalSinReserva(true)}
                                    data-testid="agregar-sin-reserva"
                                    className={`mt-4 flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed px-3 py-2.5 text-sm font-semibold transition-colors ${osc
                                        ? 'border-zinc-700 text-amber-200 hover:border-amber-500/60'
                                        : 'border-gray-300 text-gray-600 hover:border-orange-400 hover:text-orange-600'
                                        }`}
                                >
                                    ➕ Agregar alumno sin reserva
                                </button>
                            )}
                        </div>
                        <div className={`px-6 py-4 border-t flex justify-end gap-2 ${osc ? 'border-zinc-800' : 'border-gray-200'}`}>
                            <button
                                onClick={cerrarClase}
                                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                                    osc ? 'text-zinc-300 hover:bg-zinc-800' : 'text-gray-600 hover:bg-gray-100'
                                }`}
                            >
                                Cancelar
                            </button>
                            <button
                                onClick={confirmar}
                                disabled={confirmando || reservas.length === 0}
                                className="px-6 py-2 bg-orange-500 text-white rounded-lg text-sm font-bold hover:bg-orange-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {confirmando ? 'Guardando...' : 'Confirmar'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Walk-in ("+ Agregar alumno sin reserva"): sólo con la prop, así la pestaña
                Asistencia del ADMIN queda idéntica. El aviso de resultado reusa el mismo
                bloque `mensaje` que ya muestra "Asistencia guardada". */}
            {permitirSinReserva && modalSinReserva && claseSeleccionada && (
                <ModalAgregarSinReserva
                    clase={claseSeleccionada}
                    onCerrar={() => setModalSinReserva(false)}
                    onAgregado={(alumno) => {
                        setModalSinReserva(false);
                        // Bloque 2: el modal ya pidió confirmación y ejecutó el endpoint; acá
                        // sólo se muestra su texto (mismo aviso para las dos ramas: el cartel
                        // dice si descontó token, si era ilimitado o si quedó sin cargo).
                        setToast(alumno.mensaje);
                        setTimeout(() => setToast(null), 2600);
                    }}
                />
            )}

            {/* Bloque 2: el aviso del walk-in sobrevive al cierre del modal (por eso el toast
                vive acá y no adentro del modal, que se desmonta). */}
            <Toast texto={toast} />
        </div>
    );
};

export default AsistenciaClases;
