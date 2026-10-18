import React from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import PanelAlumnosPrueba from '../../components/PanelAlumnosPrueba';
import { useAlumnosPrueba } from '../../hooks/useAlumnosPrueba';
// La pantalla nació en el Inicio móvil; se reusa tal cual (mismos estilos y
// mismas clases `.ub-admin`) también en la ruta de escritorio.
import './inicioMobileAdmin.css';

/**
 * Ruta de ESCRITORIO `/admin/alumnos-prueba`.
 *
 * Antes la tarjeta "Alumnos Nuevos" del Dashboard navegaba a `/admin/kpis`, que
 * no es la pantalla que el admin esperaba: los listados de alumnos en prueba y
 * de altas del mes sólo existían dentro del Inicio móvil (<768px). Acá se monta
 * el MISMO panel compartido, con el CSS adaptado a una tarjeta embebida.
 */
const AlumnosPrueba = () => {
    const navigate = useNavigate();
    const estado = useAlumnosPrueba();

    return (
        <Layout>
            <div className="ub-admin ub-pagina-prueba">
                <PanelAlumnosPrueba
                    estado={estado}
                    embebido
                    onVolver={() => navigate('/admin/dashboard')}
                />
            </div>
        </Layout>
    );
};

export default AlumnosPrueba;
