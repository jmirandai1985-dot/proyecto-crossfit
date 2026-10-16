/**
 * relojClases — CUÁNDO el panel del coach tiene que volver a preguntar por el estado de sus
 * clases de hoy.
 *
 * POR QUÉ EXISTE (punto 5 del reporte móvil del Dashboard del coach): la tarjeta grande del
 * Resumen muestra la clase "en curso ahora" y ese estado (`en_curso` / `realizada`) lo decide
 * el BACKEND en hora de Chile (`clases_service.estado_clase`) — el front NO lee el reloj para
 * decidirlo. Lo que faltaba era VOLVER A PREGUNTAR: con una clase que termina 19:00 y otra que
 * arranca 19:00, el panel se quedaba con el `estado` de la carga inicial y la tarjeta no
 * cambiaba hasta recargar a mano.
 *
 * Este util devuelve el instante del PRÓXIMO borde del día (arranque o cierre de una clase),
 * así el panel agenda UN refetch en ese instante en vez de golpear la API cada minuto.
 *
 * Reglas:
 *   · Las horas del backend son de CHILE; acá se arman como instantes de la FECHA LOCAL del
 *     equipo, la misma que usa el panel para "hoy" (`toLocalDateStr(new Date())`). El coach
 *     marca asistencia desde el box (Chile), así que las dos coinciden.
 *   · Los bordes ya pasados no cuentan; si no queda ninguno, devuelve `null` (el día terminó).
 *   · `margenMs` (default 1000) empuja el borde un pelo hacia adelante: disparar exactamente
 *     en la hora podría traer todavía el estado anterior (el backend compara con `<=`).
 *   · Una clase CANCELADA no tiene borde: no se dicta.
 *
 * Lo usan el panel del coach (`DashboardCoach`) y los tests aislados
 * (`scripts/test-reloj-clases.mjs`), igual que el resto de los utils de franjas.
 */
import { horaDe } from './franjasAsistencia.js';

export const MARGEN_BORDE_MS = 1000;

/** Epoch ms de una hora 'HH:MM[:SS]' en la MISMA fecha local que `baseMs`. */
export const instanteDeHoraLocal = (hora, baseMs) => {
    const h = horaDe(hora);
    if (h === null) return null;
    const partes = String(hora).split(':');
    const minutos = Number(partes[1]) || 0;
    const base = new Date(baseMs);
    return new Date(base.getFullYear(), base.getMonth(), base.getDate(), h, minutos, 0, 0).getTime();
};

/** ¿La fecha 'YYYY-MM-DD' de la clase es la del día local de `baseMs`? (sin fecha: se asume hoy) */
export const esDelMismoDiaLocal = (fecha, baseMs) => {
    if (fecha === null || fecha === undefined || fecha === '') return true;
    const base = new Date(baseMs);
    const dos = (n) => String(n).padStart(2, '0');
    const iso = `${base.getFullYear()}-${dos(base.getMonth() + 1)}-${dos(base.getDate())}`;
    return String(fecha).slice(0, 10) === iso;
};

/** Todos los bordes futuros del día (arranques y cierres), sin repetir y ordenados. */
export const bordesDeClases = (clases, ahoraMs = Date.now(), margenMs = MARGEN_BORDE_MS) => {
    const bordes = new Set();
    (clases || []).forEach((clase) => {
        if (clase?.cancelada) return;
        if (!esDelMismoDiaLocal(clase?.fecha, ahoraMs)) return;
        [clase?.hora_inicio, clase?.hora_fin].forEach((hora) => {
            const instante = instanteDeHoraLocal(hora, ahoraMs);
            if (instante !== null && instante + margenMs > ahoraMs) bordes.add(instante + margenMs);
        });
    });
    return [...bordes].sort((a, b) => a - b);
};

/**
 * Epoch ms del PRÓXIMO borde (arranque o cierre de una clase de hoy), o `null` si no queda
 * ninguno. Es lo que el panel agenda como refetch del `estado`.
 */
export const proximoCambioDeClase = (clases, ahoraMs = Date.now(), margenMs = MARGEN_BORDE_MS) => {
    const bordes = bordesDeClases(clases, ahoraMs, margenMs);
    return bordes.length ? bordes[0] : null;
};
