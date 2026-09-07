import React from 'react';
import Layout from '../../components/Layout';
import AsistenciaClases from '../../components/AsistenciaClases';

/**
 * Página "Asistencia" del panel de Administración.
 *
 * Permite al admin marcar la asistencia de CUALQUIER clase del día (sin
 * restricción de disciplina asignada) cubriendo el caso en que el coach
 * asignado no está presente. Reutiliza el componente compartido
 * AsistenciaClases en variante oscura (consistente con el resto del panel).
 * El backend ya distingue por rol (admin ve todas las clases y registra la
 * marca con via="admin").
 */
const AdminAsistencia = () => {
    return (
        <Layout>
            <AsistenciaClases variant="dark" />
        </Layout>
    );
};

export default AdminAsistencia;
