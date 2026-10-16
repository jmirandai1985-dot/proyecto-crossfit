import React, { useMemo, useState } from 'react';
import {
    useCrearWodsBatch, useGuardarWod, usePrevisualizarSemana, useProgramarSemana,
    usePublicarAvisoRapido,
} from '../hooks/queries';
import { useAuth } from '../context/AuthContext';
import { hoyChileStr, semanaEnCurso } from '../utils/fecha';
// El corte Mañana/Tarde/Noche de los horarios sale del MISMO util que la pestaña Asistencia
// (una sola definición de franja en todo el panel).
import { FRANJAS, franjaDe } from '../utils/franjasAsistencia';

// Días de la semana (0 = domingo, el índice de `Date.getUTCDay()`).
const DIAS_CORTOS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];

/** Día de la semana (0-6) de una fecha ISO 'AAAA-MM-DD' (mediodía UTC: sin líos de zona). */
const fechaDiaDe = (iso) => {
    const d = new Date(`${iso}T12:00:00Z`);
    return Number.isNaN(d.getTime()) ? 0 : d.getUTCDay();
};

/**
 * Modal "Publicar WOD" del panel del coach (mockup `#modal-wod`).
 * QUÉ RESUELVE: el coach publica el entrenamiento del día desde su Resumen, con el WOD
 * armado en tres partes (calentamiento, musculación, WOD) y un aviso corto opcional que el
 * alumnado ve HOY en su Inicio.
 *
 * DOS FORMAS DE ENTRAR, UNA SOLA VERDAD:
 *   * MANUAL → `POST /wods/batch-create` (el endpoint que ya usa Gestión de Clases): crea
 *     un WOD por fecha y los vincula en la MISMA transacción. "Aplicar a" usa el `clase_ids`
 *     que ya existía: `[clase.id]` = este horario · sin `clase_ids` = todas las clases de
 *     esa fecha + disciplina. "La semana" es lo mismo sobre los 7 días lunes→domingo.
 *
 * BLOQUE 1 (UI de entrada unificada): el viejo formulario de Gestión de Clases publicaba con
 * una GRILLA de días (Lun→Dom de la semana en curso) + "¿A qué horarios se publica?". Esos
 * dos controles viven acá (pasos 4 y 5 del modo manual) en vez de una copia aparte:
 *   · la grilla marca los días a publicar (el día de la clase viene marcado);
 *   · los horarios se muestran agrupados por franja (Mañana / Tarde / Noche, del util
 *     compartido `franjasAsistencia`); "Todos los horarios" = sin `clase_ids` (el backend
 *     vincula todas las clases de cada fecha) y elegir horarios = `clase_ids` con la clase
 *     de cada día (un día marcado sin clase a ese horario NO se publica, y se avisa).
 * `clasesSemana` (opcional) es la semana del coach que ya tiene el panel: de ahí salen los
 * horarios a ofrecer. Sin ella el modal sigue funcionando con el horario de la clase.
 *   * ARCHIVO (.xlsx) → `POST /wods/semana-archivo` (vista previa, no escribe) y
 *     `POST /wods/programar-semana` (1 WOD por día + el aviso de cada día, todo junto).
 *
 * EL AVISO NO DUPLICA NADA: va por `POST /marketing/aviso-rapido`, el mismo mecanismo del
 * "Aviso rápido" que ya vive en Gestión de Clases (tipo `aviso`, HOY, sin flyer). Por eso
 * el texto dice "hoy": con "la semana", el aviso es del día en que se publica.
 *
 * El WOD de cada día se ve SÓLO ese día porque lleva su `fecha`; no hay nada que "publicar"
 * a medianoche (ni acá ni en el backend).
 *
 * Props: `clase` (la clase desde la que se publica: da fecha, hora, disciplina y cupo),
 * `onCerrar`, `onPublicado(datos)`.
 */
