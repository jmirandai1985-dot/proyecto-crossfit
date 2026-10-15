import React, { useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
    SIN_DATOS, useAlumnosElegiblesClase, useCrearReserva, useMarcarAsistenciaReserva,
    usePresenteSinReserva,
} from '../hooks/queries';

/**
 * Modal compartido "+ Agregar alumno sin reserva" (walk-in del panel del coach).
 *
 * POR QUÉ EXISTE: el alumno reserva por su cuenta; cuando alguien llega al box sin
 * reserva, el coach lo agrega como PRESENTE. Pero "sin reserva" NO es "gratis", así que el
 * backend parte el caso en dos y `GET /asistencia/clases/{id}/elegibles` entrega
 * `puede_reservar` (el MISMO predicado que aplica `POST /reservas`). Este modal obedece:
 *
 *   * `puede_reservar` → reserva NORMAL a nombre del alumno (`POST /reservas`: el endpoint
 *     auditado que descuenta 1 crédito) y luego se marca presente
 *     (`PUT /reservas/{id}/asistencia`). Acá no hay NADA de dinero: se reusan los dos
 *     endpoints que ya usan el mesón y el staff.
 *   * no puede reservar (sin plan o sin créditos) → `POST /asistencia/clases/{id}/sin-reserva`:
 *     presencia SIN CARGO (`tokens_gastados = 0`), que es lo que su historial muestra.
 *
 * Un fallo del camino con crédito NO cae al camino sin cargo: si entre la lectura y el POST
 * el alumno se quedó sin créditos, se muestra el motivo del backend tal cual. Cobrar o no
 * cobrar no lo decide un fallback silencioso.
 *
 * La lista la trae el backend por clase (todos los alumnos activos del box, no sólo los que
 * ya entrenaron con este coach) y el filtro por nombre es local, igual que el del tab
 * Alumnos del panel.
 *
 * BLOQUE 2 — CONFIRMACIÓN ANTES DE TOCAR EL CRÉDITO: tocar un nombre YA NO escribe nada.
 * Abre la tarjeta de confirmación (`textoConfirmacion`) con Cancelar/Confirmar, y recién el
 * "Confirmar" ejecuta el mismo camino de siempre (los mismos endpoints, sin lógica nueva).
 * El texto de esa tarjeta y el del toast posterior (`mensajeExito`) salen de la MISMA rama
 * que ejecuta `agregar`, así que no pueden mentir:
 *   · con créditos  -> "Se le descontará 1 token del plan";
 *   · ILIMITADO (`creditos_disponibles` NULL) -> NO se descuenta cupo. La reserva registra
 *     `tokens_gastados = 1`, pero el backend sólo resta cuando el número existe
 *     (`reservas.py`: `if membresia.creditos_disponibles is not None`), así que prometer un
 *     descuento ahí sería mentira;
 *   · sin plan o sin créditos -> presencia SIN CARGO (`tokens_gastados = 0`).
 *
 * Props: `clase` {id, disciplina_nombre, hora_inicio, hora_fin}; `onCerrar`;
 * `onAgregado(datos)` — quien lo abre decide dónde muestra el resultado (el detalle de
 * Asistencia y el Resumen lo pintan como toast con `datos.mensaje`, que se escribe acá y no
 * en cada pantalla).
 */
