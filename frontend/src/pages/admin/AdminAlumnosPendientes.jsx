import React from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { mapearColaLegacy, rutaPendientes } from '../../utils/pendientes';

/**
 * Redirección de compatibilidad: `/admin/alumnos-pendientes` → `/admin/pendientes`.
 *
 * La pantalla vieja era el deep-link de la campana, del Dashboard y de varios
 * correos, así que la ruta NO se elimina: queda como puente para no romper enlaces
 * guardados en teléfonos ni marcadores. La pantalla real (con las cuatro pestañas)
 * es `pages/admin/Pendientes.jsx`.
 *
 * El `?cola=` viejo se traduce a la pestaña equivalente (`mapearColaLegacy`) para
 * que el admin aterrice donde iba: `?cola=registros` abre "Registros" y
 * `?cola=solicitudes` (el default histórico) abre "Solicitudes".
 *
 * `<Navigate replace>`: sin el `replace`, el botón atrás volvería a esta ruta y
 * rebotaría otra vez, dejando al usuario atrapado en un ping-pong de redirects.
 */
const AdminAlumnosPendientes = () => {
    const [searchParams] = useSearchParams();
    const tab = mapearColaLegacy(searchParams.get('cola'));
    return <Navigate to={rutaPendientes(tab)} replace />;
};

export default AdminAlumnosPendientes;
