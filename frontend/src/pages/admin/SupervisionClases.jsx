import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import Layout from '../../components/Layout';
import api from '../../services/api';
import ModalClase from '../../components/ModalClase';
import SupervisionClaseRow from '../../components/SupervisionClaseRow';
import { fechaSolaAInstante, fmtFechaCortaChile, hoyChileStr } from '../../utils/fecha';

/**
 * Supervisión de Clases (admin) — B5.
 *
 * Qué muestra:
 *   1. GRILLA POR RANGO (vista por defecto): una columna por día del rango
 *      (lunes-sábado: los domingos no hay clases) y una fila por franja horaria.
 *      Cada celda pinta las clases REALES con su marca de cobertura; si el
 *      horario existe pero la clase todavía no se generó, pinta la plantilla en
 *      gris para no dejar el hueco "vacío" (dato de `plantillas`).
 *   2. LEYENDA de las CUATRO marcas + RESUMEN de cobertura del rango.
 *   3. CLASES DE HOY aparte: día completo con el control "Ampliar cupo" de una
 *      clase puntual (hasta +10 sobre su cupo original).
 *   4. Gestión de cupos por disciplina y la vista "por disciplina" (tarjetas +
 *      calendario semanal + reservas self-service).
 *
 * De dónde salen los datos: TODO lo calcula el backend (`/supervision/grilla`,
 * `/clases/`, `/horarios-base`). El frontend no recalcula marcas ni porcentajes:
 * la marca `sin_coach | coach | admin | emergencia` y el 409 de la asignación de
 * emergencia se muestran tal cual los manda el backend.
 *
 * Qué se arregló acá (B5): la grilla semanal era inalcanzable (`vistaModo` nunca
 * cambiaba de 'tarjetas'), el filtro Desde/Hasta no filtraba nada visible, dos
 * `catch` usaban un `error` inexistente (ReferenceError) y el botón de cupos
 * quedaba con contraste bajo sobre el fondo oscuro.
 */

const API_BASE = '/api/v1';

// Límites del cupo por disciplina: los mismos que valida el backend (Query ge=1, le=200).
const CUPO_MIN = 1;
const CUPO_MAX = 200;
// Tope de días que acepta GET /supervision/grilla (app/utils/semana.MAX_DIAS_RANGO).
const MAX_DIAS_RANGO = 62;
// El panel se refresca solo: la grilla cambia cuando un coach toma o suelta.
const POLLING_INTERVALO_MS = 45000;

// Las CUATRO marcas de cobertura, ya calculadas por el backend
// (services/asignaciones_clases.marca_cobertura). El frontend NO las recalcula.
const MARCAS = {
    coach: { icono: '✅', etiqueta: 'Tomada por el coach', chip: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/50' },
    admin: { icono: '🟦', etiqueta: 'Asignada por el admin', chip: 'bg-sky-500/15 text-sky-200 border-sky-500/50' },
    emergencia: { icono: '⚠️', etiqueta: 'Cobertura de emergencia', chip: 'bg-amber-500/15 text-amber-200 border-amber-500/50' },
    sin_coach: { icono: '🔴', etiqueta: 'Sin coach', chip: 'bg-red-500/15 text-red-200 border-red-500/50' },
};
const marca = (m) => MARCAS[m] || MARCAS.sin_coach;

// 0 = Lunes … 6 = Domingo (la convención del backend, NO la de PostgreSQL).
const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

const fmtHora = (h) => (h ? String(h).slice(0, 5) : '');

/** Fecha 'YYYY-MM-DD' de `fecha` ± `dias` (calendario chileno, ver utils/fecha.js). */
const sumarDias = (fecha, dias) => {
    const base = fechaSolaAInstante(fecha);
    return hoyChileStr(new Date(base.getTime() + dias * 86400000));
};

/** Lunes de la semana de `fecha` (0 = Lunes, igual que el backend). */
const lunesDe = (fecha) => {
    const dowJs = fechaSolaAInstante(fecha).getUTCDay(); // 0 = Domingo … 6 = Sábado
    return sumarDias(fecha, -((dowJs + 6) % 7));
};

/** Días de calendario entre `desde` y `hasta`, ambos incluidos. */
const diasDelRango = (desde, hasta) => {
    const a = fechaSolaAInstante(desde).getTime();
    const b = fechaSolaAInstante(hasta).getTime();
    return Math.floor((b - a) / 86400000) + 1;
};

/** Chip de UNA clase real dentro de una celda de la grilla. */
function ChipClase({ clase, onAbrir }) {
    const m = marca(clase.marca);
    return (
        <button
            type="button"
            onClick={() => onAbrir(clase)}
            title={`${clase.disciplina_nombre} · ${m.etiqueta} · ${clase.coach_nombre || 'Sin coach'} · ${clase.asistentes_confirmados || 0}/${clase.cupo_maximo ?? '?'} · click para asignar o quitar coach`}
            className={`w-full text-left mb-1 px-2 py-1.5 rounded border ${m.chip} hover:brightness-125 transition`}
        >
            <div className="flex items-center gap-1">
                <span aria-hidden="true">{m.icono}</span>
                <span className="truncate font-medium">{clase.disciplina_nombre}</span>
            </div>
            <div className="text-[11px] truncate opacity-90">{clase.coach_nombre || 'Sin coach'}</div>
            <div className="text-[11px] opacity-80">
                {clase.asistentes_confirmados || 0}/{clase.cupo_maximo ?? '?'}
                {clase.wod_id ? ' · 📝 WOD' : ''}
            </div>
        </button>
    );
}

/** Plantilla del horario sin clase generada (para que la grilla no tenga huecos). */
function PlantillaFantasma({ plantilla }) {
    return (
        <div
            title={`Horario fijo ${plantilla.hora_inicio}-${plantilla.hora_fin}${plantilla.coach_nombre ? ` · ${plantilla.coach_nombre}` : ''} (la clase de este día todavía no se generó)`}
            className="mb-1 px-2 py-1.5 rounded border border-dashed border-zinc-700 bg-zinc-800/30 text-zinc-500"
        >
            <div className="truncate text-[12px]">{plantilla.disciplina_nombre}</div>
            <div className="truncate text-[11px]">
                {plantilla.coach_nombre ? `👤 ${plantilla.coach_nombre}` : '⚠️ sin coach fijo'}
            </div>
        </div>
    );
}

/** Tarjeta chica del resumen de cobertura. */
function Tarjeta({ label, valor, detalle, tono = 'text-zinc-100' }) {
    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</p>
            <p className={`text-xl font-bold ${tono}`}>{valor}</p>
            {detalle && <p className="text-[11px] text-zinc-400">{detalle}</p>}
        </div>
    );
}

