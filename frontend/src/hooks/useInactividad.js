/**
 * useInactividad — cierre de sesión automático a los 10 minutos sin actividad.
 *
 * Se monta UNA vez en `Layout`, que es el marco compartido de los TRES paneles (alumno, coach y
 * admin): no hay tres copias que se puedan desincronizar.
 *
 * Cómo mide la inactividad
 * ------------------------
 *  · `ultimaActividad` se actualiza con eventos reales del usuario (mouse, teclado, touch y
 *    scroll). No se resetea por requests de fondo: un badge que se refresca solo NO cuenta
 *    como "el usuario está usando la app".
 *  · Un intervalo revisa cada 15 s. Además, al volver a la pestaña (`visibilitychange`) se
 *    revisa de inmediato: los navegadores frenan los timers en background, y sin ese chequeo
 *    una pestaña olvidada 20 minutos podía seguir "viva" hasta el siguiente tick.
 *  · Al vencer: `logout()` (borra la sesión) y `navigate('/login?motivo=inactividad')` con
 *    `replace` (el botón atrás no vuelve a una pantalla protegida).
 *
 * `debeCerrarSesion` es pura y se testea sin navegador (`scripts/test-inactividad.mjs`).
 */
import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
    EVENTOS_ACTIVIDAD, INTERVALO_CHEQUEO_MS, MINUTOS_INACTIVIDAD, MS_INACTIVIDAD,
    debeCerrarSesion,
} from '../utils/inactividad';

// Re-export para que el hook siga siendo el punto de entrada del componente, pero la lógica
// pura (constantes + `debeCerrarSesion`) viva en utils y se pueda testear sin React.
export {
    EVENTOS_ACTIVIDAD, INTERVALO_CHEQUEO_MS, MINUTOS_INACTIVIDAD, MS_INACTIVIDAD,
    debeCerrarSesion,
};

export function useInactividad() {
    const { logout } = useAuth();
    const navigate = useNavigate();
    const ultimaActividad = useRef(Date.now());
    const cerrada = useRef(false);

    useEffect(() => {
        const registrarActividad = () => { ultimaActividad.current = Date.now(); };

        const revisar = () => {
            if (cerrada.current) return;
            if (!debeCerrarSesion(ultimaActividad.current)) return;
            cerrada.current = true;
            logout();
            navigate('/login?motivo=inactividad', { replace: true });
        };

        EVENTOS_ACTIVIDAD.forEach(
            (evento) => window.addEventListener(evento, registrarActividad, { passive: true }),
        );
        document.addEventListener('visibilitychange', revisar);
        const intervalo = setInterval(revisar, INTERVALO_CHEQUEO_MS);

        return () => {
            EVENTOS_ACTIVIDAD.forEach(
                (evento) => window.removeEventListener(evento, registrarActividad),
            );
            document.removeEventListener('visibilitychange', revisar);
            clearInterval(intervalo);
        };
    }, [logout, navigate]);
}

export default useInactividad;
