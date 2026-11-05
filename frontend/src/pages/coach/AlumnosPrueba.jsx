import React from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import PanelAlumnosPrueba from '../../components/PanelAlumnosPrueba';
import { useAlumnosPrueba } from '../../hooks/useAlumnosPrueba';
// La pantalla reusa el panel compartido del admin (mismos estilos y clases `.ub-admin`).
import '../admin/inicioMobileAdmin.css';

/**
 * Ruta `/coach/alumnos-prueba`.
 *
 * El coach usa el MISMO panel "Alumnos nuevos y en prueba" que el admin: los dos
 * listados + la vista previa y el envío de la invitación por correo. El backend
 * es compartido: `get_current_coach` admite administrador y coach.
 */
const CoachAlumnosPrueba = () => {
    const navigate = useNavigate();
    const estado = useAlumnosPrueba();

    return (
        <Layout>
            <div className="ub-admin ub-pagina-prueba">
                <PanelAlumnosPrueba
                    estado={estado}
                    embebido
                    onVolver={() => navigate('/coach/dashboard')}
                />
            </div>
        </Layout>
    );
};

export default CoachAlumnosPrueba;
