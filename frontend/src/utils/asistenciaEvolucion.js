/**
 * Asistencia Semanal (Evolución) — cálculo de cumplimiento y racha.
 *
 * Recibe el array que devuelve GET /api/v1/reservas/asistencia-semanal, donde cada
 * elemento es { semana: 'YYYY-Sww', asistencias, total }. Las semanas llegan ordenadas
 * ascendentemente (la más antigua primero) y SOLO incluyen semanas con al menos una
 * reserva; una semana sin reservas (sin datos) NO aparece en el array y por lo tanto
 * corta la racha (equivale a `asistencias = 0`).
 *
 * Devuelve:
 *  - cumplimientoPct: % de cumplimiento del período (Σasistencias / Σtotal * 100, redondeado).
 *  - totalAsistencias / totalReservas: sumas del período.
 *  - rachaActual: semanas consecutivas (desde la más reciente hacia atrás) con >= 1 asistencia.
 *  - mejorRacha: la racha más larga de todo el período.
 */

// Índice absoluto de una semana ISO ('YYYY-Sww') para comparar semanas consecutivas:
// el lunes de una semana ISO es siempre 7 días después del de la anterior.
function absolutoSemana(label) {
    const m = String(label || '').match(/^(\d{4})-S(\d{2})$/);
    if (!m) return null;
    const year = Number(m[1]);
    const week = Number(m[2]);
    // El 4 de enero siempre cae dentro de la semana ISO 1 (regla ISO-8601).
    const ene4 = new Date(Date.UTC(year, 0, 4));
    const lunesSemana1 = new Date(ene4);
    lunesSemana1.setUTCDate(ene4.getUTCDate() - ((ene4.getUTCDay() + 6) % 7));
    const lunes = new Date(lunesSemana1);
    lunes.setUTCDate(lunesSemana1.getUTCDate() + (week - 1) * 7);
    return Math.floor(lunes.getTime() / (7 * 86400000));
}

export function calcularRachaAsistencia(asistenciaSemanal) {
    const semanas = (asistenciaSemanal || [])
        .map((w) => ({
            asistencias: Number(w?.asistencias) || 0,
            total: Number(w?.total) || 0,
            abs: absolutoSemana(w?.semana),
        }))
        .filter((w) => w.abs !== null)
        .sort((a, b) => a.abs - b.abs);

    const totalAsistencias = semanas.reduce((s, w) => s + w.asistencias, 0);
    const totalReservas = semanas.reduce((s, w) => s + w.total, 0);
    const cumplimientoPct = totalReservas > 0
        ? Math.round((totalAsistencias / totalReservas) * 100)
        : 0;

    // Racha actual: desde la más reciente hacia atrás.
    let rachaActual = 0;
    if (semanas.length > 0 && semanas[semanas.length - 1].asistencias >= 1) {
        rachaActual = 1;
        for (let i = semanas.length - 2; i >= 0; i--) {
            if (semanas[i].asistencias < 1) break;
            if (semanas[i + 1].abs - semanas[i].abs !== 1) break; // semana sin datos → corta
            rachaActual++;
        }
    }

    // Mejor racha histórica (el streak más largo de todo el período).
    let mejorRacha = 0;
    let streak = 0;
    for (let i = 0; i < semanas.length; i++) {
        const consecutiva = i === 0 || semanas[i].abs - semanas[i - 1].abs === 1;
        if (semanas[i].asistencias >= 1 && consecutiva) {
            streak += 1;
        } else if (semanas[i].asistencias >= 1) {
            streak = 1; // hay un hueco antes → esta semana inicia una racha nueva
        } else {
            streak = 0;
        }
        if (streak > mejorRacha) mejorRacha = streak;
    }

    return {
        cumplimientoPct,
        totalAsistencias,
        totalReservas,
        rachaActual,
        mejorRacha,
    };
}
