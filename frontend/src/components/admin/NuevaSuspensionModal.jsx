import React, { useEffect, useRef, useState } from 'react';
import { useMutationState } from '@tanstack/react-query';
// El panel REAL de la suspensión por salud: es el MISMO que monta la ficha del alumno
// (`FichaAlumnoTabs`). Acá se monta tal cual, con `usuarioId`, sin modificarlo.
import SuspensionSaludPanel from './SuspensionSaludPanel';
import {
    MUTACION_CREAR_SUSPENSION_SALUD, SIN_DATOS, useAlumnosPaginados,
} from '../../hooks/queries';
import { haySuspensionNueva } from '../../utils/suspensiones';

// Misma UX de búsqueda que el padrón de alumnos (`pages/admin/Alumnos.jsx`): lo que
// viaja al backend sale con 350 ms de retardo (y sin retardo al vaciar la caja), así
// que no se dispara una request por tecla. La búsqueda es SERVER-SIDE (`buscar` del
// endpoint `/usuarios/`, por nombre o correo): filtrar en el cliente sólo alcanzaría
// a los primeros resultados pedidos.
const ESPERA_BUSQUEDA_MS = 350;
// Resultados por búsqueda: el modal es un selector, no una tabla paginada.
const RESULTADOS_POR_BUSQUEDA = 8;

/**
 * Modal "+ Nueva suspensión" de la pantalla Suspensiones (panel admin).
 *
 * POR QUÉ EXISTE: la pantalla se llamaba "Suspensiones" pero sólo mostraba el
 * historial; para crear una suspensión por salud había que ir a Alumnos → ficha →
 * pestaña "Suspensión". Este modal agrega ese segundo punto de entrada, en 2 pasos:
 *
 *   1. buscar y elegir al alumno (`useAlumnosPaginados`, el MISMO hook del padrón);
 *   2. montar `SuspensionSaludPanel` con el alumno elegido (el mismo panel de la ficha,
 *      con su formulario, su aviso previo y su historial). "Cambiar de alumno" vuelve
 *      al paso 1 y "Cerrar" cierra el modal.
 *
 * CÓMO SE ENTERA DE LA CREACIÓN: el panel hace la mutación por su cuenta y no recibe
 * callbacks, así que este modal NO lo modifica: observa el resultado de
 * `useCrearSuspensionSalud` en la caché de React Query (`useMutationState`, con la
 * clave `MUTACION_CREAR_SUSPENSION_SALUD`) y compara los ids que ya existían al abrir
 * el paso 2 con los de ahora. Si aparece uno nuevo, la suspensión se creó y se avisa
 * al padre (`onCreada`), que cierra el modal y refresca el listado.
 *
 * Props:
 *   * `onCerrar`: cierra el modal (botón "Cerrar", el fondo oscuro o Escape);
 *   * `onCreada(alumno)`: la suspensión se creó bien -> refrescar y cerrar.
 */
