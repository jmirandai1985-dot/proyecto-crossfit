import React, { useState } from 'react';
import { useCrearSuspension, useElegibilidadSuspension } from '../hooks/queries';
import { fechaSolaAInstante, fmtFechaChile, hoyChileStr } from '../utils/fecha';

/**
 * Modal de suspensión de plan (self-service del alumno), flujo de 3 pasos:
 * 1) saldo + selector de rango (con tope en el saldo) + términos;
 * 2) aviso previo con las reservas que se cancelarán;
 * 3) confirmación con la nueva fecha de vencimiento.
 */
const ModalSuspensionPlan = ({ elegibilidad, onCerrar, onConfirmada }) => {
    const saldo = elegibilidad?.saldo_disponible ?? 0;

    const [paso, setPaso] = useState(1);
    const [fechaInicio, setFechaInicio] = useState(hoyChileStr());
    const [dias, setDias] = useState(1);
    const [aceptado, setAceptado] = useState(false);
    const [error, setError] = useState(null);
    const [resultado, setResultado] = useState(null);

    const previewQ = useElegibilidadSuspension({ fechaInicio, dias });
    const crear = useCrearSuspension();

    const reservas = previewQ.data?.reservas_a_cancelar || [];
    const diasValido = dias >= 1 && dias <= saldo;

    const cambiarDias = (v) => {
        const n = Number(v) || 1;
        setDias(Math.max(1, Math.min(saldo, n)));
    };

    const continuar = () => {
        setError(null);
        setPaso(2);
    };

    const confirmar = async () => {
        setError(null);
        try {
            const r = await crear.mutateAsync({ fecha_inicio: fechaInicio, dias });
            setResultado(r);
            setPaso(3);
            if (onConfirmada) onConfirmada();
        } catch (e) {
            setError(e?.response?.data?.detail || 'No se pudo confirmar la suspensión.');
        }
    };

    const fin = fmtFechaChile(
        new Date(fechaSolaAInstante(fechaInicio).getTime() + (dias - 1) * 86400000),
    );

    return (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-xl shadow-xl max-w-md w-full">
                <div className="bg-emerald-600 text-white px-6 py-4 rounded-t-xl">
                    <h2 className="text-lg font-bold">🏖️ Suspender mi plan</h2>
                    <p className="text-emerald-100 text-sm">
                        Pausa tu plan por vacaciones o lo que necesites.
                    </p>
                </div>

                <div className="p-6 space-y-4">
                    {error && (
                        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                            ❌ {error}
                        </div>
                    )}

                    {/* ── PASO 1: saldo + rango + términos ─────────────────── */}
                    {paso === 1 && (
                        <>
                            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-800">
                                Te quedan <strong>{saldo} día(s)</strong> de suspensión
                                en este ciclo (14 por año).
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Fecha de inicio
                                </label>
                                <input
                                    type="date"
                                    value={fechaInicio}
                                    min={hoyChileStr()}
                                    onChange={(e) => setFechaInicio(e.target.value)}
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Días a suspender (máximo {saldo})
                                </label>
                                <input
                                    type="number"
                                    min={1}
                                    max={saldo}
                                    value={dias}
                                    onChange={(e) => cambiarDias(e.target.value)}
                                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                                />
                            </div>

                            <label className="flex items-start gap-2 text-sm text-gray-600">
                                <input
                                    type="checkbox"
                                    checked={aceptado}
                                    onChange={(e) => setAceptado(e.target.checked)}
                                    className="mt-0.5"
                                />
                                <span>
                                    Entiendo que durante la suspensión no podré reservar
                                    clases y que mi plan se extiende {dias} día(s).
                                </span>
                            </label>

                            <div className="flex gap-3 pt-2">
                                <button
                                    type="button"
                                    onClick={onCerrar}
                                    className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors"
                                >
                                    Cancelar
                                </button>
                                <button
                                    type="button"
                                    onClick={continuar}
                                    disabled={!aceptado || !diasValido}
                                    className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50"
                                >
                                    Continuar
                                </button>
                            </div>
                        </>
                    )}

                    {/* ── PASO 2: aviso de reservas + confirmar ─────────────── */}
                    {paso === 2 && (
                        <>
                            <div className="bg-gray-50 rounded-xl p-4 text-sm space-y-1">
                                <p className="font-bold text-gray-900">
                                    Del {fmtFechaChile(fechaSolaAInstante(fechaInicio))} al {fin}
                                </p>
                                <p className="text-gray-600">{dias} día(s) de suspensión</p>
                            </div>

                            {reservas.length > 0 && (
                                <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
                                    <p className="font-bold mb-2">
                                        ⚠️ Se cancelarán {reservas.length} reserva(s):
                                    </p>
                                    <ul className="space-y-1">
                                        {reservas.map((r) => (
                                            <li key={r.reserva_id}>
                                                · {r.disciplina} —{' '}
                                                {fmtFechaChile(fechaSolaAInstante(r.fecha))}{' '}
                                                {r.hora_inicio}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            <div className="flex gap-3 pt-2">
                                <button
                                    type="button"
                                    onClick={() => setPaso(1)}
                                    className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors"
                                >
                                    Volver
                                </button>
                                <button
                                    type="button"
                                    onClick={confirmar}
                                    disabled={crear.isPending}
                                    className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50"
                                >
                                    {crear.isPending ? 'Confirmando...' : 'Confirmar suspensión'}
                                </button>
                            </div>
                        </>
                    )}

                    {/* ── PASO 3: confirmación ──────────────────────────────── */}
                    {paso === 3 && resultado && (
                        <>
                            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-800 space-y-1">
                                <p className="font-bold text-lg">✅ ¡Plan suspendido!</p>
                                <p>Nueva fecha de vencimiento:</p>
                                <p className="font-bold">
                                    {fmtFechaChile(resultado.fecha_expiracion)}
                                </p>
                                {resultado.reservas_canceladas?.length > 0 && (
                                    <p className="text-xs">
                                        Se cancelaron {resultado.reservas_canceladas.length}{' '}
                                        reserva(s) del período.
                                    </p>
                                )}
                            </div>
                            <button
                                type="button"
                                onClick={onCerrar}
                                className="w-full px-4 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors"
                            >
                                Entendido
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ModalSuspensionPlan;

