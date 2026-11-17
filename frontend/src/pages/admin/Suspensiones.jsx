import React, { useCallback, useState } from 'react';
// La suspensión recién creada tiene que aparecer en el listado SIN recargar la página:
// se invalida la FAMILIA del listado + resumen de suspensiones del admin.
import { useQueryClient } from '@tanstack/react-query';
import Layout from '../../components/Layout';
import NuevaSuspensionModal from '../../components/admin/NuevaSuspensionModal';
import { claves, useResumenSuspensiones, useSuspensionesAdmin } from '../../hooks/queries';
import { fmtFechaChile } from '../../utils/fecha';

const ESTADOS = [
    { key: '', label: 'Todas' },
    { key: 'activa', label: 'Activas' },
    { key: 'futura', label: 'Futuras' },
    { key: 'pasada', label: 'Pasadas' },
    { key: 'cancelada', label: 'Canceladas' },
];

const tonoEstado = (estado) => {
    switch (estado) {
        case 'activa': return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
        case 'futura': return 'bg-blue-500/20 text-blue-300 border-blue-500/30';
        case 'pasada': return 'bg-zinc-700/40 text-zinc-400 border-zinc-700';
        case 'cancelada': return 'bg-red-500/20 text-red-300 border-red-500/30';
        default: return 'bg-zinc-800 text-zinc-300 border-zinc-700';
    }
};

const etiquetaEstado = (estado) => ESTADOS.find((e) => e.key === estado)?.label || estado;

/**
 * Suspensiones de plan (panel admin): supervisión + alta de la suspensión por salud.
 *
 * POR QUÉ EXISTE: la suspensión self-service la pide el alumno (sin aprobación), así que
 * el admin no acciona nada en ese caso — sólo supervisa quién está suspendido, cuántos
 * días y cuántas reservas se cancelaron de paso. La suspensión POR SALUD sí la crea el
 * admin, y hasta ahora eso sólo se podía desde la ficha del alumno (Alumnos → ficha →
 * pestaña "Suspensión"). El botón "+ Nueva suspensión" abre un modal de 2 pasos
 * (elegir alumno → fechas) que monta el MISMO `SuspensionSaludPanel` de la ficha: no
 * hay formulario ni reglas duplicadas.
 *
 * Reusa el patrón visual de las otras tablas del admin (Pedidos/Clases): header, KPIs,
 * filtros y tabla. La tabla scrollea horizontal en celular (`overflow-x-auto`) y el
 * modal entra a pantalla completa (`max-h-[92dvh] overflow-y-auto`), así que no hace
 * falta una pantalla móvil aparte.
 */
