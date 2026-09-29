import React from 'react';
import Layout from '../../components/Layout';
import PanelHistorial from '../../components/historial/PanelHistorial';

/**
 * "Mi Historial" del alumno (`/alumno/mi-historial`).
 *
 * Misma pantalla que la del box, por la puerta del alumno
 * (`GET /alumnos/me/historial`): el backend NO manda la gestión interna
 * (arquetipo, riesgo de baja, seguimiento), que es información de administración.
 */
const MiHistorial = () => (
    <Layout>
        <div className="max-w-6xl mx-auto">
            <h1 className="text-2xl font-bold text-white mb-1">Mi historial</h1>
            <p className="text-sm text-zinc-400 mb-4">
                Tu vida en el box: clases, asistencia, plan y pagos.
            </p>
            <PanelHistorial />
        </div>
    </Layout>
);

export default MiHistorial;
