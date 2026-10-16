import React, { useState } from 'react';
import { useAccionClase } from '../hooks/queries';

/**
 * Estado + acciones del coach sobre UNA clase: tomarla, soltarla y —si el coach no dicta
 * esa disciplina— CUBRIR LA SUPLENCIA (el `modo_emergencia` auditado del backend).
 *
 * POR QUÉ EXISTE: esto vivía en `pages/coach/GestionClases.jsx` (B4). Al retirarse esa
 * pantalla, la función se trajo a la pestaña Clases del panel —junto a la grilla semanal—
 * SIN cambiar de comportamiento: mismos endpoints (`POST /clases/{id}/tomar|soltar`), mismo
 * `alcance` (sólo esta clase / todas las del horario recurrente) y la misma confirmación
 * cuando el backend responde 409 porque la disciplina no es del coach.
 *
 * EL NOMBRE CAMBIÓ, LA FUNCIÓN NO: lo que el coach veía como "modo emergencia" ahora se
 * llama **"Cubrir suplencia"** (es lo que está haciendo: cubrir la clase de otro). El
 * parámetro que viaja al backend sigue siendo `modo_emergencia` y la auditoría para
 * Supervisión queda igual (`clase.cobertura_emergencia`).
 *
 * `coach_id` / `coach_nombre` / `cobertura_emergencia` / `horario_base_id` vienen en
 * `ClaseListItem`, el mismo schema que ya usaba la pantalla vieja.
 *
 * Props: `clase` · `coachId` (el coach logueado) · `coachDisciplinas` (ids que dicta: vacío
 * = sin datos, no se ofrece suplencia) · `onAviso(texto)` opcional, quién muestra el
 * resultado (el panel usa su banner).
 */
const NOMBRES_DIA = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

const horaCorta = (h) => (h ? String(h).substring(0, 5) : '');
const fechaCortaDe = (c) => (c?.fecha
    ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha)
    : '');
const diaSemanaDe = (fechaStr) => {
    const d = new Date(`${fechaStr}T12:00:00`);
    return Number.isNaN(d.getTime()) ? '' : NOMBRES_DIA[d.getDay()];
};