const ModalPublicarWod = ({
    clase, clasesSemana = [], disciplinas = [], wodEdicion = null, soloArchivo = false,
    onCerrar, onPublicado,
}) => {
    // ── MODO EDICIÓN: portado de Gestión de Clases (pantalla ya retirada) ──
    // `wodEdicion` = el WOD que YA está publicado en la clase. El MISMO formulario se
    // pre-carga y al guardar hace `PUT /wods/{id}`: no se crea otro WOD, que dejaría al
    // anterior huérfano (`POST /wods/batch-create` re-apunta `clase.wod_id`). Es la razón
    // por la que la tarjeta de una clase ya publicada abre el detalle y no el formulario.
    const esEdicion = Boolean(wodEdicion?.id);
    const { usuario_id: coachId } = useAuth();
    // `soloArchivo` = la carga masiva del Excel SIN clase de por medio (el botón
    // "+ Cargar WODs de la semana" de la pestaña Clases): arranca en la rama del archivo.
    const [modo, setModo] = useState(soloArchivo ? 'archivo' : 'manual');  // 'manual' | 'archivo'
    // Disciplina del flujo sin clase: `programar-semana` la exige para vincular el WOD de
    // cada día (el backend responde 400 si un coach la omite).
    const [disciplinaSel, setDisciplinaSel] = useState('');
    const [ayuda, setAyuda] = useState(false);
    // ── BLOQUE 1: los DOS controles del modo manual (días + horarios) ──
    // Reemplazan al selector "Aplicar a" (Este horario / Todo el día / La semana), que ahora
    // es la combinación de estos dos:
    //   · `diasTocados`  null = todavía no eligió días → arranca en el día de la clase;
    //   · `horasElegidas` null = el horario de la clase · [] = TODAS las clases de cada día ·
    //     ['HH:MM', …] = sólo esos horarios (se traducen a `clase_ids`).
    const [diasTocados, setDiasTocados] = useState(null);
    const [horasTocadas, setHorasTocadas] = useState(null);
    const [form, setForm] = useState({
        calentamiento: wodEdicion?.calentamiento || '',
        musculacion: wodEdicion?.fuerza_habilidad || '',
        wod_nombre: wodEdicion?.titulo || '',
        wod_tipo: wodEdicion?.tipo_metcon || 'For Time',
        wod_descripcion: wodEdicion?.wod_principal || '',
        aviso: '',
    });
    const [error, setError] = useState('');
    const [previa, setPrevia] = useState(null);        // { dias, errores, nombre }
    const [enviando, setEnviando] = useState(false);

    const crearBatch = useCrearWodsBatch();
    const guardarWod = useGuardarWod();
    const previsualizar = usePrevisualizarSemana();
    const programar = useProgramarSemana();
    const avisoRapido = usePublicarAvisoRapido();

    const TIPOS = ['For Time', 'AMRAP', 'EMOM', 'Otro'];
    // Sin clase (carga masiva del Excel) la semana es la de HOY: el archivo trae sus fechas.
    const fechaClase = clase?.fecha ? String(clase.fecha).split('T')[0] : hoyChileStr();
    const hora = (clase?.hora_inicio || '').slice(0, 5);
    // Disciplina del flujo: la de la clase; sin clase, la que el coach elige en el modal.
    const disciplinaEfectiva = clase?.disciplina_id
        ?? (disciplinaSel ? Number(disciplinaSel) : null);
    const lunesDeLaSemana = useMemo(() => semanaEnCurso(fechaClase), [fechaClase]);
    const horaDe = (c) => String(c?.hora_inicio || '').slice(0, 5);
    const fechaDe = (c) => String(c?.fecha || '').slice(0, 10);

    // Días a publicar (los que el coach marca en la grilla).
    const fechas = useMemo(() => {
        const base = diasTocados ?? (fechaClase ? [fechaClase] : []);
        return [...base].sort();
    }, [diasTocados, fechaClase]);

    // Horarios de ESA disciplina en la semana en curso, agrupados por franja (Mañana/Tarde/
    // Noche) con el util compartido. El horario de la clase siempre está, aunque la lista de
    // la semana no lo traiga (así el modal nunca queda sin opciones).
    const clasesDeLaDisciplina = useMemo(() => (clasesSemana || [])
        .filter((c) => c?.disciplina_id === clase?.disciplina_id), [clasesSemana, clase]);
    const horasPorFranja = useMemo(() => {
        const set = new Set();
        clasesDeLaDisciplina.forEach((c) => { const h = horaDe(c); if (h) set.add(h); });
        if (hora) set.add(hora);
        const horas = [...set].sort();
        return FRANJAS
            .map((f) => ({ ...f, horas: horas.filter((h) => franjaDe(h) === f.id) }))
            .filter((f) => f.horas.length > 0);
    }, [clasesDeLaDisciplina, hora]);
    const horasElegidas = useMemo(
        () => horasTocadas ?? (hora ? [hora] : []), [horasTocadas, hora]);

    const toggleDia = (fecha) => setDiasTocados(() => {
        const base = new Set(diasTocados ?? (fechaClase ? [fechaClase] : []));
        if (base.has(fecha)) base.delete(fecha); else base.add(fecha);
        return [...base];
    });
    const toggleHora = (h) => setHorasTocadas(() => {
        const base = new Set(horasTocadas ?? (hora ? [hora] : []));
        if (base.has(h)) base.delete(h); else base.add(h);
        return [...base];
    });

    /**
     * Qué se publica de verdad: los días marcados y, si eligió horarios, sólo las clases de
     * ESOS horarios (sus ids van en el `clase_ids` de batch-create). Un día marcado sin
     * ninguna clase a ese horario NO se publica (y se avisa abajo): publicar un WOD sin
     * clases vinculadas no es lo que el coach pidió.
     */
    const planPublicacion = useMemo(() => {
        if (horasElegidas.length === 0) return { fechas, claseIds: null, diasSinClase: [] };
        const claseIds = [];
        const diasSinClase = [];
        const publicables = fechas.filter((fecha) => {
            const delDia = clasesDeLaDisciplina.filter((c) => fechaDe(c) === fecha
                && horasElegidas.includes(horaDe(c)));
            if (delDia.length === 0) { diasSinClase.push(fecha); return false; }
            claseIds.push(...delDia.map((c) => c.id));
            return true;
        });
        return { fechas: publicables, claseIds, diasSinClase };
    }, [fechas, horasElegidas, clasesDeLaDisciplina]);

    // Etiqueta del alcance (lo que se le cuenta al coach y lo que viaja en `onPublicado`).
    const etiquetaAlcance = horasElegidas.length === 0
        ? (fechas.length === 1 ? `todas las clases del ${fechas[0]}` : 'todas las clases de esos días')
        : (horasElegidas.length === 1 ? `el horario ${horasElegidas[0]}` : `${horasElegidas.length} horarios`);

    const setCampo = (campo) => (e) => setForm((prev) => ({ ...prev, [campo]: e.target.value }));

    const publicarManual = async () => {
        setError('');
        if (!form.wod_descripcion.trim()) {
            setError('La descripción del WOD es obligatoria.');
            return;
        }
        if (!fechaClase || !disciplinaEfectiva) {
            setError('No se pudo identificar la clase (fecha o disciplina).');
            return;
        }
        // ── Modo edición: actualiza el WOD que YA está en la clase (`PUT /wods/{id}`) ──
        if (esEdicion) {
            setEnviando(true);
            try {
                await guardarWod.mutateAsync({
                    wodId: wodEdicion.id,
                    payload: {
                        titulo: form.wod_nombre.trim() || null,
                        calentamiento: form.calentamiento.trim() || null,
                        fuerza_habilidad: form.musculacion.trim() || null,
                        wod_principal: form.wod_descripcion.trim(),
                        tipo_metcon: form.wod_tipo || 'Otro',
                        estado: wodEdicion.estado || 'publicado',
                        fecha: fechaClase,
                        coach_id: coachId,
                    },
                    params: { disciplina_id: disciplinaEfectiva },
                });
                if (onPublicado) onPublicado({ origen: 'edicion', clases: 1, aviso: null });
                onCerrar();
            } catch (e) {
                setError(e.response?.data?.detail || e.message || 'No se pudo actualizar el WOD');
            } finally {
                setEnviando(false);
            }
            return;
        }
        // Bloque 1: publicar sin ninguna clase vinculada no es lo que el coach pidió, así que
        // el caso se explica en pantalla en vez de mandar un lote vacío.
        if (planPublicacion.fechas.length === 0) {
            setError(horasElegidas.length === 0
                ? 'Marca al menos un día para publicar.'
                : `Ningún día marcado tiene clase a las ${horasElegidas.join(', ')}: no se publica nada así.`);
            return;
        }
        setEnviando(true);
        try {
            const body = {
                wods: planPublicacion.fechas.map((fecha) => ({
                    fecha,
                    titulo: form.wod_nombre.trim() || null,
                    calentamiento: form.calentamiento.trim() || null,
                    fuerza_habilidad: form.musculacion.trim() || null,
                    wod_principal: form.wod_descripcion.trim(),
                    tipo_metcon: form.wod_tipo || 'Otro',
                    estado: 'publicado',
                })),
            };
            // Horarios elegidos = SÓLO esas clases (`clase_ids`, una por día marcado, que es lo
            // que el endpoint ya aceptaba); "todos los horarios" va SIN la clave a propósito
            // (el backend vincula todas las clases de cada fecha + disciplina).
            if (planPublicacion.claseIds) body.clase_ids = planPublicacion.claseIds;

            const resultado = await crearBatch.mutateAsync({
                body, params: { disciplina_id: disciplinaEfectiva },
            });

            let aviso = null;
            if (form.aviso.trim()) {
                // El aviso rápido es el de HOY (backend fija la ventana): con "la semana"
                // el coach está publicando un aviso del día en que publica, y así se dice.
                aviso = await avisoRapido.mutateAsync({ texto: form.aviso.trim() });
            }
            if (onPublicado) {
                onPublicado({
                    origen: 'manual',
                    // Rótulo del alcance para quien lo muestre (el Resumen sólo usa `origen`).
                    alcance: horasElegidas.length === 0 ? 'dia' : 'horas',
                    dias: planPublicacion.fechas.length, aviso,
                    clases: resultado?.clases_vinculadas ?? 0,
                });
            }
            onCerrar();
        } catch (e) {
            setError(e.response?.data?.detail || e.message || 'No se pudo publicar el WOD');
        } finally {
            setEnviando(false);
        }
    };

    const elegirArchivo = async (evento) => {
        const archivo = evento.target.files?.[0];
        if (!archivo) return;
        setError('');
        setPrevia(null);
        try {
            const datos = await previsualizar.mutateAsync(archivo);
            setPrevia({ nombre: archivo.name, dias: datos?.dias || [], errores: datos?.errores || [] });
            setModo('archivo');
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo leer el archivo');
        } finally {
            evento.target.value = '';   // el mismo archivo se puede volver a elegir
        }
    };

    const volverAlManual = () => {
        setModo('manual');
        setPrevia(null);
        setError('');
    };

    const programarSemana = async () => {
        if (!previa?.dias?.length) return;
        setError('');
        if (!disciplinaEfectiva) {
            setError(clase?.disciplina_id
                ? 'No se pudo identificar la disciplina de la clase.'
                : 'Elige la disciplina de la semana que vas a programar.');
            return;
        }
        setEnviando(true);
        try {
            const resultado = await programar.mutateAsync({
                body: { dias: previa.dias },
                params: { disciplina_id: disciplinaEfectiva },
            });
            if (onPublicado) {
                onPublicado({
                    origen: 'archivo',
                    dias: resultado?.dias ?? previa.dias.length,
                    clases: resultado?.clases_vinculadas ?? 0,
                    avisos: resultado?.avisos ?? 0,
                });
            }
            onCerrar();
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo programar la semana');
        } finally {
            setEnviando(false);
        }
    };

    const CAMPO = 'mt-1.5 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none';
    const ETIQUETA = 'block text-[12px] text-zinc-400';
    const tagBtn = (activo) => `rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition-colors ${activo ? 'border-orange-500 bg-orange-500/15 text-orange-200' : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'}`;

    return (
        <div className="fixed inset-0 z-[60] bg-black/60 flex items-end sm:items-center justify-center p-0 sm:p-4"
            onClick={onCerrar}>
            <div className="w-full sm:max-w-lg bg-zinc-900 border-t-2 sm:border border-zinc-800 rounded-t-2xl sm:rounded-2xl max-h-[92dvh] overflow-y-auto shadow-2xl"
                onClick={(e) => e.stopPropagation()} data-testid="modal-publicar-wod">

                <div className="p-4 border-b border-zinc-800 flex items-start justify-between gap-3">
                    <div>
                        <h3 className="font-bold text-zinc-100">
                            {esEdicion ? '✏️ Editar WOD' : '📝 Publicar WOD'}
                        </h3>
                        <p className="mt-1 text-[12px] text-zinc-500">
                            {esEdicion
                                ? 'Ya está publicado en esta clase: el cambio se ve en TODAS las clases que lo llevan'
                                : soloArchivo
                                    ? 'Carga masiva: el Excel de la semana completa'
                                    : `${hora} · ${clase?.disciplina_nombre || 'Clase'} · `
                                        + `${clase?.reservas_count ?? clase?.asistentes_confirmados ?? 0} inscritos`}
                        </p>
                    </div>
                    <button type="button" onClick={onCerrar} aria-label="Cerrar"
                        className="text-xl font-bold leading-none text-zinc-400 hover:text-zinc-200">
                        ✕
                    </button>
                </div>

                <div className="p-4 space-y-4">
                    {error && (
                        <div className="rounded-xl border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-200">
                            ⚠️ {error}
                        </div>
                    )}

                    {modo === 'manual' ? (
                        <>
                            {/* El Excel no se ofrece al EDITAR: ese WOD ya está publicado y
                                el archivo crea WODs NUEVOS por día (no actualiza). */}
                            {!esEdicion && (<div>
                                <button
                                    type="button"
                                    onClick={() => document.getElementById('wod-archivo-semana').click()}
                                    disabled={enviando}
                                    data-testid="cargar-archivo-semana"
                                    className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-zinc-700 px-3 py-2.5 text-[12px] font-semibold text-sky-300 hover:border-sky-500/60 disabled:opacity-50"
                                >
                                    📄 Cargar archivo con WODs de la semana
                                </button>
                                <input
                                    id="wod-archivo-semana" type="file" accept=".xlsx" className="hidden"
                                    onChange={elegirArchivo} data-testid="input-archivo-semana"
                                />
                                <button
                                    type="button" onClick={() => setAyuda((v) => !v)}
                                    className="mt-1 text-[10.5px] text-sky-300 underline"
                                >
                                    ¿Cómo debe venir el archivo?
                                </button>
                                {ayuda && (
                                    <div className="mt-2 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-[10.5px] leading-relaxed text-zinc-400"
                                        data-testid="ayuda-archivo">
                                        Excel (.xlsx), una fila por día, en este orden:<br />
                                        <span className="font-mono text-amber-200">
                                            fecha | calentamiento | musculacion | wod_nombre | wod_tipo | wod_descripcion | aviso
                                        </span><br />
                                        · <b className="text-zinc-300">fecha</b> como fecha de Excel o AAAA-MM-DD
                                        (ej. 2026-10-13)<br />
                                        · <b className="text-zinc-300">wod_tipo</b>: For Time / AMRAP / EMOM
                                        (lo demás queda como «Otro»)<br />
                                        · calentamiento, musculacion y aviso son opcionales<br />
                                        · sin filas vacías entre días ni celdas combinadas
                                    </div>
                                )}
                                <p className="mt-3 text-center text-[11px] text-zinc-600">
                                    — o completa manualmente —
                                </p>
                            </div>)}

                            {/* El WOD ya está vinculado a su(s) clase(s): el PUT actualiza ese
                                MISMO WOD. El alcance (días/horarios) sólo aplica al crear. */}
                            {esEdicion && (
                                <div className="rounded-xl border border-amber-700/60 bg-amber-900/20 px-4 py-3 text-[11.5px] text-amber-100"
                                    data-testid="aviso-edicion-wod">
                                    ⚠️ Al guardar se actualiza el WOD que comparten estas clases:
                                    no se crea otro ni se cambia su alcance.
                                </div>
                            )}

                            <label className={ETIQUETA}>
                                1 · Calentamiento
                                <textarea rows={2} value={form.calentamiento}
                                    onChange={setCampo('calentamiento')} maxLength={500}
                                    placeholder="Ej. 400m trote + movilidad de cadera y hombro"
                                    data-testid="wod-calentamiento" className={CAMPO} />
                            </label>

                            <label className={ETIQUETA}>
                                2 · Musculación
                                <textarea rows={2} value={form.musculacion}
                                    onChange={setCampo('musculacion')} maxLength={500}
                                    placeholder="Ej. 5x5 Back Squat 70%"
                                    data-testid="wod-musculacion" className={CAMPO} />
                            </label>

                            <label className={ETIQUETA}>
                                3 · WOD · Nombre
                                <input type="text" value={form.wod_nombre} onChange={setCampo('wod_nombre')}
                                    maxLength={200} placeholder="Ej. Fran, Cindy…"
                                    data-testid="wod-nombre" className={CAMPO} />
                            </label>

                            <div>
                                <span className={ETIQUETA}>Tipo</span>
                                <div className="mt-1.5 flex flex-wrap gap-2" data-testid="wod-tipos">
                                    {TIPOS.map((t) => (
                                        <button key={t} type="button"
                                            onClick={() => setForm((p) => ({ ...p, wod_tipo: t }))}
                                            className={tagBtn(form.wod_tipo === t)}>{t}</button>
                                    ))}
                                </div>
                            </div>

                            <label className={ETIQUETA}>
                                Descripción
                                <textarea rows={3} value={form.wod_descripcion}
                                    onChange={setCampo('wod_descripcion')} maxLength={500}
                                    placeholder="Ej. 21-15-9 Thrusters / Pull-ups"
                                    data-testid="wod-descripcion" className={CAMPO} />
                            </label>

                            {/* ── BLOQUE 1: días + horarios (lo que antes era "Aplicar a") ──
                                En modo EDICIÓN no se muestran: el PUT actualiza el WOD que ya
                                está publicado, no elige alcance (eso sólo pasa al crear). */}
                            {!esEdicion && (<>
                            <div data-testid="wod-dias">
                                <span className={ETIQUETA}>4 · Días donde publicar (semana actual)</span>
                                <div className="mt-1.5 flex flex-wrap gap-1.5">
                                    {lunesDeLaSemana.map((fecha) => {
                                        const marca = DIAS_CORTOS[fechaDiaDe(fecha)];
                                        const activo = fechas.includes(fecha);
                                        return (
                                            <button
                                                key={fecha}
                                                type="button"
                                                onClick={() => toggleDia(fecha)}
                                                data-testid={`wod-dia-${fecha}`}
                                                aria-pressed={activo}
                                                className={`w-[42px] rounded-lg border px-1 py-1.5 text-center text-[10px] font-semibold transition-colors ${activo
                                                    ? 'border-orange-500 bg-orange-500/15 text-orange-200'
                                                    : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'}`}
                                            >
                                                <span className="block">{marca}</span>
                                                <span className="block text-[12px]">{Number(fecha.slice(8, 10))}</span>
                                            </button>
                                        );
                                    })}
                                </div>
                                <div className="mt-1.5 flex gap-3 text-[10.5px] text-zinc-500">
                                    <button type="button" data-testid="wod-dias-clase"
                                        onClick={() => setDiasTocados(fechaClase ? [fechaClase] : [])}
                                        className="underline hover:text-zinc-300">
                                        Sólo el día de la clase
                                    </button>
                                    <button type="button" data-testid="wod-dias-semana"
                                        onClick={() => setDiasTocados(lunesDeLaSemana)}
                                        className="underline hover:text-zinc-300">
                                        Toda la semana
                                    </button>
                                    <span>{fechas.length} día(s) marcado(s)</span>
                                </div>
                            </div>

                            <div data-testid="wod-horarios">
                                <span className={ETIQUETA}>5 · ¿A qué horarios se publica?</span>
                                <div className="mt-1.5 flex flex-wrap gap-2">
                                    <button
                                        type="button"
                                        data-testid="alcance-todos"
                                        aria-pressed={horasElegidas.length === 0}
                                        onClick={() => setHorasTocadas([])}
                                        className={tagBtn(horasElegidas.length === 0)}
                                    >
                                        Todos los horarios
                                    </button>
                                </div>
                                {horasPorFranja.map((f) => (
                                    <div key={f.id} className="mt-2">
                                        <p className="text-[10.5px] uppercase tracking-wide text-zinc-500">
                                            {f.label}
                                        </p>
                                        <div className="mt-1 flex flex-wrap gap-2">
                                            {f.horas.map((h) => (
                                                <button
                                                    key={h}
                                                    type="button"
                                                    onClick={() => toggleHora(h)}
                                                    data-testid={`horario-${h}`}
                                                    aria-pressed={horasElegidas.includes(h)}
                                                    className={tagBtn(horasElegidas.includes(h))}
                                                >
                                                    {h}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                ))}
                                <p className="mt-1.5 text-[10.5px] text-zinc-500">
                                    {horasElegidas.length === 0
                                        ? `Se publica en TODAS las clases de ${planPublicacion.fechas.length} día(s)`
                                        : `Se publica en ${planPublicacion.claseIds.length} clase(s) (${etiquetaAlcance})`}
                                </p>
                                {planPublicacion.diasSinClase.length > 0 && (
                                    <p className="mt-1 text-[10.5px] text-amber-300"
                                        data-testid="dias-sin-horario">
                                        ⚠️ {planPublicacion.diasSinClase.join(', ')}: no hay clase a ese
                                        horario — esos días no se publican.
                                    </p>
                                )}
                            </div>
                            </>)}

                            {/* El aviso de hoy es un MENSAJE NUEVO del día (no se edita): en
                                modo edición no se ofrece, igual que en la pantalla vieja. */}
                            {!esEdicion && (
                            <label className={ETIQUETA}>
                                Aviso que verán los alumnos hoy{' '}
                                <span className="text-zinc-600">(opcional)</span>
                                <textarea rows={2} value={form.aviso} onChange={setCampo('aviso')}
                                    maxLength={280} placeholder="Ej. Trae calcetas, hoy hay cuerda"
                                    data-testid="wod-aviso" className={CAMPO} />
                            </label>
                            )}

                            <button type="button" onClick={publicarManual} disabled={enviando}
                                data-testid="publicar-wod"
                                className="w-full rounded-xl bg-orange-500 px-4 py-3 text-sm font-bold text-white hover:bg-orange-600 disabled:opacity-50">
                                {enviando
                                    ? (esEdicion ? 'Guardando…' : 'Publicando…')
                                    : (esEdicion ? '💾 Guardar cambios' : 'Publicar')}
                            </button>
                        </>
                    ) : (
                        <>
                            {/* Carga masiva SIN clase (el botón de la pestaña Clases): el
                                backend exige la disciplina para vincular el WOD de cada día. */}
                            {!clase?.disciplina_id && (
                                <label className={ETIQUETA}>
                                    Disciplina de la semana
                                    <select
                                        value={disciplinaSel}
                                        onChange={(e) => setDisciplinaSel(e.target.value)}
                                        data-testid="wod-disciplina-archivo"
                                        className={CAMPO}
                                    >
                                        <option value="">Elige la disciplina…</option>
                                        {disciplinas.map((d) => (
                                            <option key={d.id} value={d.id}>{d.nombre}</option>
                                        ))}
                                    </select>
                                </label>
                            )}
                            {/* Todavía sin archivo elegido (se entró directo a la carga
                                masiva): el mismo botón + input de la rama manual. */}
                            {!previa && (
                                <div>
                                    <button
                                        type="button"
                                        onClick={() => document.getElementById('wod-archivo-semana').click()}
                                        disabled={enviando}
                                        data-testid="cargar-archivo-semana"
                                        className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-zinc-700 px-3 py-2.5 text-[12px] font-semibold text-sky-300 hover:border-sky-500/60 disabled:opacity-50"
                                    >
                                        📄 Cargar archivo con WODs de la semana
                                    </button>
                                    <input
                                        id="wod-archivo-semana" type="file" accept=".xlsx" className="hidden"
                                        onChange={elegirArchivo} data-testid="input-archivo-semana"
                                    />
                                    <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
                                        Excel (.xlsx), una fila por día, en este orden:{' '}
                                        <span className="font-mono text-amber-200">
                                            fecha | calentamiento | musculacion | wod_nombre |
                                            wod_tipo | wod_descripcion | aviso
                                        </span>
                                        . El WOD de cada día se publica en TODAS las clases de esa
                                        fecha y disciplina.
                                    </p>
                                </div>
                            )}
                            {previa && (
                            <div className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2.5">
                                <span aria-hidden="true">✅</span>
                                <span className="text-[11.5px] font-semibold text-sky-300">
                                    {previa.nombre} — {previa.dias?.length ?? 0} días detectados
                                </span>
                            </div>
                            )}

                            {previa?.errores?.length > 0 && (
                                <div className="rounded-xl border border-amber-700/60 bg-amber-900/20 px-4 py-3 text-[11.5px] text-amber-100"
                                    data-testid="errores-archivo">
                                    <p className="font-bold">Revisa el archivo ({previa.errores.length}):</p>
                                    <ul className="mt-1 list-disc space-y-0.5 pl-4">
                                        {previa.errores.map((e) => <li key={e}>{e}</li>)}
                                    </ul>
                                </div>
                            )}

                            <div>
                                <p className="text-[11px] text-zinc-500">
                                    Se publican solos en su fecha: el WOD del día se ve ESE día
                                    (y el aviso también, si el día lo trae).
                                </p>
                                <div className="mt-2 space-y-1.5" data-testid="previa-semana">
                                    {(previa?.dias || []).map((d) => (
                                        <div key={d.fecha}
                                            className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2">
                                            <span className="w-[86px] flex-none text-[10.5px] font-semibold text-zinc-400">
                                                {d.fecha}
                                            </span>
                                            <span className="flex-1 truncate text-[12.5px] text-zinc-100">
                                                {d.wod_nombre} — {d.wod_descripcion}
                                            </span>
                                            {d.aviso && (
                                                <span className="flex-none rounded bg-amber-900/30 px-1.5 py-0.5 text-[9.5px] text-amber-200">
                                                    aviso
                                                </span>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <button type="button" onClick={programarSemana}
                                disabled={enviando || !previa?.dias?.length}
                                data-testid="programar-semana"
                                className="w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-bold text-white hover:bg-blue-700 disabled:opacity-50">
                                {enviando ? 'Programando…' : 'Programar semana'}
                            </button>
                            {!soloArchivo && (
                            <button type="button" onClick={volverAlManual} disabled={enviando}
                                className="w-full rounded-xl px-4 py-2 text-[12px] font-semibold text-zinc-400 hover:text-zinc-200">
                                Cancelar y volver al formulario manual
                            </button>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ModalPublicarWod;
