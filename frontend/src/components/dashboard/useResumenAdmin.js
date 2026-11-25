/**
 * Datos y reglas compartidas por el Dashboard admin (escritorio y móvil).
 *
 * Reglas de negocio que viven acá para que las dos vistas no diverjan:
 *  - Alumnos activos: snapshot diario del BI (`/kpis/diario`), no un conteo
 *    propio del frontend.
 *  - Alumnos en riesgo: críticos + altos del snapshot de churn. Si el modelo
 *    no tiene datos reales (0) o la consulta falla, se devuelve null y la UI
 *    muestra n/d + "pendiente de reentrenar"; nunca un número inventado.
 *  - Conversión, asistencia real y ocupación: MES EN CURSO (hoy en Chile),
 *    calculado EN VIVO por `GET /kpis/mes-en-curso` — el mes en curso todavía no
 *    tiene fila en `monthly_kpis` (el job BI publica al cierre), y las tarjetas
 *    del Dashboard ya no muestran el mes cerrado: ése sigue en la pestaña KPIs.
 *  - Conversión: SIN mínimo de base. Se publica el porcentaje y el conteo
 *    ("2 de 3 pagaron") con los alumnos que empezaron prueba este mes.
 *  - Ocupación: se MANTIENE el cálculo que ya existía
 *    (asistencia real / reservas × ocupación). ⚠️ PENDIENTE de decisión humana:
 *    `metricas_service.ocupacion_promedio` (backend) mide asistencias reales /
 *    cupo, mientras `detallesKpi` ('bi:ocupacion') la define como reservas /
 *    cupo. No se cambia la fórmula ni la definición acá (ver reporte).
 */
import { useCallback, useEffect, useState } from 'react';
import api from '../../services/api';
import { fechaSolaAInstante, hoyChileStr } from '../../utils/fecha';
import { resumenPagosDelDia } from '../../utils/pagosDelDia';
import { usePagosDelDia } from '../../hooks/queries';

const MESES_LARGOS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

const numOrNull = (valor) => {
    if (valor === null || valor === undefined || valor === '') return null;
    const numero = Number(valor);
    return Number.isFinite(numero) ? numero : null;
};

const motivoError = (error) => error?.response?.data?.detail
    || (error?.response?.status ? `HTTP ${error.response.status}` : error?.message)
    || 'No se pudo cargar';

const restarDias = (fechaStr, dias) => new Date(
    fechaSolaAInstante(fechaStr).getTime() - (dias * 86400000),
).toISOString().slice(0, 10);

async function cargarUltimoDiario() {
    const hoy = hoyChileStr();
    let ultimoError = '';
    // El job publica AYER, pero si el día actual ya tiene fila se usa; se
    // retrocede hasta 7 días para encontrar el último snapshot disponible.
    for (let i = 0; i <= 7; i += 1) {
        const fecha = restarDias(hoy, i);
        try {
            const res = await api.get('/api/v1/kpis/diario', { params: { fecha } });
            return { data: { ...res.data, fecha: res.data?.fecha || fecha }, error: '' };
        } catch (error) {
            if (error?.response?.status !== 404) ultimoError = motivoError(error);
        }
    }
    return { data: null, error: ultimoError };
}

