import React, { useState } from 'react';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import {
    useCancelarSuspension, useElegibilidadSuspension, useMembresiaActiva,
    useMisSuspensiones,
} from '../../hooks/queries';
import ModalSuspensionPlan from '../../components/ModalSuspensionPlan';
import { fmtFechaChile } from '../../utils/fecha';

// Etiqueta + tono de cada estado del historial (mismo criterio de estado que el
// admin: activa/futura/pasada, más el caso `cancelada` del endpoint del alumno).
const ETIQUETAS_ESTADO = {
    activa: { label: 'Activa', cls: 'bg-emerald-100 text-emerald-700' },
    futura: { label: 'Futura', cls: 'bg-blue-100 text-blue-700' },
    pasada: { label: 'Pasada', cls: 'bg-gray-100 text-gray-600' },
    cancelada: { label: 'Cancelada', cls: 'bg-red-100 text-red-700' },
};

const Suspension = () => {
    const membresiaQ = useMembresiaActiva();
    const elegibilidadQ = useElegibilidadSuspension();
    const historialQ = useMisSuspensiones();
    const cancelarSuspension = useCancelarSuspension();

    const [showModal, setShowModal] = useState(false);
    const [mensaje, setMensaje] = useState(null);

    const suspActiva = elegibilidadQ.data?.suspension_activa;
    const historial = historialQ.data || [];

    const handleCancelar = async () => {
        if (!suspActiva) return;
        const ok = window.confirm(
            '¿Seguro que quieres cancelar tu suspensión? Tu plan volverá a su fecha '
            + 'de vencimiento original y las clases que ya se cancelaron no se '
            + 'recuperan. Esta acción no se puede deshacer.',
        );
        if (!ok) return;
        try {
            await cancelarSuspension.mutateAsync(suspActiva.id);
            setMensaje({ tipo: 'exito', texto: 'Suspensión cancelada: tu plan volvió a su fecha original.' });
            elegibilidadQ.refetch();
            membresiaQ.refetch();
        } catch (err) {
            const detalle = err.response?.data?.detail || 'No se pudo cancelar la suspensión.';
            setMensaje({ tipo: 'error', texto: typeof detalle === 'string' ? detalle : 'Error desconocido' });
        }
    };

    const etiquetaEstado = (estado) => ETIQUETAS_ESTADO[estado] || ETIQUETAS_ESTADO.pasada;

    return (
        <Layout>
            <div className="max-w-2xl mx-auto space-y-6">
                <div className="max-md:flex max-md:items-start max-md:gap-2">
                    <BotonVolver />
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">🏖️ Suspensión de plan</h1>
                        <p className="text-gray-600 mt-1">
                            Pausa tu plan por vacaciones o lo que necesites, y revisa tu historial.
                        </p>
                    </div>
                </div>

                {mensaje && (
                    <div className={`p-4 rounded-xl text-sm font-medium ${mensaje.tipo === 'exito'
                        ? 'bg-green-50 border border-green-200 text-green-700'
                        : 'bg-red-50 border border-red-200 text-red-700'}`}>
                        {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                    </div>
                )}

                {/* ── Suspensión activa (destacado) ────────────────────────── */}
                {suspActiva && (
                    <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
                        <h2 className="text-lg font-bold text-amber-800 mb-1">⏸️ Tienes una suspensión activa</h2>
                        <p className="text-sm text-amber-800 mb-4">
                            Del {fmtFechaChile(suspActiva.fecha_inicio)} al{' '}
                            {fmtFechaChile(suspActiva.fecha_fin)} ({suspActiva.dias} día(s)).
                        </p>
                        <button
                            type="button"
                            onClick={handleCancelar}
                            disabled={!elegibilidadQ.data?.puede_cancelar}
                            className="px-6 py-2.5 bg-red-500 text-white rounded-xl font-medium text-sm hover:bg-red-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Cancelar suspensión
                        </button>
                        {!elegibilidadQ.data?.puede_cancelar && (
                            <p className="text-sm text-amber-700 mt-2">
                                Ya cancelaste una suspensión este año: solo puedes cancelar una vez por ciclo.
                            </p>
                        )}
                    </div>
                )}

                {/* ── Mi plan + botón suspender ─────────────────────────────── */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-bold text-gray-800 mb-1">💳 Mi plan</h2>
                    {membresiaQ.data?.activa ? (
                        <p className="text-sm text-gray-500 mb-5">
                            {membresiaQ.data.plan_nombre || 'Plan'} ·{' '}
                            {membresiaQ.data.es_ilimitado
                                ? 'Ilimitado'
                                : `${membresiaQ.data.clases_disponibles ?? 0} crédito(s)`}{' '}
                            · Vence en {membresiaQ.data.dias_restantes} día(s)
                        </p>
                    ) : (
                        <p className="text-sm text-gray-500 mb-5">Sin plan activo.</p>
                    )}

                    <button
                        type="button"
                        onClick={() => setShowModal(true)}
                        disabled={!elegibilidadQ.data?.elegible}
                        className="px-6 py-2.5 bg-blue-500 text-white rounded-xl font-medium text-sm hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        🏖️ Suspender mi plan
                    </button>
                    {elegibilidadQ.data && elegibilidadQ.data.elegible === false && (
                        <p className="text-sm text-gray-500 mt-2">{elegibilidadQ.data.motivo}</p>
                    )}
                </div>

                {/* ── Reglas (siempre visibles) ────────────────────────────── */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-bold text-gray-800 mb-3">
                        Cómo funciona la suspensión de tu plan
                    </h2>
                    <p className="text-xs text-gray-400 leading-relaxed">
                        Tienes 14 días al año para suspender, divisibles en hasta
                        2 períodos. El año se cuenta desde la fecha en que te
                        inscribiste, no desde enero. Necesitas al menos 4 créditos
                        disponibles y al menos 10 días antes de que venza tu plan
                        para poder suspender. Las reservas que tengas dentro del
                        período se cancelan automáticamente. Tu fecha de vencimiento
                        se extiende exactamente los días que suspendas. Si quieres
                        volver antes de que termine tu suspensión, puedes cancelarla
                        — pero solo una vez por año. Al cancelar, tu plan vuelve a
                        su fecha de vencimiento original y no se descuenta de tu
                        saldo anual, pero las clases que ya se cancelaron no se
                        recuperan.
                    </p>
                </div>

                {/* ── Historial ───────────────────────────────────────────── */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h2 className="text-lg font-bold text-gray-800 mb-4">Historial de suspensiones</h2>
                    {historial.length === 0 ? (
                        <p className="text-sm text-gray-500">Todavía no tienes suspensiones.</p>
                    ) : (
                        <ul className="divide-y divide-gray-100">
                            {historial.map((s) => {
                                const e = etiquetaEstado(s.estado);
                                return (
                                    <li key={s.id} className="py-3 flex items-center justify-between gap-3">
                                        <div>
                                            <p className="text-sm font-medium text-gray-800">
                                                Del {fmtFechaChile(s.fecha_inicio)} al{' '}
                                                {fmtFechaChile(s.fecha_fin)}
                                            </p>
                                            <p className="text-xs text-gray-500">{s.dias} día(s)</p>
                                        </div>
                                        <span className={`inline-block px-2.5 py-1 rounded-full text-xs font-bold ${e.cls}`}>
                                            {e.label}
                                        </span>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            </div>

            {showModal && (
                <ModalSuspensionPlan
                    elegibilidad={elegibilidadQ.data}
                    onCerrar={() => setShowModal(false)}
                    onConfirmada={() => {
                        membresiaQ.refetch();
                        elegibilidadQ.refetch();
                        historialQ.refetch();
                    }}
                />
            )}
        </Layout>
    );
};

export default Suspension;

