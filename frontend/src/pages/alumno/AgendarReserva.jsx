import React, { useState } from 'react';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import GrillaReservaClases, { ModalConfirmarReserva } from '../../components/GrillaReservaClases';
import { useAuth } from '../../context/AuthContext';
import { useClasesRango, useCrearReserva, useReservasConfirmadas } from '../../hooks/queries';
import { agruparClasesPorDia, getProximosDias } from '../../utils/grillaReserva';

/**
 * "Agendar Reserva" (Bloque 2): la pestaña con la grilla REAL para TOMAR una
 * clase nueva (selector de día + horarios + botón Reservar). Antes esa grilla
 * vivía escondida dentro del Inicio (Dashboard.jsx); ahora las dos pantallas
 * montan el MISMO componente compartido `GrillaReservaClases` y el MISMO modal
 * `ModalConfirmarReserva`, sin lógica duplicada.
 *
 * Los datos son los mismos del Inicio (mismas queryKeys): si el alumno viene de
 * ahí, la grilla se pinta al instante desde la caché de React Query.
 */
const AgendarReserva = () => {
    const { usuario_id, tenant_id } = useAuth();
    const [claseSeleccionada, setClaseSeleccionada] = useState(null);

    const proximosDias = getProximosDias();
    const fechaHasta = proximosDias[proximosDias.length - 1]?.fecha || proximosDias[0]?.fecha;

    const clasesQ = useClasesRango(proximosDias[0]?.fecha, fechaHasta);
    const reservasQ = useReservasConfirmadas();
    const crearReserva = useCrearReserva();

    const clasesPorDia = React.useMemo(
        () => agruparClasesPorDia(clasesQ.data),
        [clasesQ.data],
    );
    // Sólo las reservas activas: es lo que usa el modal para avisar que la clase
    // sería la segunda del día (mismo criterio que el Inicio).
    const misReservas = reservasQ.data || [];

    // La mutación invalida ['reservas'], ['clases'], ['membresia'] y ['asistencia']:
    // el cupo y los créditos se refrescan solos en esta pantalla y en el Inicio.
    const confirmarReserva = (clase) => crearReserva.mutateAsync({
        tenant_id,
        alumno_id: usuario_id,
        clase_id: clase.id,
        estado: 'confirmada',
    });

    return (
        <Layout>
            <div className="mx-auto max-w-4xl space-y-5">
                <div className="flex items-center gap-3">
                    <BotonVolver fallback="/alumno/dashboard" />
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Agendar Reserva</h1>
                        <p className="mt-0.5 text-sm text-gray-500">
                            Elige el día y el horario de tu próxima clase.
                        </p>
                    </div>
                </div>

                {clasesQ.isError && (
                    <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                        No se pudieron cargar las clases disponibles. Intenta nuevamente.
                    </div>
                )}

                {clasesQ.isPending ? (
                    <div className="flex items-center justify-center py-16">
                        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-emerald-500" />
                    </div>
                ) : (
                    <GrillaReservaClases
                        proximosDias={proximosDias}
                        clasesPorDia={clasesPorDia}
                        onReservar={setClaseSeleccionada}
                    />
                )}
            </div>

            <ModalConfirmarReserva
                clase={claseSeleccionada}
                misReservas={misReservas}
                onCerrar={() => setClaseSeleccionada(null)}
                onConfirmar={confirmarReserva}
            />
        </Layout>
    );
};

export default AgendarReserva;
