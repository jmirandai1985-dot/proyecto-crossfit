import React from 'react';
import { Link, useParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import BotonVolver from '../../components/BotonVolver';
import PanelHistorial from '../../components/historial/PanelHistorial';

/**
 * Historial de un alumno visto por el BOX (`/admin/alumnos/:alumnoId/historial`).
 *
 * Es la MISMA pantalla que ve el alumno (`MiHistorial`), pero por la puerta del staff
 * (`GET /alumnos/{id}/historial`): el backend agrega el bloque de gestión (arquetipo,
 * riesgo de baja, seguimiento) que el alumno no ve.
 *
 * A4 (móvil): a esta pantalla se entra desde dos sitios muy distintos —
 *   · el listado de Alumnos (escritorio), donde "Volver a Alumnos" es la salida natural;
 *   · la ficha rápida del Inicio móvil (`/admin/dashboard` con <768px), donde volver a la
 *     tabla de Alumnos dejaría al admin en una pantalla de escritorio. Ahí manda la flecha
 *     `BotonVolver`, que regresa a donde estaba (`history.back()`).
 * Por eso la flecha es SÓLO móvil y el enlace "Volver a Alumnos" es SÓLO escritorio:
 * en ≥768px la pantalla se ve EXACTAMENTE igual que hoy.
 */
const HistorialAlumno = () => {
    const { alumnoId } = useParams();
    const id = Number(alumnoId);

    return (
        <Layout>
            <div className="max-w-6xl mx-auto">
                <div className="max-md:flex max-md:items-start max-md:gap-2">
                    {/* Sin pantalla propia por detrás, la flecha cae al Inicio móvil del
                        admin: `/admin/dashboard` es la raíz del panel en <768px. */}
                    <BotonVolver fallback="/admin/dashboard" />
                    <div className="max-md:flex-1">
                        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                            <div>
                                <h1 className="text-2xl font-bold text-white">Historial del alumno</h1>
                                <p className="text-sm text-zinc-400">
                                    Asistencia, pagos, membresías y marcas: desde el alta hasta hoy.
                                </p>
                            </div>
                            <Link
                                to="/admin/alumnos"
                                className="max-md:hidden px-4 py-2 rounded-lg bg-zinc-800 text-zinc-200 text-sm font-bold hover:bg-zinc-700 transition-colors"
                            >
                                ← Volver a Alumnos
                            </Link>
                        </div>

                        {Number.isFinite(id) && id > 0 ? (
                            <PanelHistorial alumnoId={id} />
                        ) : (
                            <p className="text-sm text-red-300" data-testid="historial-alumno-invalido">
                                El id del alumno no es válido.
                            </p>
                        )}
                    </div>
                </div>
            </div>
        </Layout>
    );
};

export default HistorialAlumno;
