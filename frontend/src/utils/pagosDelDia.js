/**
 * Cantidad y total CLP de los cobros del día (`GET /admin/pagos-del-dia`).
 *
 * UNA sola definición para que la tarjeta "Ingresos de hoy" y la lista "Pagos del
 * día" no puedan mostrar números distintos: la tarjeta toma su valor de acá y la
 * lista pinta su encabezado con la misma función.
 *
 * El backend ya manda `resumen.cantidad` / `resumen.total_clp` calculados sobre la
 * lista COMPLETA del día (membresías + Bazar, aprobados y pendientes). Sólo si el
 * resumen no viniera se suman los montos de `pagos` — nunca un 0 falso.
 */
export function resumenPagosDelDia(data) {
    const pagos = Array.isArray(data?.pagos) ? data.pagos : [];
    const resumen = data?.resumen || {};
    const cantidadCruda = resumen.cantidad == null ? pagos.length : Number(resumen.cantidad);
    const totalCrudo = resumen.total_clp == null
        ? pagos.reduce((acc, p) => acc + Number(p.monto_clp || 0), 0)
        : Number(resumen.total_clp);
    return {
        pagos,
        cantidad: Number.isFinite(cantidadCruda) ? cantidadCruda : pagos.length,
        totalClp: Number.isFinite(totalCrudo) ? totalCrudo : 0,
    };
}

export default resumenPagosDelDia;
