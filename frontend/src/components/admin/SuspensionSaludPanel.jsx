import React, { useState } from 'react';
import {
    useSuspensionesSalud,
    usePreviewSuspensionSalud,
    useCrearSuspensionSalud,
    useCancelarSuspensionSalud,
} from '../../hooks/queries';
import { fmtFechaChile, hoyChileStr } from '../../utils/fecha';

const tonoEstado = (estado) => {
    switch (estado) {
        case 'activa': return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
        case 'futura': return 'bg-blue-500/20 text-blue-300 border-blue-500/30';
        case 'pasada': return 'bg-zinc-700/40 text-zinc-400 border-zinc-700';
        case 'cancelada': return 'bg-red-500/20 text-red-300 border-red-500/30';
        default: return 'bg-zinc-800 text-zinc-300 border-zinc-700';
    }
};

/**
 * Panel de "Suspensión por salud" (admin), embebido en la ficha del alumno.
 *
 * La suspensión por salud la crea y la cancela SOLO el admin (el alumno no la ve
 * como algo que él controla). El admin define fecha de inicio y de vuelta (no
 * días); el backend calcula `dias` y el efecto sobre la suscripción es el mismo
 * que el de la suspensión self-service. Sin tope de días ni cupo anual.
 *
 * Recibe `usuarioId` como prop y no depende de rutas propias.
 */
