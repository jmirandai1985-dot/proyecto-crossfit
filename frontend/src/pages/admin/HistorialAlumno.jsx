import React from 'react';
import { Link, useParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import PanelHistorial from '../../components/historial/PanelHistorial';

/**
 * Historial de un alumno visto por el BOX (`/admin/alumnos/:alumnoId/historial`).
 *
 * Es la MISMA pantalla que ve el alumno (`MiHistorial`), pero por la puerta del staff
 * (`GET /alumnos/{id}/historial`): el backend agrega el bloque de gestión (arquetipo,
 * riesgo de baja, seguimiento) que el alumno no ve.
 */
const HistorialAlumno = () => {
    const { alumnoId } = useParams();
    const id = Number(alumnoId);

    return (
        <Layout>
            <div className="max-w-6xl mx-auto">
                <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                    <div>
                        <h1 className="text-2xl font-bold text-white">Historial del alumno</h1>
                        <p className="text-sm text-zinc-400">
                            Asistencia, pagos, membresías y marcas: desde el alta hasta hoy.
                        </p>
                    </div>
                    <Link
                        to="/admin/alumnos"
                        className="px-4 py-2 rounded-lg bg-zinc-800 text-zinc-200 text-sm font-bold hover:bg-zinc-700 transition-colors"
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
        </Layout>
    );
};

export default HistorialAlumno;
