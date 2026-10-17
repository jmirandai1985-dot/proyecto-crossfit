import React from 'react';
import Layout from '../../components/Layout';
import AsistenciaClases from '../../components/AsistenciaClases';
// Historial del mes (SÓLO LECTURA): el "después" del marcado. Es el MISMO componente que monta
// la pestaña Historial del coach, así que el admin y el coach miran la misma cuenta.
import HistorialAsistencia from '../../components/HistorialAsistencia';

/**
 * Página "Asistencia" del panel de Administración.
 *
 * Permite al admin marcar la asistencia de CUALQUIER clase del día (sin
 * restricción de disciplina asignada) cubriendo el caso en que el coach
 * asignado no está presente. Reutiliza el componente compartido
 * AsistenciaClases en variante oscura (consistente con el resto del panel).
 * El backend ya distingue por rol (admin ve todas las clases y registra la
 * marca con via="admin").
 *
 * Debajo va el HISTORIAL DE ASISTENCIA del mes elegido (anillos por día de la
 * semana, calendario y detalle por bloque). Vive acá —y no en una pantalla
 * aparte— porque es la otra mitad de la MISMA tarea: marcar primero, revisar
 * después. `GET /api/v1/asistencia/historial` no escribe nada y para el admin
 * devuelve todas las clases del box (`alcance: 'box'`).
 */
const AdminAsistencia = () => {
    return (
        <Layout>
            <div className="space-y-8">
                <AsistenciaClases variant="dark" />
                <HistorialAsistencia />
            </div>
        </Layout>
    );
};

export default AdminAsistencia;