const AccionesClaseCoach = ({ clase, coachId, coachDisciplinas = [], onAviso }) => {
    const accionClaseMut = useAccionClase();
    // { accion: 'tomar'|'soltar', alcance: 'clase'|'horario', cargando, error }
    const [accion, setAccion] = useState(null);
    // { alcance, detalle } -> confirmación de suplencia (se muestra el 409 REAL)
    const [suplencia, setSuplencia] = useState(null);

    if (!clase?.id) return null;

    const mia = clase.coach_id != null && clase.coach_id === coachId;
    const libre = clase.coach_id == null;
    const texto = mia ? '👤 Tú' : libre ? '⚠️ Sin coach'
        : `👤 ${clase.coach_nombre || `Coach #${clase.coach_id}`}`;

    /** ¿La clase es de una disciplina que este coach NO dicta? (→ cubrir suplencia) */
    const esDeOtraDisciplina = (c) => (
        coachDisciplinas.length > 0 && c.disciplina_id != null
        && !coachDisciplinas.includes(c.disciplina_id)
    );

    const abrir = (cual) => {
        setSuplencia(null);
        // Sin horario recurrente no existe "todos los [día] [hora]": queda sólo la clase.
        setAccion({ accion: cual, alcance: 'clase', cargando: false, error: '' });
    };


    const ejecutar = async (cual, alcance, cubrirSuplencia = false) => {
        setAccion((prev) => (prev ? { ...prev, alcance, cargando: true, error: '' } : prev));
        setSuplencia(null);
        try {
            const params = { alcance };
            if (cual === 'tomar' && cubrirSuplencia) params.modo_emergencia = true;
            const data = (await accionClaseMut.mutateAsync({
                claseId: clase.id, accion: cual, params,
            })) || {};
            const cuantas = cual === 'tomar'
                ? (data.clases_tocadas ?? 1) : (data.clases_liberadas ?? 1);
            const detalle = alcance === 'horario'
                ? `${cuantas} clase(s) del horario ${diaSemanaDe(fechaCortaDe(clase))} ${horaCorta(clase.hora_inicio)}`
                : `La clase de ${horaCorta(clase.hora_inicio)} (${clase.disciplina_nombre || '-'})`;
            setAccion(null);
            onAviso?.(cual === 'tomar'
                ? `✅ ${detalle} quedó a tu nombre${cubrirSuplencia ? ' (suplencia cubierta)' : ''}.`
                : `✅ ${detalle} quedó sin coach.`);
        } catch (e) {
            const status = e.response?.status;
            const detalle = e.response?.data?.detail || e.message || 'No se pudo completar la acción';
            setAccion((prev) => (prev ? { ...prev, cargando: false, error: detalle } : prev));
            // 409 típico: "no dictas esa disciplina" → se ofrece cubrir la suplencia (mismo
            // camino auditado que la Supervisión del admin). Cualquier otro 409 (clase
            // pasada, la tiene otro coach) se queda como mensaje: reintentar volvería a fallar.
            if (cual === 'tomar' && status === 409 && esDeOtraDisciplina(clase)) {
                setSuplencia({ alcance, detalle });
            }
        }
    };

    const btnAlcance = (activo) => `w-full text-left p-3 rounded-lg border-2 transition-all ${activo
        ? 'border-emerald-500 bg-emerald-500/15 ring-2 ring-emerald-500/30'
        : 'border-zinc-700 bg-zinc-900 hover:border-emerald-500/60'}`;

    return (
        <div className="mt-1 flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <span
                className={`text-[11px] font-semibold ${mia ? 'text-emerald-400' : libre ? 'text-red-400' : 'text-zinc-400'}`}
                title={clase.cobertura_emergencia ? 'Cubierta por suplencia' : undefined}
            >
                {texto}{clase.cobertura_emergencia ? ' ⚠️' : ''}
            </span>
            {libre && (
                <button
                    type="button"
                    data-testid={`tomar-clase-${clase.id}`}
                    onClick={() => abrir('tomar')}
                    className="rounded px-2.5 py-1 text-[11px] font-bold bg-emerald-600 text-white hover:bg-emerald-700"
                >
                    ✋ Tomar
                </button>
            )}
            {mia && (
                <button
                    type="button"
                    data-testid={`soltar-clase-${clase.id}`}
                    onClick={() => abrir('soltar')}
                    className="rounded px-2.5 py-1 text-[11px] font-bold bg-zinc-700 text-zinc-100 hover:bg-zinc-600"
                >
                    Soltar
                </button>
            )}

            {/* ── Modal de alcance: sólo esta clase / todo el horario recurrente ── */}
            {accion && (
                <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4"
                    onClick={() => { if (!accion.cargando) setAccion(null); }}>
                    <div className="w-full max-w-md rounded-xl border-2 border-emerald-600/50 bg-zinc-900 p-5 shadow-2xl"
                        onClick={(e) => e.stopPropagation()} data-testid="accion-clase-modal">
                        <h2 className="text-lg font-bold text-zinc-100">
                            {accion.accion === 'tomar' ? '✋ Tomar clase' : '🖐️ Soltar clase'}
                        </h2>
                        <p className="mt-1 text-[12.5px] text-zinc-400" data-testid="accion-clase-resumen">
                            {diaSemanaDe(fechaCortaDe(clase))} {fechaCortaDe(clase)} ·{' '}
                            {horaCorta(clase.hora_inicio)}-{horaCorta(clase.hora_fin)} ·{' '}
                            {clase.disciplina_nombre || '-'} · cupo{' '}
                            {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || '?'}
                        </p>
                        <p className="mt-2 text-[12.5px] text-zinc-500">
                            {accion.accion === 'tomar'
                                ? 'La clase quedará a tu nombre (✅ en Supervisión).'
                                : 'La clase quedará sin coach (🔴 en Supervisión).'}
                        </p>

                        <div className="mt-3 space-y-2">
                            <button type="button" data-testid="alcance-clase"
                                onClick={() => setAccion((p) => ({ ...p, alcance: 'clase' }))}
                                disabled={accion.cargando} className={btnAlcance(accion.alcance === 'clase')}>
                                <span className="block text-[13px] font-bold text-zinc-100">Sólo esta clase</span>
                                <span className="block text-[11px] text-zinc-400 mt-0.5">
                                    {diaSemanaDe(fechaCortaDe(clase))} {fechaCortaDe(clase)} — 1 clase.
                                </span>
                            </button>
                            <button type="button" data-testid="alcance-horario"
                                disabled={!clase.horario_base_id || accion.cargando}
                                onClick={() => setAccion((p) => ({ ...p, alcance: 'horario' }))}
                                className={`${btnAlcance(accion.alcance === 'horario')} ${!clase.horario_base_id ? 'opacity-50 cursor-not-allowed' : ''}`}>
                                <span className="block text-[13px] font-bold text-zinc-100">Todo el horario</span>
                                <span className="block text-[11px] text-zinc-400 mt-0.5">
                                    {clase.horario_base_id
                                        ? `Las próximas clases de ${horaCorta(clase.hora_inicio)} (${diaSemanaDe(fechaCortaDe(clase))}).`
                                        : 'Esta clase no tiene horario recurrente: sólo se puede la clase suelta.'}
                                </span>
                            </button>
                        </div>

                        {accion.error && (
                            <p className="mt-3 rounded-lg border border-red-600/60 bg-red-900/30 px-3 py-2 text-[12px] text-red-200"
                                data-testid="accion-clase-error">
                                ⚠️ {accion.error}
                            </p>
                        )}

                        <div className="mt-4 flex gap-3">
                            <button
                                onClick={() => ejecutar(accion.accion, accion.alcance)}
                                disabled={accion.cargando}
                                data-testid="confirmar-accion-clase"
                                className="flex-1 rounded-lg bg-emerald-600 py-2 font-bold text-white hover:bg-emerald-700 disabled:opacity-50">
                                {accion.cargando ? 'Guardando…'
                                    : accion.accion === 'tomar' ? '✅ Tomar' : 'Soltar'}
                            </button>
                            <button onClick={() => setAccion(null)} disabled={accion.cargando}
                                className="flex-1 rounded-lg bg-zinc-800 py-2 font-medium text-zinc-300 hover:bg-zinc-700 disabled:opacity-50">
                                Cancelar
                            </button>
                        </div>
                    </div>
                </div>
            )}


            {/* ── Cubrir suplencia: el 409 del backend se muestra tal cual ── */}
            {suplencia && (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4"
                    onClick={() => setSuplencia(null)}>
                    <div className="w-full max-w-md rounded-xl border-2 border-red-500/40 bg-zinc-900 p-5 shadow-2xl"
                        onClick={(e) => e.stopPropagation()} data-testid="cubrir-suplencia-modal">
                        <h2 className="text-lg font-bold text-red-300">⚠️ Cubrir suplencia</h2>
                        <p className="mt-2 text-[12.5px] text-zinc-300" data-testid="suplencia-detalle">
                            {suplencia.detalle}
                        </p>
                        <p className="mt-2 text-[12.5px] text-zinc-500">
                            Puedes cubrirla igual: la clase queda a tu nombre y la suplencia queda
                            registrada en la auditoría para Supervisión.
                            {suplencia.alcance === 'horario'
                                && ` El alcance elegido (todo el ${diaSemanaDe(fechaCortaDe(clase))} ${horaCorta(clase.hora_inicio)}) se mantiene.`}
                        </p>
                        <div className="mt-4 flex gap-3">
                            <button
                                onClick={() => ejecutar('tomar', suplencia.alcance, true)}
                                data-testid="confirmar-suplencia-clase"
                                className="flex-1 rounded-lg bg-red-600 py-2 font-bold text-white hover:bg-red-700">
                                ✅ Sí, cubrir suplencia
                            </button>
                            <button onClick={() => setSuplencia(null)}
                                className="flex-1 rounded-lg bg-zinc-800 py-2 font-medium text-zinc-300 hover:bg-zinc-700">
                                Cancelar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default AccionesClaseCoach;