export function useResumenAdmin() {
    const [datos, setDatos] = useState({
        diario: null, churn: null, mesCurso: null, caja: null,
    });
    const [errores, setErrores] = useState({});
    const [cargando, setCargando] = useState(true);

    // ── "Ingresos de hoy": los MISMOS cobros de "Pagos del día" ──────────────
    // La tarjeta ya no lee la caja de `transacciones_financieras`
    // (`/finanzas/resumen-hoy`): esa tabla se quedaba en $0 cuando el webhook no
    // escribía la transacción. Ahora el valor es la suma de los cobros del día que
    // pinta la lista (membresías + Bazar). `usePagosDelDia` es el hook que usa
    // `PagosDelDia`: misma queryKey y misma caché, así que la tarjeta y el
    // desglose no pueden discrepar.
    const pagosDiaQ = usePagosDelDia();
    const resumenPagosDia = resumenPagosDelDia(pagosDiaQ.data);
    const hayPagosDia = pagosDiaQ.data != null;

    const cargar = useCallback(async () => {
        setCargando(true);
        const [diarioRes, churnRes, mesRes, cajaRes] = await Promise.allSettled([
            cargarUltimoDiario(),
            api.get('/api/v1/kpis/churn'),
            // MES EN CURSO calculado en vivo (embudo de prueba→plan, asistencia real y
            // ocupación del mes a la fecha). NO se pide `/kpis/mensual`: el mes en curso
            // todavía no tiene fila en `monthly_kpis` y respondería 404.
            api.get('/api/v1/kpis/mes-en-curso'),
            api.get('/api/v1/finanzas/resumen-hoy'),
        ]);

        const errs = {};
        const diario = diarioRes.status === 'fulfilled' ? diarioRes.value.data : null;
        if (diarioRes.status === 'fulfilled' && diarioRes.value.error) {
            errs.diario = diarioRes.value.error;
        } else if (diarioRes.status === 'rejected') {
            errs.diario = motivoError(diarioRes.reason);
        }

        const churn = churnRes.status === 'fulfilled' ? churnRes.value.data : null;
        if (churnRes.status === 'rejected') errs.churn = motivoError(churnRes.reason);

        const caja = cajaRes.status === 'fulfilled' ? cajaRes.value.data : null;
        if (cajaRes.status === 'rejected') errs.caja = motivoError(cajaRes.reason);

        // La clave del error sigue siendo `mensual`: es la que leen las tres tarjetas
        // del bloque mensual (Conversión, Asistencia real, Ocupación).
        const mesCurso = mesRes.status === 'fulfilled' ? mesRes.value.data : null;
        if (mesRes.status === 'rejected') errs.mensual = motivoError(mesRes.reason);

        setDatos({ diario, churn, mesCurso, caja });
        setErrores(errs);
        setCargando(false);
    }, []);

    useEffect(() => { cargar(); }, [cargar]);

    const alumnosActivos = numOrNull(datos.diario?.alumnos_activos);
    const asistentesHoy = numOrNull(datos.diario?.asistentes_totales);

    const criticos = numOrNull(datos.churn?.criticos);
    const altos = numOrNull(datos.churn?.altos);
    const sumaRiesgo = criticos !== null && altos !== null ? criticos + altos : null;
    // 0 = el modelo no tiene casos reales: no se publica un 0 como si fuera dato.
    const alumnosRiesgo = sumaRiesgo && sumaRiesgo > 0 ? sumaRiesgo : null;
    const riesgoPendiente = alumnosRiesgo === null;

    // ── Conversión prueba→plan del MES EN CURSO ──────────────────────────────
    // SIN mínimo de base: con 1 alumno en prueba ya se publica (antes se ocultaba
    // hasta llegar a 5 y el admin veía "n/d" aunque hubiera datos). El texto dice
    // SIEMPRE el conteo ("2 de 3 pagaron") además del porcentaje.
    const baseConversion = numOrNull(datos.mesCurso?.alumnos_prueba);
    const conversionRate = numOrNull(datos.mesCurso?.conversion_rate);
    const planComprado = numOrNull(datos.mesCurso?.alumnos_plan_comprado);
    const clasePrueba = numOrNull(datos.mesCurso?.alumnos_clase_prueba_ejecutada);
    const conversionHint = baseConversion === null
        ? 'Sin alumnos en prueba este mes'
        : `${planComprado ?? 0} de ${baseConversion} pagaron plan`
            + ` · ${clasePrueba ?? 0} hicieron clase de prueba`;

    // Asistencia real del mes: reservas confirmadas de clases realizadas CON
    // asistencia marcada / reservas confirmadas de esas mismas clases
    // (`kpis_populate.calcular_asistencia_mes`, la MISMA definición del BI).
    const asistenciaReal = numOrNull(datos.mesCurso?.asistencia_promedio);
    const reservasSobreCupo = numOrNull(datos.mesCurso?.ocupacion_promedio);
    // ⚠️ FÓRMULA SIN CAMBIOS (ver PENDIENTE en el docstring del módulo):
    // asistencia real / reservas × ocupación. El texto de la tarjeta es el mismo
    // que acompaña a este cálculo ("asistencia real / cupo").
    const ocupacionReal = asistenciaReal !== null && reservasSobreCupo !== null
        ? Math.round(((asistenciaReal * reservasSobreCupo) / 100) * 10) / 10
        : null;

    // Período de las tarjetas: el MES EN CURSO en Chile (no el último mes cerrado).
    const hoy = hoyChileStr();
    const [anioHoy, mesHoy] = String(hoy).split('-').map(Number);
    const periodoTexto = Number.isFinite(mesHoy) && mesHoy >= 1 && mesHoy <= 12
        ? `${MESES_LARGOS[mesHoy - 1]} ${anioHoy}`
        : null;

    const pagosDiaError = pagosDiaQ.error ? motivoError(pagosDiaQ.error) : '';

    return {
        ...datos,
        cargando,
        errores: pagosDiaError ? { ...errores, pagosDia: pagosDiaError } : errores,
        recargar: cargar,
        alumnosActivos,
        asistentesHoy,
        alumnosRiesgo,
        riesgoPendiente,
        criticos,
        altos,
        baseConversion,
        conversionRate,
        conversionHint,
        asistenciaReal,
        ocupacionReal,
        periodoTexto,
        // "Ingresos de hoy" = total de los cobros que lista "Pagos del día".
        // Mientras la consulta no tiene datos se devuelve null (la tarjeta pinta
        // "n/d"), nunca un 0 que se lea como "no entró plata".
        ingresosHoy: hayPagosDia ? resumenPagosDia.totalClp : null,
        cobrosHoy: hayPagosDia ? resumenPagosDia.cantidad : null,
        pagosDiaCargando: pagosDiaQ.isPending,
    };
}

export default useResumenAdmin;