const NuevaSuspensionModal = ({ onCerrar, onCreada }) => {
    // `termino` es lo que se escribe; `busqueda` es lo que viaja al backend.
    const [termino, setTermino] = useState('');
    const [busqueda, setBusqueda] = useState('');
    // Alumno elegido en el paso 1 (`null` = todavía se está buscando).
    const [alumno, setAlumno] = useState(null);

    useEffect(() => {
        const timer = setTimeout(
            () => setBusqueda(termino.trim()),
            termino ? ESPERA_BUSQUEDA_MS : 0,
        );
        return () => clearTimeout(timer);
    }, [termino]);

    const alumnosQ = useAlumnosPaginados({
        porPagina: RESULTADOS_POR_BUSQUEDA, pagina: 1, buscar: busqueda,
    });
    const alumnos = alumnosQ.data?.lista ?? SIN_DATOS;

    // Suspensiones por salud creadas con ÉXITO para el alumno elegido, según la caché
    // de mutaciones. `select` devuelve el id de la suspensión que responde el backend;
    // la vista previa (`?preview=true`) no lo trae, así que no se confunde con un alta.
    const creadas = useMutationState({
        filters: {
            mutationKey: MUTACION_CREAR_SUSPENSION_SALUD,
            status: 'success',
            predicate: (m) => Number(m.state.variables?.usuario_id) === Number(alumno?.id),
        },
        select: (m) => m.state.data?.suspension?.id ?? null,
    });
    // String estable: el array que devuelve `useMutationState` cambia de identidad en
    // cada render y no sirve como dependencia de un efecto.
    const idsCreadas = creadas.filter((id) => id != null).join(',');

    // Foto de los ids que YA existían al abrir el paso 2: una suspensión creada en una
    // visita anterior (o desde la ficha) no puede cerrar el modal sola.
    const previasRef = useRef(null);

    useEffect(() => {
        if (!alumno) return;
        const actuales = idsCreadas ? idsCreadas.split(',').map(Number) : [];
        if (previasRef.current === null) {
            previasRef.current = new Set(actuales);
            return;
        }
        if (!haySuspensionNueva(previasRef.current, actuales)) return;
        previasRef.current = new Set(actuales);
        if (onCreada) onCreada(alumno);
    }, [alumno, idsCreadas, onCreada]);

    const elegirAlumno = (elegido) => {
        previasRef.current = null;
        setAlumno(elegido);
    };

    const cambiarAlumno = () => {
        previasRef.current = null;
        setAlumno(null);
    };

    // Escape cierra el modal, igual que el resto de los modales del panel.
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onCerrar(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onCerrar]);

    return (
        <div
            className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
            onClick={onCerrar}
            data-testid="modal-nueva-suspension"
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label="Nueva suspensión por salud"
                className="max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl border border-zinc-800 bg-zinc-900 shadow-2xl sm:max-w-2xl sm:rounded-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="border-b border-zinc-800 px-4 py-3">
                    <h2 className="text-lg font-bold text-zinc-100">Nueva suspensión por salud</h2>
                    <p className="mt-0.5 text-xs text-zinc-400" data-testid="paso-nueva-suspension">
                        {alumno
                            ? `Paso 2 de 2: define las fechas de ${alumno.nombre}.`
                            : 'Paso 1 de 2: elige al alumno que va a suspender su plan.'}
                    </p>
                </div>

                {!alumno ? (
                    <div className="space-y-3 p-4">
                        <label className="block">
                            <span className="mb-1 block text-xs text-zinc-500">Alumno</span>
                            <input
                                type="text"
                                value={termino}
                                onChange={(e) => setTermino(e.target.value)}
                                placeholder="Buscar por nombre o correo..."
                                autoFocus
                                autoComplete="off"
                                spellCheck={false}
                                data-testid="buscar-alumno-suspension"
                                className="w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none"
                            />
                        </label>

                        {alumnosQ.isError ? (
                            <p className="rounded-xl border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-200">
                                {alumnosQ.error?.response?.data?.detail
                                    || 'No se pudo buscar alumnos.'}
                            </p>
                        ) : alumnosQ.isPending && alumnos.length === 0 ? (
                            <div className="flex items-center justify-center py-8">
                                <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-orange-500" />
                            </div>
                        ) : alumnos.length === 0 ? (
                            <p className="py-6 text-center text-sm text-zinc-500">
                                {busqueda
                                    ? 'Ningún alumno coincide con la búsqueda.'
                                    : 'No hay alumnos para mostrar.'}
                            </p>
                        ) : (
                            <>
                                <p className="text-[11px] uppercase tracking-wider text-zinc-500">
                                    {busqueda
                                        ? `Resultados para "${busqueda}"`
                                        : 'Primeros alumnos del padrón'}
                                </p>
                                <div className="space-y-1.5" data-testid="resultados-alumno-suspension">
                                    {alumnos.map((a) => (
                                        <button
                                            key={a.id}
                                            type="button"
                                            onClick={() => elegirAlumno(a)}
                                            data-testid={`elegir-alumno-${a.id}`}
                                            className="flex w-full items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-left transition-colors hover:border-orange-500/60"
                                        >
                                            <span className="min-w-0">
                                                <span className="block truncate text-[13px] text-zinc-100">
                                                    {a.nombre}
                                                </span>
                                                <span className="block truncate text-[11.5px] text-zinc-500">
                                                    {a.correo}
                                                </span>
                                            </span>
                                            <span className="flex-none text-[11px] font-bold uppercase tracking-wide text-orange-400">
                                                Elegir
                                            </span>
                                        </button>
                                    ))}
                                </div>
                            </>
                        )}

                        <div className="flex justify-end pt-1">
                            <button
                                type="button"
                                onClick={onCerrar}
                                data-testid="cerrar-nueva-suspension"
                                className="rounded-xl border border-zinc-700 px-4 py-2.5 text-sm font-bold text-zinc-300 transition-colors hover:bg-zinc-800"
                            >
                                Cerrar
                            </button>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-4 p-4">
                        {/* Alumno elegido: el panel de la ficha trabaja con este id. */}
                        <div className="flex flex-col gap-2 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                            <div className="min-w-0">
                                <p className="truncate text-[13.5px] font-bold text-zinc-100">
                                    {alumno.nombre}
                                </p>
                                <p className="truncate text-[11.5px] text-zinc-500">{alumno.correo}</p>
                            </div>
                            <button
                                type="button"
                                onClick={cambiarAlumno}
                                data-testid="cambiar-alumno-suspension"
                                className="flex-none self-start rounded-lg border border-zinc-700 px-3 py-1.5 text-xs font-bold text-zinc-300 transition-colors hover:border-orange-500 hover:text-orange-300 sm:self-auto"
                            >
                                Cambiar de alumno
                            </button>
                        </div>

                        {/* El MISMO panel que monta la ficha del alumno, sin cambios. */}
                        <SuspensionSaludPanel usuarioId={alumno.id} />

                        <div className="flex justify-end border-t border-zinc-800 pt-3">
                            <button
                                type="button"
                                onClick={onCerrar}
                                data-testid="cerrar-nueva-suspension"
                                className="rounded-xl bg-orange-500 px-4 py-2.5 text-sm font-bold text-white transition-colors hover:bg-orange-600"
                            >
                                Cerrar
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default NuevaSuspensionModal;
