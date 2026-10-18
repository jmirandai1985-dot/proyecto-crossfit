/**
 * useAlumnosPrueba — los DOS listados de "Alumnos nuevos y en prueba".
 *
 * POR QUÉ EXISTE: la tarjeta del Inicio móvil (<768px) y la ruta de escritorio
 * `/admin/alumnos-prueba` muestran exactamente la misma pantalla. Antes el fetch
 * vivía dentro de `InicioMobileAdmin`; al abrir la pantalla desde el Dashboard de
 * escritorio no había forma de reusarlo sin duplicar endpoints y manejo de errores.
 *
 * Regla del panel: error POR SECCIÓN. Si un endpoint falla, el otro listado se
 * muestra igual y el motivo va a la vista (nunca un 0 disfrazado de dato).
 */
import { useCallback, useEffect, useState } from 'react';
import api from '../services/api';

/** Motivo legible de una promesa rechazada (misma regla que el resto del panel). */
export const motivoErrorPrueba = (resultado) => resultado?.reason?.response?.data?.detail
    || (resultado?.reason?.response?.status
        ? `HTTP ${resultado.reason.response.status}` : resultado?.reason?.message)
    || 'No se pudo cargar';

export function useAlumnosPrueba() {
    const [enPrueba, setEnPrueba] = useState([]);
    const [nuevosMes, setNuevosMes] = useState([]);
    const [cargando, setCargando] = useState(true);
    const [errorPrueba, setErrorPrueba] = useState('');
    const [errorNuevos, setErrorNuevos] = useState('');

    const cargar = useCallback(async () => {
        setCargando(true);
        const [rPrueba, rNuevos] = await Promise.allSettled([
            // Los que están EN PRUEBA: estado 🟡/🔵 + último correo manual.
            api.get('/api/v1/admin/alumnos-prueba'),
            // Los dados de alta en el mes en curso: MISMA definición que el KPI.
            api.get('/api/v1/admin/alumnos-nuevos'),
        ]);

        if (rPrueba.status === 'fulfilled') {
            setEnPrueba(Array.isArray(rPrueba.value.data?.alumnos)
                ? rPrueba.value.data.alumnos : []);
            setErrorPrueba('');
        } else {
            setEnPrueba([]);
            setErrorPrueba(motivoErrorPrueba(rPrueba));
        }

        if (rNuevos.status === 'fulfilled') {
            setNuevosMes(Array.isArray(rNuevos.value.data?.alumnos)
                ? rNuevos.value.data.alumnos : []);
            setErrorNuevos('');
        } else {
            setNuevosMes([]);
            setErrorNuevos(motivoErrorPrueba(rNuevos));
        }
        setCargando(false);
    }, []);

    useEffect(() => {
        cargar();
    }, [cargar]);

    /** El envío manual actualiza la fila sin volver a pedir los dos listados. */
    const marcarEnviado = useCallback((alumnoId, enviadoEn) => {
        setEnPrueba((prev) => prev.map((a) => (a.id === alumnoId
            ? { ...a, ultimo_envio: enviadoEn || a.ultimo_envio } : a)));
    }, []);

    return {
        enPrueba, nuevosMes, cargando, errorPrueba, errorNuevos,
        recargar: cargar, marcarEnviado,
    };
}
