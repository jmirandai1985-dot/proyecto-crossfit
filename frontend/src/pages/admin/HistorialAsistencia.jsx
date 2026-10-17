import React from 'react';
import Layout from '../../components/Layout';
// El MISMO componente que monta la sub-pestaña Historial del coach: una sola definición
// del cálculo para los dos roles (el backend decide el alcance por el JWT).
import HistorialAsistencia from '../../components/HistorialAsistencia';

/**
 * Pestaña "Historial de Asistencia" del panel de Administración (SÓLO LECTURA).
 *
 * Antes vivía APILADA debajo de `AsistenciaClases` en `/admin/asistencia`. Se separó en
 * su propia entrada del menú —mismo criterio que la sub-pestaña `?tab=historial` del
 * coach—: marcar (Asistencia) y revisar el mes (Historial) son dos tareas distintas, y en
 * el teléfono la segunda quedaba al final de una pantalla larga, lejos de su entrada.
 *
 * `GET /api/v1/asistencia/historial` no escribe nada y, para el admin, devuelve todas las
 * clases del box (`alcance: 'box'`). Acá no hay matemática propia: anillos, calendario y
 * totales salen del componente compartido y de `utils/historialAsistencia.js`.
 */
const AdminHistorialAsistencia = () => (
    <Layout>
        <HistorialAsistencia />
    </Layout>
);

export default AdminHistorialAsistencia;