const SuspensionSaludPanel = ({ usuarioId }) => {
    const [fechaInicio, setFechaInicio] = useState(hoyChileStr());
    const [fechaFin, setFechaFin] = useState('');
    const [motivo, setMotivo] = useState('');
    const [error, setError] = useState(null);
    const [modal, setModal] = useState(null);
    const [confirmado, setConfirmado] = useState(null);

    const historialQ = useSuspensionesSalud(usuarioId);
    const previewM = usePreviewSuspensionSalud();
    const crearM = useCrearSuspensionSalud();
    const cancelarM = useCancelarSuspensionSalud();

    const items = historialQ.data || [];
    const rangoValido = fechaInicio && fechaFin && fechaFin > fechaInicio;

    const abrirPreview = async () => {
        setError(null);
        try {
            const p = await previewM.mutateAsync({
                usuario_id: usuarioId,
                fecha_inicio: fechaInicio,
                fecha_fin: fechaFin,
                motivo: motivo.trim() || null,
            });
            setModal({ preview: p });
        } catch (e) {
            setError(e?.response?.data?.detail || 'No se pudo calcular el aviso previo.');
        }
    };

    const confirmar = async () => {
        setError(null);
        try {
            const r = await crearM.mutateAsync({
                usuario_id: usuarioId,
                fecha_inicio: fechaInicio,
                fecha_fin: fechaFin,
                motivo: motivo.trim() || null,
            });
            setModal(null);
            setConfirmado(r);
            setFechaFin('');
            setMotivo('');
        } catch (e) {
            setError(e?.response?.data?.detail || 'No se pudo confirmar la suspensión.');
        }
    };

    const cancelar = async (suspension) => {
        setError(null);
        const ok = window.confirm(
            `¿Cancelar la suspensión por salud del ${fmtFechaChile(suspension.fecha_inicio)} ` +
            `al ${fmtFechaChile(suspension.fecha_fin)}? Se revertirá la fecha de vencimiento.`,
        );
        if (!ok) return;
        try {
            await cancelarM.mutateAsync({ suspension_id: suspension.id, usuario_id: usuarioId });
        } catch (e) {
            setError(e?.response?.data?.detail || 'No se pudo cancelar la suspensión.');
        }
    };

    return (
        <div className="space-y-5">
            {/* Formulario */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 space-y-3">
                <h3 className="text-sm font-bold text-zinc-100">Suspender por salud</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                        <label className="block text-xs text-zinc-500 mb-1">Fecha de inicio</label>
                        <input
                            type="date"
                            value={fechaInicio}
                            onChange={(e) => setFechaInicio(e.target.value)}
                            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100"
                        />
                    </div>
                    <div>
                        <label className="block text-xs text-zinc-500 mb-1">Fecha de vuelta</label>
                        <input
                            type="date"
                            value={fechaFin}
                            onChange={(e) => setFechaFin(e.target.value)}
                            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100"
                        />
                    </div>
                </div>
                <div>
                    <label className="block text-xs text-zinc-500 mb-1">Motivo (opcional)</label>
                    <input
                        type="text"
                        value={motivo}
                        onChange={(e) => setMotivo(e.target.value)}
                        placeholder="Ej. licencia médica, cirugía"
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100"
                    />
                </div>
                {error && <div className="text-xs text-red-400">{error}</div>}
                <button
                    type="button"
                    onClick={abrirPreview}
                    disabled={!rangoValido || previewM.isPending}
                    className="px-4 py-2.5 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-bold text-sm transition-colors disabled:opacity-50"
                >
                    Suspender por salud
                </button>
            </div>

            {/* Confirmación exitosa */}
            {confirmado && (
                <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-3 text-sm text-emerald-300">
                    Suspensión confirmada: {confirmado.suspension?.dias} día(s), nueva fecha de
                    vencimiento {fmtFechaChile(confirmado.fecha_expiracion)}.
                </div>
            )}

            {/* Historial */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
                <div className="px-4 py-3 border-b border-zinc-800">
                    <h3 className="text-sm font-bold text-zinc-100">
                        Historial de suspensiones por salud
                    </h3>
                </div>
                {historialQ.isPending && items.length === 0 ? (
                    <p className="px-4 py-6 text-sm text-zinc-500">Cargando...</p>
                ) : items.length === 0 ? (
                    <p className="px-4 py-6 text-sm text-zinc-500">Sin suspensiones por salud.</p>
                ) : (
                    <table className="w-full text-left">
                        <thead className="bg-zinc-800/60">
                            <tr className="text-[11px] uppercase tracking-wider text-zinc-500">
                                <th className="px-4 py-3 font-bold">Desde</th>
                                <th className="px-4 py-3 font-bold">Hasta</th>
                                <th className="px-4 py-3 font-bold">Días</th>
                                <th className="px-4 py-3 font-bold">Motivo</th>
                                <th className="px-4 py-3 font-bold">Estado</th>
                                <th className="px-4 py-3 font-bold" />
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800">
                            {items.map((s) => (
                                <tr key={s.id} className="hover:bg-zinc-800/40">
                                    <td className="px-4 py-3 text-[12.5px] text-zinc-300">
                                        {fmtFechaChile(s.fecha_inicio)}
                                    </td>
                                    <td className="px-4 py-3 text-[12.5px] text-zinc-300">
                                        {fmtFechaChile(s.fecha_fin)}
                                    </td>
                                    <td className="px-4 py-3 text-[13.5px] font-bold text-zinc-100">
                                        {s.dias}
                                    </td>
                                    <td className="px-4 py-3 text-[12.5px] text-zinc-400">
                                        {s.motivo || '—'}
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`inline-flex items-center text-[11px] font-bold px-2.5 py-1 rounded-full border ${tonoEstado(s.estado)}`}>
                                            {s.estado}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-right">
                                        {s.estado === 'activa' && !s.cancelada && (
                                            <button
                                                type="button"
                                                onClick={() => cancelar(s)}
                                                disabled={cancelarM.isPending}
                                                className="px-3 py-1.5 border border-red-500/40 text-red-300 rounded-lg hover:bg-red-500/10 text-xs font-bold transition-colors disabled:opacity-50"
                                            >
                                                Cancelar
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {/* Modal de confirmación (aviso previo) */}
            {modal && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-xl shadow-xl max-w-md w-full">
                        <div className="bg-orange-500 text-white px-6 py-4 rounded-t-xl">
                            <h2 className="text-lg font-bold">Confirmar suspensión por salud</h2>
                        </div>
                        <div className="p-6 space-y-4">
                            <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 text-sm text-orange-800 space-y-1">
                                <p>
                                    Días a suspender: <strong>{modal.preview.dias}</strong>
                                </p>
                                <p>
                                    Nueva fecha de vencimiento:{' '}
                                    <strong>{fmtFechaChile(modal.preview.fecha_expiracion_nueva)}</strong>
                                </p>
                            </div>
                            {modal.preview.reservas_a_cancelar?.length > 0 ? (
                                <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
                                    <p className="font-bold mb-2">
                                        Se cancelarán {modal.preview.reservas_a_cancelar.length} reserva(s):
                                    </p>
                                    <ul className="space-y-1">
                                        {modal.preview.reservas_a_cancelar.map((r) => (
                                            <li key={r.reserva_id}>
                                                · {r.disciplina} — {fmtFechaChile(r.fecha)} {r.hora_inicio}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            ) : (
                                <p className="text-sm text-zinc-500">No hay reservas en el rango.</p>
                            )}
                            {error && <div className="text-xs text-red-600">{error}</div>}
                            <div className="flex gap-3 pt-1">
                                <button
                                    type="button"
                                    onClick={() => setModal(null)}
                                    className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors"
                                >
                                    Volver
                                </button>
                                <button
                                    type="button"
                                    onClick={confirmar}
                                    disabled={crearM.isPending}
                                    className="flex-1 px-4 py-3 bg-orange-600 text-white rounded-xl hover:bg-orange-700 font-bold text-sm transition-colors disabled:opacity-50"
                                >
                                    {crearM.isPending ? 'Confirmando...' : 'Confirmar suspensión'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SuspensionSaludPanel;