const ModalAgregarSinReserva = ({ clase, onCerrar, onAgregado }) => {
    const { tenant_id } = useAuth();
    const elegiblesQ = useAlumnosElegiblesClase(clase?.id);
    const crearReserva = useCrearReserva();
    const marcarAsistencia = useMarcarAsistenciaReserva();
    const presenteSinReserva = usePresenteSinReserva();

    const [busqueda, setBusqueda] = useState('');
    const [error, setError] = useState('');
    const [agregandoId, setAgregandoId] = useState(null);
    // Bloque 2: alumno esperando el OK de la tarjeta (`null` = se está eligiendo). Mientras
    // esté seteado, el modal muestra la confirmación y NO hay ninguna llamada en vuelo.
    const [confirmando, setConfirmando] = useState(null);

    // `SIN_DATOS` (no un `[]` nuevo) para que el `useMemo` de abajo no se recalcule en
    // cada render mientras la consulta no trae datos: es el mismo patrón del resto del
    // panel (ver `hooks/queries.js`).
    const alumnos = elegiblesQ.data || SIN_DATOS;
    const filtrados = useMemo(() => {
        const q = busqueda.trim().toLowerCase();
        if (!q) return alumnos;
        return alumnos.filter((a) => (a.nombre || '').toLowerCase().includes(q));
    }, [alumnos, busqueda]);

    const ocupado = agregandoId !== null;

    const iniciales = (nombre) => (nombre || '?')
        .split(' ').filter(Boolean).map((w) => w[0]).join('').slice(0, 2).toUpperCase();

    // Lo que le va a pasar al alumno, dicho ANTES de tocarlo (es el corazón del mockup).
    // ILIMITADO = `creditos_disponibles` NULL: la reserva registra 1 token usado, pero no hay
    // cupo que restar (ver el comentario de arriba), así que no se promete un descuento.
    const pista = (a) => {
        if (a.ya_presente) return 'Ya está en la clase';
        if (a.puede_reservar) {
            return a.ilimitado ? 'Ilimitado · no se le descuenta cupo'
                : `${a.creditos} créditos · se descuenta 1`;
        }
        if (a.plan_vigente) return 'Sin créditos · queda sin cargo';
        return 'Sin plan · queda sin cargo';
    };

    // Tarjeta de confirmación (Bloque 2): el título dice QUÉ va a pasar y el detalle POR QUÉ.
    // Las dos salen de la MISMA condición que ejecuta `agregar` (`puede_reservar`, y dentro
    // de esa rama `ilimitado` / `plan_vigente`), así que la tarjeta no puede contradecir la
    // llamada que se va a hacer al confirmar.
    const textoConfirmacion = (a) => {
        if (a.puede_reservar) {
            return a.ilimitado
                ? {
                    titulo: `Se agregará a ${a.nombre} como presente`,
                    detalle: 'Su plan es ILIMITADO: no se le descuenta cupo de clases.',
                }
                : {
                    titulo: `Se le descontará 1 token del plan a ${a.nombre}`,
                    detalle: 'La clase se reserva a su nombre y queda como presente.',
                };
        }
        return a.plan_vigente
            ? {
                titulo: `Se agregará a ${a.nombre} como presente sin costo`,
                detalle: 'No le quedan créditos: queda SIN CARGO en su historial.',
            }
            : {
                titulo: `Se agregará a ${a.nombre} como presente sin costo`,
                detalle: 'No tiene plan vigente: queda SIN CARGO en su historial.',
            };
    };

    // Toast posterior: lo pinta la pantalla que abrió el modal (esa sigue montada cuando el
    // modal se cierra), con el texto que viaja en `onAgregado`.
    const mensajeExito = (a) => {
        if (a.puede_reservar) {
            return a.ilimitado
                ? `Se registró la clase de ${a.nombre} (plan ilimitado, sin descontar cupo)`
                : `Se ha descontado un token del plan de ${a.nombre}`;
        }
        return `${a.nombre} quedó presente sin cargo (queda en su historial)`;
    };

    const agregar = async (alumno) => {
        if (ocupado || alumno.ya_presente) return;
        setError('');
        setAgregandoId(alumno.alumno_id);
        try {
            if (alumno.puede_reservar) {
                const reserva = await crearReserva.mutateAsync({
                    tenant_id, alumno_id: alumno.alumno_id, clase_id: clase.id,
                    estado: 'confirmada',
                });
                await marcarAsistencia.mutateAsync({ reservaId: reserva.id, asistio: true });
                if (onAgregado) onAgregado({ ...alumno, cargo: 'credito', mensaje: mensajeExito(alumno) });
            } else {
                await presenteSinReserva.mutateAsync({
                    claseId: clase.id, alumnoId: alumno.alumno_id,
                });
                if (onAgregado) onAgregado({ ...alumno, cargo: 'sin_cargo', mensaje: mensajeExito(alumno) });
            }
            setConfirmando(null);
            onCerrar();
        } catch (e) {
            setError(e.response?.data?.detail || 'No se pudo agregar al alumno');
        } finally {
            setAgregandoId(null);
        }
    };

    // Bloque 2: Cancelar vuelve a la lista sin tocar nada; Confirmar ejecuta el camino de
    // siempre (`agregar` → los mismos endpoints). Ninguna de las dos reintroduce lógica de
    // dinero en el front: quien descuenta es el backend.
    const cancelar = () => {
        if (ocupado) return;
        setError('');
        setConfirmando(null);
    };

    const confirmar = () => {
        if (confirmando) agregar(confirmando);
    };

    const hora = (clase?.hora_inicio || '').slice(0, 5);

    return (
        <div className="fixed inset-0 z-[60] bg-black/60 flex items-end sm:items-center justify-center p-0 sm:p-4"
            onClick={onCerrar}>
            <div className="w-full sm:max-w-lg bg-zinc-900 border-t-2 sm:border border-zinc-800 rounded-t-2xl sm:rounded-2xl max-h-[92dvh] overflow-y-auto shadow-2xl"
                onClick={(e) => e.stopPropagation()}>
                <div className="p-4 border-b border-zinc-800 flex items-start justify-between gap-3">
                    <div>
                        <h3 className="font-bold text-zinc-100">➕ Agregar sin reserva</h3>
                        <p className="mt-1 text-[12px] text-zinc-500">
                            {hora} · {clase?.disciplina_nombre || 'Clase'} — se agrega como
                            presente ahora mismo
                        </p>
                    </div>
                    <button type="button" onClick={onCerrar} aria-label="Cerrar"
                        className="text-xl font-bold leading-none text-zinc-400 hover:text-zinc-200">
                        ✕
                    </button>
                </div>

                <div className="p-4 space-y-3">
                    {/* Bloque 2 — paso 2: elegir un nombre NO descuenta nada, sólo abre esta
                        tarjeta. El descuento (o la presencia sin cargo) ocurre recién al
                        tocar "Confirmar", que llama al mismo `agregar` de siempre. */}
                    {confirmando ? (
                        <div className="space-y-3" data-testid="confirmar-token">
                            <div className="space-y-2 rounded-2xl border border-amber-600/50 bg-amber-950/30 px-4 py-4">
                                <div className="flex items-center gap-3">
                                    <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-zinc-800 text-[11px] font-bold text-zinc-200">
                                        {iniciales(confirmando.nombre)}
                                    </span>
                                    <div className="min-w-0">
                                        <p className="truncate text-[14px] font-bold text-zinc-100">
                                            {confirmando.nombre}
                                        </p>
                                        <p className="text-[11px] text-zinc-400">{pista(confirmando)}</p>
                                    </div>
                                </div>
                                <p className="text-[13px] font-semibold text-zinc-100">
                                    {textoConfirmacion(confirmando).titulo}.
                                </p>
                                <p className="text-[12px] text-zinc-400">
                                    {textoConfirmacion(confirmando).detalle}
                                </p>
                                <p className="text-[12.5px] font-semibold text-amber-200">¿Confirmas?</p>
                            </div>

                            {error && (
                                <div className="rounded-xl border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-200">
                                    ⚠️ {error}
                                </div>
                            )}

                            <div className="flex gap-2">
                                <button
                                    type="button"
                                    disabled={ocupado}
                                    onClick={cancelar}
                                    data-testid="cancelar-token"
                                    className="flex-1 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm font-semibold text-zinc-200 transition-colors hover:border-zinc-500 disabled:opacity-40"
                                >
                                    Cancelar
                                </button>
                                <button
                                    type="button"
                                    disabled={ocupado}
                                    onClick={confirmar}
                                    data-testid="confirmar-token-btn"
                                    className="flex-1 rounded-xl bg-orange-500 px-4 py-3 text-sm font-bold text-white transition-colors hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                    {ocupado ? 'Agregando…' : 'Confirmar'}
                                </button>
                            </div>

                            <p className="text-center text-[10.5px] text-zinc-500">
                                Todavía no se descontó nada: recién al confirmar.
                            </p>
                        </div>
                    ) : (
                    /* La lista de siempre, intacta. El fragmento sólo la esconde mientras la
                       tarjeta de confirmación está abierta (no cambia el DOM de la lista). */
                    <>
                    <label className="block text-[12px] text-zinc-400">
                        Buscar alumno
                        <input
                            type="text"
                            value={busqueda}
                            onChange={(e) => setBusqueda(e.target.value)}
                            placeholder="Nombre…"
                            autoFocus
                            autoComplete="off"
                            data-testid="buscar-alumno-sin-reserva"
                            className="mt-1.5 w-full rounded-xl bg-zinc-950 border border-zinc-700 px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 focus:border-orange-500 focus:outline-none"
                        />
                    </label>

                    {error && (
                        <div className="rounded-xl border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-200">
                            ⚠️ {error}
                        </div>
                    )}

                    {elegiblesQ.isPending ? (
                        <div className="flex items-center justify-center py-8">
                            <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-orange-500" />
                        </div>
                    ) : elegiblesQ.isError ? (
                        <p className="py-6 text-center text-sm text-red-300">
                            {elegiblesQ.error?.response?.data?.detail
                                || 'No se pudieron cargar los alumnos del box'}
                        </p>
                    ) : filtrados.length === 0 ? (
                        <p className="py-6 text-center text-sm text-zinc-500">
                            {busqueda ? 'No se encontraron alumnos' : 'No hay alumnos disponibles'}
                        </p>
                    ) : (
                        <div className="space-y-1.5" data-testid="lista-sin-reserva">
                            {filtrados.map((a) => (
                                <button
                                    key={a.alumno_id}
                                    type="button"
                                    disabled={ocupado || a.ya_presente}
                                    onClick={() => setConfirmando(a)}
                                    data-testid={`agregar-alumno-${a.alumno_id}`}
                                    className={`flex w-full items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-left transition-colors ${a.ya_presente ? 'opacity-50' : 'hover:border-orange-500/60'
                                        } disabled:cursor-not-allowed`}
                                >
                                    <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-zinc-800 text-[10px] font-bold text-zinc-300">
                                        {iniciales(a.nombre)}
                                    </span>
                                    <span className="flex-1 text-[13px] text-zinc-100">{a.nombre}</span>
                                    <span className={`text-[10.5px] ${a.puede_reservar && !a.ya_presente ? 'text-amber-300' : 'text-zinc-500'}`}>
                                        {agregandoId === a.alumno_id ? 'Agregando…' : pista(a)}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}

                    <p className="text-center text-[10.5px] text-zinc-600">
                        Toca un nombre: te pido confirmación antes de descontar nada.
                    </p>
                    </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ModalAgregarSinReserva;