const Suspensiones = () => {
    const [buscar, setBuscar] = useState('');
    const [estado, setEstado] = useState('');
    const [desde, setDesde] = useState('');
    const [hasta, setHasta] = useState('');
    // Modal "+ Nueva suspensión" (2 pasos: alumno -> panel de suspensión por salud).
    const [modalNueva, setModalNueva] = useState(false);
    // Confirmación de la suspensión recién creada: el modal se cierra solo y el aviso
    // del panel (`SuspensionSaludPanel`) se va con él, así que queda acá.
    const [avisoCreada, setAvisoCreada] = useState('');

    const qc = useQueryClient();

    const listadoQ = useSuspensionesAdmin({ buscar, estado, desde, hasta });
    const resumenQ = useResumenSuspensiones();

    const items = listadoQ.data || [];
    const kpis = resumenQ.data || {};

    // Refresca el listado (con CUALQUIER filtro activo) y el resumen de KPIs de una vez:
    // la clave familia es el prefijo de las dos consultas.
    const refrescarSuspensiones = useCallback(() => {
        qc.invalidateQueries({ queryKey: claves.suspensionesAdminFamilia });
    }, [qc]);

    // La suspensión se creó bien desde el panel: cerrar el modal y mostrar la fila nueva.
    const alCrearSuspension = useCallback((alumno) => {
        refrescarSuspensiones();
        setModalNueva(false);
        setAvisoCreada(
            `Suspensión por salud creada para ${alumno?.nombre || 'el alumno'}.`
            + ' El listado ya la muestra.',
        );
    }, [refrescarSuspensiones]);

    // Cerrar sin crear también refresca: desde el historial del panel se puede CANCELAR
    // una suspensión por salud, y esa fila cambia de estado.
    const cerrarModalNueva = useCallback(() => {
        refrescarSuspensiones();
        setModalNueva(false);
    }, [refrescarSuspensiones]);

    const kpiCards = [
        { label: 'Activas hoy', valor: kpis.activas_hoy ?? 0, icon: '🟢' },
        { label: 'Del mes', valor: kpis.del_mes ?? 0, icon: '📅' },
        { label: 'Días totales (mes)', valor: kpis.dias_totales_mes ?? 0, icon: '🗓️' },
        { label: 'Reservas canceladas (total)', valor: kpis.reservas_canceladas_totales ?? 0, icon: '❌' },
    ];

    const loading = listadoQ.isPending && items.length === 0;

    return (
        <Layout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl font-extrabold text-zinc-100">Suspensiones de plan</h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            Supervisión de las suspensiones self-service y alta de la suspensión
                            por salud (licencia médica) del alumno.
                        </p>
                    </div>
                    {/* Mismo botón naranja del resto del panel (Clases, Coaches, Disciplinas). */}
                    <button
                        type="button"
                        onClick={() => setModalNueva(true)}
                        data-testid="btn-nueva-suspension"
                        className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm self-start"
                    >
                        + Nueva suspensión
                    </button>
                </div>

                {avisoCreada && (
                    <div
                        className="flex items-start justify-between gap-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl px-4 py-3 mb-6 text-sm text-emerald-300"
                        data-testid="aviso-suspension-creada"
                    >
                        <p>{avisoCreada}</p>
                        <button
                            type="button"
                            onClick={() => setAvisoCreada('')}
                            className="flex-none text-xs font-bold text-emerald-200 hover:text-white"
                        >
                            Ocultar
                        </button>
                    </div>
                )}

                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    {kpiCards.map((k) => (
                        <div key={k.label} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
                            <p className="text-xs text-zinc-500 uppercase tracking-wider">{k.label}</p>
                            <p className="mt-1 text-2xl font-extrabold text-zinc-100">
                                {k.icon} {k.valor}
                            </p>
                        </div>
                    ))}
                </div>

                <div className="flex flex-wrap gap-3 mb-4">
                    <input
                        type="text"
                        value={buscar}
                        onChange={(e) => setBuscar(e.target.value)}
                        placeholder="Buscar por nombre o email"
                        className="px-3 py-2.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-200 text-sm placeholder-zinc-500 focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                    />
                    <select
                        value={estado}
                        onChange={(e) => setEstado(e.target.value)}
                        className="px-3 py-2.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-200 text-sm focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                    >
                        {ESTADOS.map((e) => (
                            <option key={e.key} value={e.key}>{e.label}</option>
                        ))}
                    </select>
                    <input
                        type="date"
                        value={desde}
                        onChange={(e) => setDesde(e.target.value)}
                        className="px-3 py-2.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-200 text-sm focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                    />
                    <input
                        type="date"
                        value={hasta}
                        onChange={(e) => setHasta(e.target.value)}
                        className="px-3 py-2.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-200 text-sm focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                    />
                </div>

                {loading ? (
                    <div className="flex items-center justify-center h-64">
                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
                    </div>
                ) : items.length === 0 ? (
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-10 text-center">
                        <p className="text-3xl mb-3">🏖️</p>
                        <p className="text-zinc-300 font-medium">Sin suspensiones</p>
                        <p className="text-zinc-500 text-sm mt-1">
                            Cuando un alumno suspenda su plan, aparece acá.
                        </p>
                    </div>
                ) : (
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="bg-zinc-800">
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Alumno</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Desde</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Hasta</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Días</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Reservas canceladas</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Estado</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                    {items.map((s) => (
                                        <tr key={s.id} className="hover:bg-zinc-800/40">
                                            <td className="px-4 py-3.5">
                                                <div className="text-[13.5px] text-zinc-100">{s.alumno_nombre || `Alumno #${s.alumno_id}`}</div>
                                                {s.alumno_email && (
                                                    <div className="text-[11.5px] text-zinc-500">{s.alumno_email}</div>
                                                )}
                                            </td>
                                            <td className="px-4 py-3.5 text-[12.5px] text-zinc-400">{fmtFechaChile(s.fecha_inicio)}</td>
                                            <td className="px-4 py-3.5 text-[12.5px] text-zinc-400">{fmtFechaChile(s.fecha_fin)}</td>
                                            <td className="px-4 py-3.5 text-[13.5px] font-bold text-zinc-100">{s.dias}</td>
                                            <td className="px-4 py-3.5 text-[13.5px] text-zinc-300">{s.reservas_canceladas ?? 0}</td>
                                            <td className="px-4 py-3.5">
                                                <span className={`inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full border ${tonoEstado(s.estado)}`}>
                                                    {etiquetaEstado(s.estado)}
                                                </span>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* Paso 1 (buscar alumno) + paso 2 (el mismo panel de la ficha). */}
                {modalNueva && (
                    <NuevaSuspensionModal
                        onCerrar={cerrarModalNueva}
                        onCreada={alCrearSuspension}
                    />
                )}
            </div>
        </Layout>
    );
};

export default Suspensiones;