export default function SupervisionClases() {
    const { tenant_id: authTenant } = useAuth();
    const tenant_id = authTenant || parseInt(localStorage.getItem('tenant_id') || '1');
    const hoy = hoyChileStr();

    // ── Vista: la GRILLA es la principal (antes era inalcanzable). ──
    const [vista, setVista] = useState('grilla'); // 'grilla' | 'disciplinas'

    // ── Rango de la grilla: ESTOS controles filtran de verdad (B5). ──
    const [desde, setDesde] = useState(hoy);
    const [hasta, setHasta] = useState(hoy);
    const [disciplinaId, setDisciplinaId] = useState(''); // '' = todas
    const [avisoRango, setAvisoRango] = useState('');
    const [grilla, setGrilla] = useState(null);
    const [grillaLoading, setGrillaLoading] = useState(false);
    const [errorGrilla, setErrorGrilla] = useState('');
    const [refrescando, setRefrescando] = useState(false);
    const [ultimaActualizacion, setUltimaActualizacion] = useState(null);

    // ── Detalle de una clase de la grilla: asignar / quitar coach (B3). ──
    const [detalleClase, setDetalleClase] = useState(null);
    const [coachSelector, setCoachSelector] = useState(null); // { claseId, disciplinaId, etiqueta }
    const [coachesDisponibles, setCoachesDisponibles] = useState([]);
    const [cargandoCoaches, setCargandoCoaches] = useState(false);
    const [errorCoaches, setErrorCoaches] = useState('');
    const [asignando, setAsignando] = useState(false);
    const [msgAsignacion, setMsgAsignacion] = useState(null); // { tipo, texto }
    // Confirmación de cobertura de emergencia: guarda el 409 TAL CUAL (detail).
    const [emergenciaConfirm, setEmergenciaConfirm] = useState(null); // { coach, detalle, claseId, etiqueta }
    const [quitarConfirm, setQuitarConfirm] = useState(null); // { clase }

    // ── Clases de HOY (día completo) + ampliar cupo de una clase puntual. ──
    const [clasesHoy, setClasesHoy] = useState([]);
    const [cargandoClasesHoy, setCargandoClasesHoy] = useState(false);
    const [errorClasesHoy, setErrorClasesHoy] = useState('');
    const [filtroHoy, setFiltroHoy] = useState(''); // '' = todas las disciplinas

    // ── Cupos por disciplina. ──
    const [showCupos, setShowCupos] = useState(false);
    const [cuposData, setCuposData] = useState([]);
    const [cuposLoading, setCuposLoading] = useState(false);
    const [cuposMsg, setCuposMsg] = useState(null); // { tipo, texto }
    const [errorCupos, setErrorCupos] = useState('');

    // ── Vista "por disciplina": tarjetas + calendario semanal + reservas. ──
    const [disciplinas, setDisciplinas] = useState([]);
    const [errorDisciplinas, setErrorDisciplinas] = useState('');
    const [discExpandida, setDiscExpandida] = useState(null);
    const [horariosDisc, setHorariosDisc] = useState({}); // { [discId]: [...] }
    const [loadingHorariosDisc, setLoadingHorariosDisc] = useState(false);
    const [errorHorarios, setErrorHorarios] = useState({}); // { [discId]: texto }
    const [modalReservasHorario, setModalReservasHorario] = useState(null); // { horario, cargando, data }
    const [showModalClase, setShowModalClase] = useState(false); // modal "+ Agregar clase"

    // ═══ CARGA: grilla por rango (+ resumen de cobertura) ═══
    const cargarGrilla = useCallback(async () => {
        setGrillaLoading(true);
        setErrorGrilla('');
        try {
            const params = { desde, hasta };
            if (disciplinaId !== '') params.disciplina_id = disciplinaId;
            const r = await api.get(`${API_BASE}/supervision/grilla`, { params });
            setGrilla(r.data || null);
            setUltimaActualizacion(new Date());
        } catch (e) {
            console.error('Error grilla supervisión', e);
            setGrilla(null);
            setErrorGrilla(e.response?.data?.detail || 'No se pudo cargar la grilla de supervisión.');
        }
        setGrillaLoading(false);
    }, [desde, hasta, disciplinaId]);

    // ═══ CARGA: disciplinas (filtro de la grilla y vista "por disciplina") ═══
    const cargarDisciplinas = useCallback(async () => {
        setErrorDisciplinas('');
        try {
            const r = await api.get(`${API_BASE}/disciplinas`);
            setDisciplinas(r.data || []);
        } catch (e) {
            console.error('Error cargando disciplinas', e);
            setErrorDisciplinas('No se pudieron cargar las disciplinas.');
        }
    }, []);

    // ═══ CARGA: clases de HOY (día completo, incluidas las ya pasadas) ═══
    const cargarClasesHoy = useCallback(async () => {
        setCargandoClasesHoy(true);
        setErrorClasesHoy('');
        try {
            const params = { fecha_desde: hoy, fecha_hasta: hoy, limit: 200 };
            if (filtroHoy !== '') params.disciplina_id = filtroHoy;
            const r = await api.get(`${API_BASE}/clases/`, { params });
            const data = r.data || [];
            const lista = Array.isArray(data) ? data : (data.clases || []);
            lista.sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));
            setClasesHoy(lista);
        } catch (e) {
            console.error('Error clases de hoy', e);
            setErrorClasesHoy(e.response?.data?.detail || 'No se pudieron cargar las clases de hoy.');
            setClasesHoy([]);
        }
        setCargandoClasesHoy(false);
    }, [hoy, filtroHoy]);

    // Ampliar el cupo de UNA clase puntual (el backend valida permisos y el tope +10).
    const ampliarCupo = useCallback(async (clase, extra) => {
        const r = await api.post(`${API_BASE}/clases/${clase.id}/ampliar-cupo`, { cupos_extra: extra });
        const nuevo = r.data?.cupo_maximo;
        setClasesHoy((prev) => prev.map((c) => (c.id === clase.id ? { ...c, cupo_maximo: nuevo } : c)));
        // La grilla también muestra el cupo: se recarga en segundo plano.
        cargarGrilla();
        return r.data; // { cupo_maximo, cupo_original, tope, extra_disponible }
    }, [cargarGrilla]);

    // Refresco manual de todo lo que ve el admin.
    const refrescarTodo = useCallback(async () => {
        setRefrescando(true);
        await Promise.all([cargarGrilla(), cargarClasesHoy()]);
        setRefrescando(false);
    }, [cargarGrilla, cargarClasesHoy]);

    // ═══ Cupos por disciplina ═══
    const fetchCupos = useCallback(async () => {
        setCuposLoading(true);
        setErrorCupos('');
        try {
            const r = await api.get(`${API_BASE}/supervision/cupos-disciplinas`);
            setCuposData(r.data || []);
        } catch (e) {
            console.error('Error cupos', e);
            setErrorCupos(e.response?.data?.detail || 'No se pudieron cargar los cupos.');
        }
        setCuposLoading(false);
    }, []);

    const cupoBloqueado = (d) => !d.activo || (d.horarios_count ?? 0) === 0;

    // Un solo camino para el +/- de cupos por disciplina.
    const ajustarCupo = async (d, delta) => {
        const nuevo = Math.min(CUPO_MAX, Math.max(CUPO_MIN, d.cupo_actual + delta));
        if (nuevo === d.cupo_actual) return;
        setCuposMsg(null);
        try {
            const r = await api.patch(`${API_BASE}/supervision/cupo-disciplina`, null,
                { params: { disciplina_id: d.id, cupo_maximo: nuevo } });
            if (r.data?.ok && (r.data?.horarios_actualizados ?? 0) > 0) {
                setCuposData((prev) => prev.map((x) => (x.id === d.id ? { ...x, cupo_actual: nuevo } : x)));
                setCuposMsg({ tipo: 'exito', texto: `Cupo de ${d.nombre}: ${nuevo}. Aplica a las próximas clases generadas.` });
            } else {
                setCuposMsg({ tipo: 'error', texto: 'Esta disciplina no tiene horarios configurados: el cambio no se guardó.' });
            }
        } catch (e) {
            console.error('Error actualizando cupo', e);
            setCuposMsg({ tipo: 'error', texto: e.response?.data?.detail || 'No se pudo actualizar el cupo. Reintenta.' });
        }
    };

    // ═══ Vista "por disciplina": calendario semanal (plantillas `horarios`) ═══
    const cargarHorariosDisc = useCallback(async (discId) => {
        if (!discId) return;
        setLoadingHorariosDisc(true);
        setErrorHorarios((prev) => ({ ...prev, [discId]: '' }));
        try {
            const r = await api.get(`${API_BASE}/supervision/horarios-base`, {
                params: { disciplina_id: discId },
            });
            setHorariosDisc((prev) => ({ ...prev, [discId]: r.data?.horarios || [] }));
        } catch (e) {
            console.error('Error horarios de disciplina', e);
            setErrorHorarios((prev) => ({ ...prev, [discId]: e.response?.data?.detail || 'No se pudieron cargar los horarios de esta disciplina.' }));
        }
        setLoadingHorariosDisc(false);
    }, []);

    // ── Modal de reservas (solo self-service: Open Box / Musculación) ──
    const abrirModalReservas = async (horario) => {
        setModalReservasHorario({ horario, cargando: true, data: null });
        try {
            const r = await api.get(`${API_BASE}/supervision/proxima-clase-reservas`, {
                params: { horario_base_id: horario.id },
            });
            setModalReservasHorario({ horario, cargando: false, data: r.data || {} });
        } catch (e) {
            setModalReservasHorario({ horario, cargando: false, data: null, error: e.response?.data?.detail || 'No se pudieron cargar las reservas.' });
        }
    };

    // ── Asignación de coach (B3): selector + 409 de emergencia VISIBLE ──
    // `objetivo` = { claseId, disciplinaId, etiqueta } — sirve igual para una clase
    // de la grilla y para una plantilla del calendario semanal.
    const abrirSelectorCoach = async (objetivo) => {
        setMsgAsignacion(null);
        setErrorCoaches('');
        setCoachesDisponibles([]);
        setCoachSelector(objetivo);
        setCargandoCoaches(true);
        try {
            // TODOS los coaches del box, marcando si pertenecen a la disciplina.
            const r = await api.get(`${API_BASE}/supervision/coaches-todos`, {
                params: { disciplina_id: objetivo.disciplinaId },
            });
            setCoachesDisponibles(r.data || []);
        } catch (e) {
            console.error('Error coaches disponibles', e);
            setErrorCoaches(e.response?.data?.detail || 'No se pudieron cargar los coaches disponibles.');
        }
        setCargandoCoaches(false);
    };

    // Asignar un coach a UNA clase (POST /supervision/clases/{id}/asignar).
    // `forzar=false` primero: si el coach NO dicta la disciplina el backend responde
    // 409 y ese `detail` se muestra tal cual en la confirmación de emergencia.
    const asignarCoach = async (coach, forzar = false) => {
        if (!coachSelector) return;
        const objetivo = coachSelector;
        setAsignando(true);
        setMsgAsignacion(null);
        try {
            const r = await api.post(`${API_BASE}/supervision/clases/${objetivo.claseId}/asignar`, {
                coach_id: coach.id,
                forzar_emergencia: forzar,
            });
            setCoachSelector(null);
            setDetalleClase(null);
            setMsgAsignacion({
                tipo: 'exito',
                texto: `✅ ${coach.nombre} quedó a cargo de ${objetivo.etiqueta} (${marca(r.data?.marca).etiqueta}). Avisado en su campana.`,
            });
            cargarGrilla();
        } catch (e) {
            const detalle = e.response?.data?.detail || 'No se pudo asignar el coach.';
            if (e.response?.status === 409 && !coach.pertenece) {
                setEmergenciaConfirm({ coach, detalle, claseId: objetivo.claseId, etiqueta: objetivo.etiqueta });
                setCoachSelector(null);
            } else {
                setMsgAsignacion({ tipo: 'error', texto: detalle });
                setCoachSelector(null);
            }
        }
        setAsignando(false);
    };

    const confirmarEmergencia = async () => {
        if (!emergenciaConfirm) return;
        const { coach, claseId, etiqueta } = emergenciaConfirm;
        setAsignando(true);
        try {
            const r = await api.post(`${API_BASE}/supervision/clases/${claseId}/asignar`, {
                coach_id: coach.id,
                forzar_emergencia: true,
            });
            setEmergenciaConfirm(null);
            setDetalleClase(null);
            setMsgAsignacion({
                tipo: 'exito',
                texto: `⚠️ Cobertura de emergencia registrada: ${coach.nombre} queda a cargo de ${etiqueta} (${marca(r.data?.marca).etiqueta}). Se avisó al coach y a los admins.`,
            });
            cargarGrilla();
        } catch (e) {
            setMsgAsignacion({ tipo: 'error', texto: e.response?.data?.detail || 'No se pudo registrar la cobertura de emergencia.' });
            setEmergenciaConfirm(null);
        }
        setAsignando(false);
    };

    // Quitar el coach de UNA clase (DELETE) y avisar al coach que la tenía.
    const quitarCoach = async () => {
        if (!quitarConfirm) return;
        const { clase } = quitarConfirm;
        const claseId = clase.clase_id ?? clase.id;
        setAsignando(true);
        try {
            const r = await api.delete(`${API_BASE}/supervision/clases/${claseId}/asignar`);
            setQuitarConfirm(null);
            setDetalleClase(null);
            setMsgAsignacion({
                tipo: 'exito',
                texto: `🔴 La clase quedó sin coach.${r.data?.notificado ? ' El coach fue avisado en su campana.' : ''}`,
            });
            cargarGrilla();
        } catch (e) {
            setQuitarConfirm(null);
            setMsgAsignacion({ tipo: 'error', texto: e.response?.data?.detail || 'No se pudo quitar el coach.' });
        }
        setAsignando(false);
    };

    // ═══ EFECTOS ═══
    // Al abrir: disciplinas (filtro) + grilla del rango + clases de hoy.
    useEffect(() => { cargarDisciplinas(); }, [cargarDisciplinas]);
    // `cargarGrilla` cambia de identidad cuando cambian desde / hasta / disciplinaId:
    // el rango SÍ vuelve a consultar (antes las fechas no filtraban nada visible).
    useEffect(() => { cargarGrilla(); }, [cargarGrilla]);
    useEffect(() => { cargarClasesHoy(); }, [cargarClasesHoy]);

    // Polling: la grilla cambia cuando un coach toma o suelta. Se pausa con un modal abierto.
    useEffect(() => {
        if (coachSelector || quitarConfirm || emergenciaConfirm || detalleClase) return;
        const t = setInterval(() => { cargarGrilla(); }, POLLING_INTERVALO_MS);
        return () => clearInterval(t);
    }, [cargarGrilla, coachSelector, quitarConfirm, emergenciaConfirm, detalleClase]);

    // ═══ Rango ═══
    // Normaliza SIEMPRE a un rango válido (hasta >= desde y <= MAX_DIAS_RANGO): fuera de
    // eso el backend responde 400 y no tiene sentido pintar la pantalla de error.
    const aplicarRango = (nuevoDesde, nuevoHasta) => {
        const ini = nuevoDesde || desde;
        let fin = nuevoHasta || ini;
        if (fin < ini) fin = ini;
        if (diasDelRango(ini, fin) > MAX_DIAS_RANGO) {
            fin = sumarDias(ini, MAX_DIAS_RANGO - 1);
            setAvisoRango(`El rango máximo es de ${MAX_DIAS_RANGO} días: "hasta" quedó en ${fmtFechaCortaChile(fin)}.`);
        } else {
            setAvisoRango('');
        }
        setDesde(ini);
        setHasta(fin);
    };

    // ◀ / ▶ mueven el rango completo (no una semana fija) por su propio largo.
    const moverRango = (dir) => {
        const largo = Math.max(1, diasDelRango(desde, hasta));
        aplicarRango(sumarDias(desde, dir * largo), sumarDias(hasta, dir * largo));
    };

    // ═══ Derivados de la grilla ═══
    const dias = grilla?.dias || [];
    const resumen = grilla?.resumen;

    // Filas = franjas horarias del rango, tomando tanto las clases reales como las
    // plantillas (así una franja que sólo tiene plantilla igual aparece).
    const filas = useMemo(() => {
        if (!grilla) return [];
        const mapa = new Map();
        const agregar = (h1, h2) => {
            if (!h1 || !h2) return;
            const k = `${h1}|${h2}`;
            if (!mapa.has(k)) mapa.set(k, { hora_inicio: h1, hora_fin: h2, clave: k });
        };
        (grilla.plantillas || []).forEach((p) => agregar(p.hora_inicio, p.hora_fin));
        (grilla.celdas || []).forEach((c) => agregar(c.hora_inicio, c.hora_fin));
        return [...mapa.values()].sort((a, b) => a.hora_inicio.localeCompare(b.hora_inicio));
    }, [grilla]);

    const celdaDe = (dia, fila) => (grilla?.celdas || []).find(
        (c) => c.fecha === dia.fecha && c.hora_inicio === fila.hora_inicio && c.hora_fin === fila.hora_fin);

    const plantillaDe = (dia, fila) => (grilla?.plantillas || []).find(
        (p) => p.dia_semana === dia.dia_semana && p.hora_inicio === fila.hora_inicio && p.hora_fin === fila.hora_fin);

    // ═══ Derivados de la vista "por disciplina" ═══
    const resumenDisciplina = (discId) => {
        const hs = horariosDisc[discId] || [];
        return { total: hs.length, sinCoach: hs.filter((h) => !h.coach_nombre).length };
    };
    const discConCoach = (discId) => disciplinas.find((d) => d.id === discId)?.requiere_coach ?? true;

    return (
        <Layout>
            <div className="p-6 max-w-[1700px] mx-auto">
                {/* ── Encabezado y acciones ── */}
                <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                    <div>
                        <h1 className="text-2xl font-bold text-zinc-100">Supervisión de Clases</h1>
                        <p className="text-sm text-zinc-400">
                            Cobertura de coach por rango de fechas (lunes a sábado) y el día de hoy completo.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <div className="flex rounded-lg overflow-hidden border border-zinc-700">
                            <button
                                onClick={() => setVista('grilla')}
                                className={`px-3 py-1.5 text-sm font-medium ${vista === 'grilla' ? 'bg-blue-600 text-white' : 'bg-zinc-900 text-zinc-300 hover:bg-zinc-800'}`}
                            >
                                🗓 Grilla por rango
                            </button>
                            <button
                                onClick={() => setVista('disciplinas')}
                                className={`px-3 py-1.5 text-sm font-medium border-l border-zinc-700 ${vista === 'disciplinas' ? 'bg-blue-600 text-white' : 'bg-zinc-900 text-zinc-300 hover:bg-zinc-800'}`}
                            >
                                📋 Por disciplina
                            </button>
                        </div>
                        <button
                            onClick={() => setShowModalClase(true)}
                            className="px-3 py-1.5 bg-orange-500 text-white rounded text-sm font-semibold hover:bg-orange-600"
                        >
                            ＋ Agregar clase
                        </button>
                        {/* Contraste: el botón se lee en los DOS estados sobre el fondo oscuro
                            (antes el estado inactivo era purple-100 sobre zinc-950, casi invisible). */}
                        <button
                            onClick={() => { setShowCupos(!showCupos); if (!showCupos) fetchCupos(); }}
                            aria-pressed={showCupos}
                            className={`px-3 py-1.5 rounded text-sm font-semibold border transition-colors ${showCupos
                                ? 'bg-purple-600 border-purple-300 text-white'
                                : 'bg-zinc-900 border-purple-400 text-purple-200 hover:bg-purple-500/20'}`}
                        >
                            📊 Gestión de Cupos
                        </button>
                    </div>
                </div>

                {/* ── Avisos globales ── */}
                {errorDisciplinas && (
                    <div className="border-l-4 rounded-lg p-3 mb-3 text-xs bg-amber-500/10 border-amber-500 text-amber-300 flex items-center justify-between gap-3">
                        <span>{errorDisciplinas}</span>
                        <button onClick={cargarDisciplinas} className="px-2 py-1 bg-amber-600 text-white rounded text-xs font-medium hover:bg-amber-700">Reintentar</button>
                    </div>
                )}
                {msgAsignacion && (
                    <div className={`border-l-4 rounded-lg p-3 mb-3 text-sm flex items-start justify-between gap-3 ${msgAsignacion.tipo === 'exito'
                        ? 'bg-emerald-500/10 border-emerald-500 text-emerald-300'
                        : 'bg-red-500/10 border-red-500 text-red-300'}`}>
                        <span>{msgAsignacion.texto}</span>
                        <button onClick={() => setMsgAsignacion(null)} aria-label="Cerrar aviso" className="text-lg leading-none opacity-70 hover:opacity-100">&times;</button>
                    </div>
                )}
                {vista === 'grilla' && errorGrilla && (
                    <div className="border-l-4 rounded-lg p-3 mb-3 text-xs bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-3">
                        <span>{errorGrilla}</span>
                        <button onClick={cargarGrilla} className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                    </div>
                )}
                {vista === 'grilla' && avisoRango && (
                    <div className="border-l-4 rounded-lg p-3 mb-3 text-xs bg-amber-500/10 border-amber-500 text-amber-300">{avisoRango}</div>
                )}

                {/* ══ VISTA 1: GRILLA POR RANGO ══ */}
                {vista === 'grilla' && (
                    <>
                        {/* Controles del rango (estos SÍ filtran: bug "las fechas no filtran") */}
                        <div className="bg-zinc-900 rounded-xl border border-zinc-800 p-4 mb-4">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-sm font-semibold text-zinc-300">Rango:</span>
                                <input
                                    type="date"
                                    value={desde}
                                    onChange={(e) => aplicarRango(e.target.value, hasta)}
                                    aria-label="Desde"
                                    className="border border-zinc-700 bg-zinc-800 rounded px-2 py-1 text-sm text-zinc-100"
                                />
                                <span className="text-zinc-500">→</span>
                                <input
                                    type="date"
                                    value={hasta}
                                    onChange={(e) => aplicarRango(desde, e.target.value)}
                                    aria-label="Hasta"
                                    className="border border-zinc-700 bg-zinc-800 rounded px-2 py-1 text-sm text-zinc-100"
                                />
                                <button onClick={() => moverRango(-1)} title="Rango anterior" className="px-2 py-1 rounded bg-zinc-800 text-zinc-200 hover:bg-zinc-700">◀</button>
                                <button onClick={() => moverRango(1)} title="Rango siguiente" className="px-2 py-1 rounded bg-zinc-800 text-zinc-200 hover:bg-zinc-700">▶</button>
                                <button
                                    onClick={() => aplicarRango(hoy, hoy)}
                                    className={`px-3 py-1 rounded text-sm font-medium ${desde === hoy && hasta === hoy ? 'bg-emerald-600 text-white' : 'bg-zinc-800 text-zinc-200 hover:bg-zinc-700'}`}
                                >
                                    Hoy
                                </button>
                                <button onClick={() => aplicarRango(lunesDe(hoy), sumarDias(lunesDe(hoy), 5))} className="px-3 py-1 rounded text-sm font-medium bg-zinc-800 text-zinc-200 hover:bg-zinc-700">
                                    Esta semana
                                </button>
                                <button onClick={() => aplicarRango(hoy, sumarDias(hoy, 6))} className="px-3 py-1 rounded text-sm font-medium bg-zinc-800 text-zinc-200 hover:bg-zinc-700">
                                    Próximos 7 días
                                </button>
                                <button onClick={() => aplicarRango(hoy, sumarDias(hoy, 27))} className="px-3 py-1 rounded text-sm font-medium bg-zinc-800 text-zinc-200 hover:bg-zinc-700">
                                    Próximas 4 semanas
                                </button>
                                <select
                                    value={disciplinaId}
                                    onChange={(e) => setDisciplinaId(e.target.value)}
                                    aria-label="Filtrar por disciplina"
                                    className="border border-zinc-700 bg-zinc-800 rounded px-2 py-1 text-sm text-zinc-100"
                                >
                                    <option value="">Todas las disciplinas</option>
                                    {disciplinas.map((d) => (
                                        <option key={d.id} value={d.id}>{d.nombre}</option>
                                    ))}
                                </select>
                                <button
                                    onClick={refrescarTodo}
                                    disabled={refrescando}
                                    className="ml-auto px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                                >
                                    {refrescando ? 'Refrescando…' : '🔄 Refrescar'}
                                </button>
                            </div>
                            <p className="text-xs text-zinc-500 mt-2">
                                {diasDelRango(desde, hasta)} día(s) · máximo {MAX_DIAS_RANGO} · se refresca solo cada {Math.round(POLLING_INTERVALO_MS / 1000)}s
                                {ultimaActualizacion && ` · última: ${ultimaActualizacion.toLocaleTimeString('es-CL')}`}
                            </p>
                        </div>

                        {/* Leyenda de las CUATRO marcas */}
                        <div className="flex flex-wrap items-center gap-2 mb-3 text-xs text-zinc-400">
                            <span className="font-semibold text-zinc-300">Marca de cobertura:</span>
                            {Object.entries(MARCAS).map(([clave, m]) => (
                                <span key={clave} className={`px-2 py-0.5 rounded border ${m.chip}`}>{m.icono} {m.etiqueta}</span>
                            ))}
                            <span className="text-zinc-500">· La caja punteada es una plantilla del horario que todavía no tiene clase generada.</span>
                        </div>

                        {/* Resumen de cobertura del rango */}
                        {resumen && (
                            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3 mb-4">
                                <Tarjeta label="Clases del rango" valor={resumen.total_clases} detalle={`${diasDelRango(desde, hasta)} día(s)`} />
                                <Tarjeta
                                    label="Cobertura"
                                    valor={`${resumen.cobertura_pct}%`}
                                    detalle="clases con coach"
                                    tono={resumen.cobertura_pct >= 90 ? 'text-emerald-400' : resumen.cobertura_pct >= 70 ? 'text-amber-400' : 'text-red-400'}
                                />
                                <Tarjeta label="Con coach" valor={resumen.con_coach} tono="text-emerald-400" />
                                <Tarjeta label="Sin coach" valor={resumen.sin_coach} tono={resumen.sin_coach > 0 ? 'text-red-400' : 'text-zinc-100'} />
                                <Tarjeta label="✅ Tomadas por coach" valor={resumen.tomadas_por_coach} tono="text-emerald-300" />
                                <Tarjeta label="🟦 Asignadas por admin" valor={resumen.asignadas_por_admin} tono="text-sky-300" />
                                <Tarjeta
                                    label="⚠️ Emergencia"
                                    valor={resumen.cobertura_emergencia}
                                    detalle={`Plantillas sin coach: ${resumen.plantillas_sin_coach}/${resumen.plantillas_activas}`}
                                    tono={resumen.cobertura_emergencia > 0 ? 'text-amber-300' : 'text-zinc-100'}
                                />
                            </div>
                        )}

                        {/* Cobertura por disciplina */}
                        {resumen?.por_disciplina?.length > 0 && (
                            <div className="bg-zinc-900 rounded-xl border border-zinc-800 p-4 mb-4">
                                <h3 className="font-bold text-zinc-100 mb-3">Cobertura por disciplina</h3>
                                <div className="space-y-2">
                                    {resumen.por_disciplina.map((d) => (
                                        <div key={d.disciplina_id} className="flex items-center gap-3 text-sm">
                                            <span className="w-44 shrink-0 truncate text-zinc-200">{d.nombre}</span>
                                            <div className="flex-1 h-2 rounded bg-zinc-800 overflow-hidden">
                                                <div
                                                    className={`h-full ${d.cobertura_pct >= 90 ? 'bg-emerald-500' : d.cobertura_pct >= 70 ? 'bg-amber-500' : 'bg-red-500'}`}
                                                    style={{ width: `${d.cobertura_pct}%` }}
                                                />
                                            </div>
                                            <span className="w-48 shrink-0 text-right text-xs text-zinc-400">
                                                {d.cobertura_pct}% · {d.con_coach}/{d.total} con coach{d.sin_coach > 0 ? ` · ${d.sin_coach} sin coach` : ''}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* LA GRILLA: columnas = días del rango, filas = franjas horarias */}
                        <div className="bg-zinc-900 rounded-xl border border-zinc-800 overflow-hidden">
                            <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-800/50 flex flex-wrap items-center justify-between gap-2">
                                <h2 className="font-bold text-zinc-100">
                                    Grilla {fmtFechaCortaChile(desde)} → {fmtFechaCortaChile(hasta)}
                                </h2>
                                <p className="text-xs text-zinc-400">
                                    {grillaLoading
                                        ? 'Cargando…'
                                        : `${dias.length} día(s) · ${filas.length} franja(s) · click en una clase para asignar o quitar coach`}
                                </p>
                            </div>
                            {!grilla ? (
                                <div className="flex justify-center py-12">
                                    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500"></div>
                                </div>
                            ) : dias.length === 0 ? (
                                <p className="text-zinc-500 text-sm py-10 text-center">
                                    El rango no tiene días hábiles (la grilla es lunes a sábado).
                                </p>
                            ) : filas.length === 0 ? (
                                <p className="text-zinc-500 text-sm py-10 text-center">
                                    No hay franjas horarias en el rango: revisa los horarios de las disciplinas.
                                </p>
                            ) : (
                                <div className="overflow-x-auto">
                                    <table className="w-full border-collapse text-sm">
                                        <thead>
                                            <tr>
                                                <th className="sticky left-0 z-10 w-24 bg-zinc-800/90 px-3 py-2 text-left text-xs font-semibold text-zinc-300 border-b border-r border-zinc-800">
                                                    Hora
                                                </th>
                                                {dias.map((d) => (
                                                    <th
                                                        key={d.fecha}
                                                        className={`min-w-[170px] px-2 py-2 text-left text-xs font-semibold border-b border-zinc-800 ${d.es_hoy
                                                            ? 'bg-emerald-500/10 text-emerald-300'
                                                            : d.es_pasado ? 'bg-zinc-800/40 text-zinc-500' : 'bg-zinc-800/60 text-zinc-300'}`}
                                                    >
                                                        {d.nombre_dia} {fmtFechaCortaChile(d.fecha)}
                                                        {d.es_hoy && <span className="ml-1 font-bold">· hoy</span>}
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>

                                        <tbody>
                                            {filas.map((fila) => (
                                                <tr key={fila.clave}>
                                                    <th className="sticky left-0 z-10 bg-zinc-900 px-3 py-2 text-left align-top text-xs font-bold text-zinc-300 border-b border-r border-zinc-800">
                                                        {fila.hora_inicio}<br />{fmtHora(fila.hora_fin)}
                                                    </th>
                                                    {dias.map((dia) => {
                                                        const celda = celdaDe(dia, fila);
                                                        const plantilla = plantillaDe(dia, fila);
                                                        return (
                                                            <td
                                                                key={dia.fecha}
                                                                className={`align-top px-2 py-2 border-b border-zinc-800 ${dia.es_pasado ? 'opacity-60' : ''}`}
                                                            >
                                                                {celda ? (
                                                                    celda.clases.map((c) => (
                                                                        <ChipClase
                                                                            key={`${c.clase_id}-${c.disciplina_id}`}
                                                                            clase={c}
                                                                            onAbrir={(x) => { setMsgAsignacion(null); setDetalleClase(x); }}
                                                                        />
                                                                    ))
                                                                ) : plantilla ? (
                                                                    <PlantillaFantasma plantilla={plantilla} />
                                                                ) : (
                                                                    <span className="text-zinc-700">—</span>
                                                                )}
                                                            </td>
                                                        );
                                                    })}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    </>
                )}

                {/* ══ CLASES DE HOY (día completo) — acá vive "Ampliar cupo" ══ */}
                <div className="bg-zinc-900 rounded-xl border border-zinc-800 mt-4">
                    <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-800/50 flex flex-wrap items-center justify-between gap-2">
                        <div>
                            <h2 className="font-bold text-zinc-100">Clases de hoy ({fmtFechaCortaChile(hoy)})</h2>
                            <p className="text-xs text-zinc-400 mt-0.5">
                                Día completo, todas las disciplinas. Cada fila amplía el cupo de ESA clase puntual (hasta +10 sobre su cupo original).
                            </p>
                        </div>
                        <div className="flex items-center gap-2">
                            <select
                                value={filtroHoy}
                                onChange={(e) => setFiltroHoy(e.target.value)}
                                aria-label="Disciplina de las clases de hoy"
                                className="border border-zinc-700 bg-zinc-800 rounded px-2 py-1 text-sm text-zinc-100"
                            >
                                <option value="">Todas las disciplinas</option>
                                {disciplinas.map((d) => (
                                    <option key={d.id} value={d.id}>{d.nombre}</option>
                                ))}
                            </select>
                            <button
                                onClick={cargarClasesHoy}
                                disabled={cargandoClasesHoy}
                                title="Recargar las clases de hoy"
                                className="px-2.5 py-1 rounded bg-zinc-800 text-zinc-200 hover:bg-zinc-700 text-sm disabled:opacity-50"
                            >
                                🔄
                            </button>
                        </div>
                    </div>
                    <div className="p-4">
                        {errorClasesHoy && (
                            <div className="border-l-4 rounded-lg p-3 mb-3 text-xs bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-3">
                                <span>{errorClasesHoy}</span>
                                <button onClick={cargarClasesHoy} className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                            </div>
                        )}
                        {cargandoClasesHoy ? (
                            <div className="flex justify-center py-8">
                                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                            </div>
                        ) : clasesHoy.length === 0 ? (
                            <p className="text-zinc-500 text-sm text-center py-6">Sin clases generadas para hoy.</p>
                        ) : (
                            clasesHoy.map((c) => (
                                <SupervisionClaseRow key={c.id} clase={c} onAmpliarCupo={ampliarCupo} />
                            ))
                        )}
                    </div>
                </div>

                {/* ══ CUPO MÁXIMO POR DISCIPLINA (afecta las próximas clases generadas) ══ */}
                {showCupos && (
                    <div className="bg-zinc-900 rounded-xl border border-purple-500/40 p-4 mt-4">
                        <h3 className="font-bold text-lg text-zinc-100 mb-1">📊 Cupo máximo por disciplina</h3>
                        <p className="text-xs text-zinc-400 mb-3">
                            Cambia el cupo de los horarios de la disciplina: aplica a las clases que se generen de ahora en adelante
                            (las ya creadas se amplían desde «Clases de hoy»).
                        </p>
                        {cuposMsg && (
                            <div className={`mb-3 px-3 py-2 rounded text-xs border-l-4 ${cuposMsg.tipo === 'error'
                                ? 'bg-red-500/10 border-red-500 text-red-300'
                                : 'bg-emerald-500/10 border-emerald-500 text-emerald-300'}`}>
                                {cuposMsg.texto}
                            </div>
                        )}
                        {errorCupos && (
                            <div className="border-l-4 rounded-lg p-3 mb-3 text-xs bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-3">
                                <span>{errorCupos}</span>
                                <button onClick={fetchCupos} className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                            </div>
                        )}
                        {cuposLoading ? (
                            <div className="text-zinc-500 text-center py-8">Cargando cupos…</div>
                        ) : cuposData.length === 0 ? (
                            <div className="text-zinc-500 text-center py-8">Sin datos de cupos</div>
                        ) : (
                            <div className="divide-y divide-zinc-800">
                                {cuposData.map((d) => (
                                    <div key={d.id} className="flex items-center justify-between py-3">
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium text-zinc-100">{d.nombre}</span>
                                            {!d.activo && <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400">Inactiva</span>}
                                            {cupoBloqueado(d) && (
                                                <span className="text-xs text-amber-400">
                                                    {!d.activo ? '· sin cambios posibles' : '· sin horarios configurados'}
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <button
                                                onClick={() => ajustarCupo(d, -1)}
                                                disabled={d.cupo_actual <= CUPO_MIN || cupoBloqueado(d)}
                                                title={cupoBloqueado(d) ? (!d.activo ? 'Disciplina inactiva' : 'Sin horarios configurados') : 'Bajar el cupo máximo'}
                                                aria-label={`Bajar el cupo de ${d.nombre}`}
                                                className={`w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold ${(d.cupo_actual <= CUPO_MIN || cupoBloqueado(d))
                                                    ? 'bg-zinc-800 text-zinc-600 cursor-not-allowed'
                                                    : 'bg-red-500/20 text-red-300 hover:bg-red-500/30'}`}
                                            >
                                                −
                                            </button>
                                            <span className="w-12 text-center text-xl font-bold text-zinc-100">{d.cupo_actual}</span>
                                            <button
                                                onClick={() => ajustarCupo(d, 1)}
                                                disabled={d.cupo_actual >= CUPO_MAX || cupoBloqueado(d)}
                                                title={cupoBloqueado(d) ? (!d.activo ? 'Disciplina inactiva' : 'Sin horarios configurados') : 'Subir el cupo máximo'}
                                                aria-label={`Subir el cupo de ${d.nombre}`}
                                                className={`w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold ${(d.cupo_actual >= CUPO_MAX || cupoBloqueado(d))
                                                    ? 'bg-zinc-800 text-zinc-600 cursor-not-allowed'
                                                    : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'}`}
                                            >
                                                +
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* ══ VISTA 2: POR DISCIPLINA (plantillas semanales + reservas) ══ */}
                {vista === 'disciplinas' && (
                    <>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-2">
                            {disciplinas.length === 0 ? (
                                <p className="text-zinc-500 text-sm">Sin disciplinas cargadas.</p>
                            ) : disciplinas.map((d) => {
                                const r = resumenDisciplina(d.id);
                                const requiereCoach = d.requiere_coach ?? true;
                                const abrir = () => {
                                    if (discExpandida === d.id) { setDiscExpandida(null); return; }
                                    setDiscExpandida(d.id);
                                    cargarHorariosDisc(d.id);
                                };
                                return (
                                    <div
                                        key={d.id}
                                        role="button"
                                        tabIndex={0}
                                        onClick={abrir}
                                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrir(); } }}
                                        className={`rounded-xl border-2 p-4 cursor-pointer transition-all hover:shadow-lg ${discExpandida === d.id ? 'border-blue-500 bg-zinc-800/50 shadow-md' : 'border-zinc-800 bg-zinc-900'}`}
                                    >
                                        <div className="flex items-center justify-between mb-2">
                                            <h3 className="font-bold text-lg text-zinc-100">
                                                {d.nombre}
                                                {!d.activo && <span className="ml-2 text-xs px-2 py-0.5 rounded bg-zinc-700 text-zinc-400">⚠️ Inactiva</span>}
                                                {r.total === 0 && <span className="ml-2 text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold">⏰ Sin horarios</span>}
                                            </h3>
                                            <span className="text-xs text-zinc-500">{discExpandida === d.id ? '▲' : '▼'}</span>
                                        </div>
                                        <div className="space-y-1 text-sm text-zinc-400">
                                            {r.total === 0 ? (
                                                errorHorarios[d.id]
                                                    ? <div className="text-red-400 text-xs">{errorHorarios[d.id]}</div>
                                                    : <div className="text-zinc-500 text-xs">Sin horarios base asignados</div>
                                            ) : (
                                                <>
                                                    <div>📅 {r.total} horario(s) semanal(es)</div>
                                                    {requiereCoach && r.sinCoach > 0 && (
                                                        <div className="text-red-400 font-bold">⚠️ {r.sinCoach} sin coach</div>
                                                    )}
                                                    {!requiereCoach && <div className="text-zinc-500 text-xs">🏠 Self-service (sin coach)</div>}
                                                </>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>

                        {discExpandida && (
                            <div className="bg-zinc-900 rounded-xl border border-zinc-800 mt-2">
                                <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-800/50 flex flex-wrap items-center justify-between gap-2">
                                    <div>
                                        <h2 className="font-bold text-zinc-100">
                                            📅 {disciplinas.find((x) => x.id === discExpandida)?.nombre || ''} — Calendario semanal (Lun a Dom)
                                        </h2>
                                        <p className="text-xs text-zinc-400 mt-0.5">
                                            Plantillas fijas que se repiten cada semana. El coach mostrado es el de la última clase generada de ese horario.
                                        </p>
                                    </div>
                                    <button onClick={() => cargarHorariosDisc(discExpandida)} title="Recargar horarios" className="px-2.5 py-1 rounded bg-zinc-800 text-zinc-200 hover:bg-zinc-700 text-sm">🔄</button>
                                </div>
                                {errorHorarios[discExpandida] && (
                                    <div className="border-l-4 rounded-lg p-3 m-4 text-xs bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-3">
                                        <span>{errorHorarios[discExpandida]}</span>
                                        <button onClick={() => cargarHorariosDisc(discExpandida)} className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                                    </div>
                                )}
                                {loadingHorariosDisc ? (
                                    <div className="flex items-center justify-center py-12">
                                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500"></div>
                                    </div>
                                ) : (
                                    <div className="overflow-x-auto p-4">
                                        {!horariosDisc[discExpandida] || horariosDisc[discExpandida].length === 0 ? (
                                            <p className="text-center text-zinc-500 py-8">Esta disciplina no tiene horarios base asignados</p>
                                        ) : (
                                            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 min-w-[900px]">
                                                {DIAS.map((nombreDia, ds) => {
                                                    const horariosDia = (horariosDisc[discExpandida] || []).filter((h) => h.dia_semana === ds);
                                                    const esSelfService = !discConCoach(discExpandida);
                                                    return (
                                                        <div key={ds} className="bg-zinc-800/40 rounded-lg border border-zinc-800 p-3">
                                                            <p className={`text-xs font-bold mb-2 ${ds === 6 ? 'text-red-400' : 'text-zinc-400'}`}>{nombreDia}</p>
                                                            {horariosDia.length === 0 ? (
                                                                <p className="text-xs text-zinc-600">—</p>
                                                            ) : horariosDia.map((h) => (
                                                                <div
                                                                    key={h.id}
                                                                    onClick={esSelfService ? () => abrirModalReservas(h) : undefined}
                                                                    className={`mb-2 p-2 rounded border ${esSelfService
                                                                        ? 'bg-zinc-800/70 border-blue-500/40 cursor-pointer hover:bg-blue-900/30 transition-colors'
                                                                        : 'bg-zinc-900/80 border-zinc-700/60'}`}
                                                                >
                                                                    <p className="text-sm font-bold text-zinc-200">{h.hora_inicio}-{h.hora_fin}</p>

                                                                    {esSelfService ? (
                                                                        <p className="text-xs mt-0.5 text-blue-300 font-medium">📋 Ver reservas</p>
                                                                    ) : (
                                                                        <>
                                                                            <p className={`text-xs mt-0.5 ${h.coach_nombre ? 'text-emerald-400 font-medium' : 'text-red-400 font-bold'}`}>
                                                                                {h.coach_nombre ? `👤 ${h.coach_nombre}` : '⚠️ Sin coach'}
                                                                            </p>
                                                                            {!h.coach_nombre && h.clase_reciente_id && (
                                                                                <button
                                                                                    onClick={(e) => {
                                                                                        e.stopPropagation();
                                                                                        abrirSelectorCoach({
                                                                                            claseId: h.clase_reciente_id,
                                                                                            disciplinaId: discExpandida,
                                                                                            coachIdActual: h.coach_id ?? null,
                                                                                            etiqueta: `${nombreDia} ${h.hora_inicio}-${h.hora_fin}`,
                                                                                        });
                                                                                    }}
                                                                                    className="mt-1.5 w-full px-2 py-1 bg-blue-600 text-white rounded text-xs font-bold hover:bg-blue-700"
                                                                                >
                                                                                    👤 Asignar coach
                                                                                </button>
                                                                            )}
                                                                            {!h.coach_nombre && !h.clase_reciente_id && (
                                                                                <p className="mt-1 text-[11px] text-zinc-500">Sin clase generada: todavía no se puede asignar coach.</p>
                                                                            )}
                                                                        </>
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}

                {/* ══ MODAL: detalle de una clase de la grilla (asignar / quitar coach) ══ */}
                {detalleClase && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setDetalleClase(null)}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-5 max-w-lg w-full mx-4 border border-zinc-800" onClick={(e) => e.stopPropagation()}>
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <h3 className="font-bold text-lg text-zinc-100">
                                        {detalleClase.disciplina_nombre} · {detalleClase.hora_inicio}-{detalleClase.hora_fin}
                                    </h3>
                                    <p className="text-sm text-zinc-400">
                                        {DIAS[detalleClase.dia_semana]} {fmtFechaCortaChile(detalleClase.fecha)}
                                        {detalleClase.fecha === hoy ? ' · hoy' : ''}
                                    </p>
                                </div>
                                <button onClick={() => setDetalleClase(null)} aria-label="Cerrar" className="text-zinc-500 hover:text-zinc-300 text-xl leading-none">&times;</button>
                            </div>

                            {/* Los errores de la asignación (409 del backend) se ven acá también:
                                el aviso global queda detrás del overlay de este modal. */}
                            {msgAsignacion && (
                                <p className={`mt-3 px-2.5 py-1.5 rounded text-xs border-l-4 ${msgAsignacion.tipo === 'exito'
                                    ? 'bg-emerald-500/10 border-emerald-500 text-emerald-300'
                                    : 'bg-red-500/10 border-red-500 text-red-300'}`}>
                                    {msgAsignacion.texto}
                                </p>
                            )}

                            <div className="mt-3 space-y-1 text-sm">
                                <p>
                                    <span className={`inline-block px-2 py-0.5 rounded border text-xs ${marca(detalleClase.marca).chip}`}>
                                        {marca(detalleClase.marca).icono} {marca(detalleClase.marca).etiqueta}
                                    </span>
                                </p>
                                <p className="text-zinc-300">👤 Coach: <span className="font-medium">{detalleClase.coach_nombre || 'Sin coach'}</span></p>
                                <p className="text-zinc-300">🎟️ Cupos: {detalleClase.asistentes_confirmados || 0}/{detalleClase.cupo_maximo ?? '?'}</p>
                                <p className="text-zinc-300">📝 WOD: {detalleClase.wod_titulo || (detalleClase.wod_id ? `WOD #${detalleClase.wod_id}` : 'Sin WOD publicado')}</p>
                                <p className="text-zinc-300">🔁 Horario: {detalleClase.horario_base_id ? 'viene de un horario fijo (recurrente)' : 'clase puntual'}</p>
                                {detalleClase.cobertura_emergencia && (
                                    <p className="text-xs text-amber-300">⚠️ Tiene una cobertura de emergencia registrada.</p>
                                )}
                            </div>

                            {(detalleClase.cancelada || detalleClase.fecha < hoy) && (
                                <p className="mt-3 text-xs text-amber-300 bg-amber-500/10 border-l-4 border-amber-500 rounded p-2">
                                    {detalleClase.cancelada
                                        ? 'La clase está cancelada: el backend rechaza (409) asignarle o quitarle coach.'
                                        : 'La clase ya pasó: el backend rechaza (409) asignarle o quitarle coach.'}
                                </p>
                            )}

                            {!detalleClase.cancelada && detalleClase.fecha >= hoy && (
                                <div className="mt-4 flex flex-wrap gap-2">
                                    <button
                                        onClick={() => abrirSelectorCoach({
                                            claseId: detalleClase.clase_id,
                                            disciplinaId: detalleClase.disciplina_id,
                                            coachIdActual: detalleClase.coach_id,
                                            etiqueta: `${detalleClase.disciplina_nombre} ${fmtFechaCortaChile(detalleClase.fecha)} ${detalleClase.hora_inicio}-${detalleClase.hora_fin}`,
                                        })}
                                        className="px-3 py-2 bg-blue-600 text-white rounded text-sm font-semibold hover:bg-blue-700"
                                    >
                                        {detalleClase.coach_id ? '👤 Reasignar coach' : '👤 Asignar coach'}
                                    </button>
                                    {detalleClase.coach_id && (
                                        <button
                                            onClick={() => setQuitarConfirm({ clase: detalleClase })}
                                            className="px-3 py-2 bg-red-600 text-white rounded text-sm font-semibold hover:bg-red-700"
                                        >
                                            🚫 Quitar coach
                                        </button>
                                    )}
                                </div>
                            )}

                            {detalleClase.fecha === hoy && (
                                <p className="mt-3 text-xs text-zinc-500">➕ Para ampliar el cupo de esta clase usa «Clases de hoy».</p>
                            )}
                        </div>
                    </div>
                )}

                {/* ══ MODAL: elegir coach (con cobertura de emergencia) ══ */}
                {coachSelector && (
                    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60" onClick={() => { if (!asignando) setCoachSelector(null); }}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-5 max-w-md w-full mx-4 border border-zinc-800" onClick={(e) => e.stopPropagation()}>
                            <h3 className="font-bold text-lg text-zinc-100">👤 Asignar coach</h3>
                            <p className="text-sm text-zinc-400">{coachSelector.etiqueta}</p>
                            <p className="text-xs text-zinc-500 mt-1 mb-3">
                                Quien no dicte la disciplina queda como ⚠️ cobertura de emergencia: el backend lo audita y avisa a los admins.
                            </p>
                            {errorCoaches && (
                                <div className="border-l-4 rounded-lg p-2 mb-3 text-xs bg-red-500/10 border-red-500 text-red-300 flex items-center justify-between gap-2">
                                    <span>{errorCoaches}</span>
                                    <button onClick={() => abrirSelectorCoach(coachSelector)} className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700">Reintentar</button>
                                </div>
                            )}
                            {cargandoCoaches ? (
                                <div className="flex justify-center py-8">
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                                </div>
                            ) : (
                                <div className="space-y-1.5 max-h-64 overflow-y-auto">
                                    {coachesDisponibles.length === 0 ? (
                                        <p className="text-zinc-500 text-sm text-center py-4">No hay coaches activos en el sistema.</p>
                                    ) : coachesDisponibles.map((cd) => {
                                        // Ya es el coach de esa clase: elegirlo respondería 409 («Esa clase ya es de X»).
                                        const yaEs = coachSelector.coachIdActual != null && cd.id === coachSelector.coachIdActual;
                                        return (
                                            <button
                                                key={cd.id}
                                                onClick={() => asignarCoach(cd)}
                                                disabled={asignando || yaEs}
                                                className={`w-full text-left p-3 rounded border transition-colors disabled:opacity-50 ${cd.pertenece
                                                    ? 'bg-zinc-800/60 border-zinc-700 hover:bg-blue-500/20'
                                                    : 'bg-amber-500/10 border-amber-500/50 hover:bg-amber-500/20'}`}
                                            >
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="font-medium text-zinc-100">{cd.nombre}</span>
                                                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${yaEs
                                                        ? 'bg-zinc-700 text-zinc-300'
                                                        : cd.pertenece
                                                            ? 'bg-emerald-500/20 text-emerald-300'
                                                            : 'bg-amber-500/20 text-amber-300'}`}>
                                                        {yaEs
                                                            ? 'Ya es su coach'
                                                            : cd.pertenece ? '✅ Dicta la disciplina' : '⚠️ Otra disciplina'}
                                                    </span>
                                                </div>
                                                {!cd.pertenece && cd.disciplinas.length > 0 && (
                                                    <p className="text-xs text-zinc-400 mt-1">Sus disciplinas: {cd.disciplinas.join(', ')}</p>
                                                )}
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                            <button
                                onClick={() => setCoachSelector(null)}
                                disabled={asignando}
                                className="mt-3 w-full py-2 bg-zinc-700 rounded text-sm font-medium hover:bg-zinc-600 disabled:opacity-50"
                            >
                                Cancelar
                            </button>
                        </div>
                    </div>
                )}

                {/* ══ MODAL: confirmar cobertura de emergencia (muestra el 409 TAL CUAL) ══ */}
                {emergenciaConfirm && (
                    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70" onClick={() => { if (!asignando) setEmergenciaConfirm(null); }}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-5 max-w-lg w-full mx-4 border border-amber-500/60" onClick={(e) => e.stopPropagation()}>
                            <h3 className="font-bold text-lg text-amber-300">⚠️ Cobertura de emergencia</h3>
                            <p className="text-sm text-zinc-300 mt-2">
                                {emergenciaConfirm.coach.nombre} → {emergenciaConfirm.etiqueta}
                            </p>
                            {/* El texto del backend (409) se muestra verbatim: es el que explica por qué hay que confirmar. */}
                            <p className="mt-3 text-xs text-amber-200 bg-amber-500/10 border-l-4 border-amber-500 rounded p-2 whitespace-pre-wrap">
                                {emergenciaConfirm.detalle}
                            </p>
                            <p className="mt-3 text-xs text-zinc-400">
                                Si confirmas: la clase queda marcada ⚠️ como cobertura de emergencia, la acción se audita con tu usuario y el coach recibe el aviso en su campana.
                            </p>
                            <div className="mt-4 flex gap-2">
                                <button
                                    onClick={confirmarEmergencia}
                                    disabled={asignando}
                                    className="flex-1 py-2 bg-amber-500 text-white rounded text-sm font-bold hover:bg-amber-600 disabled:opacity-50"
                                >
                                    {asignando ? 'Procesando…' : '✅ Sí, asignar como emergencia'}
                                </button>
                                <button
                                    onClick={() => setEmergenciaConfirm(null)}
                                    disabled={asignando}
                                    className="flex-1 py-2 bg-zinc-700 rounded text-sm font-medium hover:bg-zinc-600 disabled:opacity-50"
                                >
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* ══ MODAL: confirmar quitar el coach de la clase ══ */}
                {quitarConfirm && (
                    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70" onClick={() => { if (!asignando) setQuitarConfirm(null); }}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-5 max-w-md w-full mx-4 border border-red-500/60" onClick={(e) => e.stopPropagation()}>
                            <h3 className="font-bold text-lg text-red-300">🚫 Quitar coach de la clase</h3>
                            <p className="text-sm text-zinc-300 mt-2">
                                {quitarConfirm.clase.disciplina_nombre} · {fmtFechaCortaChile(quitarConfirm.clase.fecha)}{' '}
                                {quitarConfirm.clase.hora_inicio}-{quitarConfirm.clase.hora_fin}
                            </p>
                            <p className="text-sm text-zinc-400 mt-1">
                                Coach actual: <span className="font-medium text-zinc-200">{quitarConfirm.clase.coach_nombre || 'sin coach'}</span>
                            </p>
                            <p className="mt-3 text-xs text-zinc-400">
                                La clase queda 🔴 sin coach y el coach recibe el aviso en su campana. No toca el horario recurrente.
                            </p>
                            <div className="mt-4 flex gap-2">
                                <button
                                    onClick={quitarCoach}
                                    disabled={asignando}
                                    className="flex-1 py-2 bg-red-600 text-white rounded text-sm font-bold hover:bg-red-700 disabled:opacity-50"
                                >
                                    {asignando ? 'Quitando…' : '🚫 Sí, quitar coach'}
                                </button>
                                <button
                                    onClick={() => setQuitarConfirm(null)}
                                    disabled={asignando}
                                    className="flex-1 py-2 bg-zinc-700 rounded text-sm font-medium hover:bg-zinc-600 disabled:opacity-50"
                                >
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* ══ MODAL: "+ Agregar clase" (clase puntual) ══ */}
                <ModalClase
                    isOpen={showModalClase}
                    onClose={() => setShowModalClase(false)}
                    onSuccess={() => { setShowModalClase(false); refrescarTodo(); }}
                    tenant_id={tenant_id}
                />

                {/* ══ MODAL: reservas self-service (Open Box / Musculación) ══ */}
                {modalReservasHorario && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setModalReservasHorario(null)}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-5 max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
                            <div className="flex items-start justify-between mb-3">
                                <h3 className="font-bold text-lg text-zinc-100">
                                    📋 Reservas — {modalReservasHorario.horario.hora_inicio}-{modalReservasHorario.horario.hora_fin}
                                </h3>
                                <button onClick={() => setModalReservasHorario(null)} aria-label="Cerrar" className="text-zinc-500 hover:text-zinc-300 text-xl leading-none">&times;</button>
                            </div>
                            {modalReservasHorario.cargando ? (
                                <div className="flex justify-center py-8">
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                                </div>
                            ) : modalReservasHorario.error ? (
                                <p className="text-red-400 text-sm py-4 text-center">{modalReservasHorario.error}</p>
                            ) : !modalReservasHorario.data?.hay_clase ? (
                                <p className="text-zinc-500 text-sm py-6 text-center">
                                    {modalReservasHorario.data?.mensaje || 'No hay próxima clase generada para este horario'}
                                </p>
                            ) : (
                                <>
                                    <div className="mb-3 p-3 rounded bg-zinc-800/60 text-sm">
                                        <p className="text-zinc-200 font-medium">
                                            📅 {new Date(modalReservasHorario.data.clase.fecha + 'T12:00:00').toLocaleDateString('es-CL')}
                                        </p>
                                        <p className="text-zinc-400 text-xs mt-1">
                                            Cupo: {modalReservasHorario.data.clase.asistentes_confirmados || 0}/{modalReservasHorario.data.clase.cupo_maximo || '?'}
                                        </p>
                                    </div>
                                    {(modalReservasHorario.data.reservas || []).length === 0 ? (
                                        <p className="text-zinc-500 text-sm py-4 text-center">Sin reservas para esta clase</p>
                                    ) : (
                                        <div className="space-y-2 max-h-64 overflow-y-auto">
                                            {(modalReservasHorario.data.reservas || []).map((r) => (
                                                <div key={r.id} className="flex justify-between items-center p-2 bg-zinc-800/50 rounded">
                                                    <span className="text-sm font-medium text-zinc-200">{r.alumno_nombre}</span>
                                                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${r.asistio
                                                        ? 'bg-emerald-500/20 text-emerald-300'
                                                        : r.activa ? 'bg-sky-500/20 text-sky-300' : 'bg-red-500/20 text-red-300'}`}>
                                                        {r.asistio ? '✅ Asistió' : r.activa ? '📌 Reservado' : '❌ Cancelada'}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </Layout>
    );
}
