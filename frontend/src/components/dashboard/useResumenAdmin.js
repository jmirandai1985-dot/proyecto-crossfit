/**
 * Datos y reglas compartidas por el Dashboard admin (escritorio y móvil).
 *
 * Reglas de negocio que viven acá para que las dos vistas no diverjan:
 *  - Alumnos activos: `/admin/alumnos-activos` (suscripción vigente HOY, día
 *    chileno). Es la MISMA base que usa `/kpis/churn` para `total_activos`, así
 *    que el riesgo es por construcción un subconjunto de los activos.
 *  - Alumnos en riesgo: `criticos_activos + altos_activos` de `/kpis/churn`
 *    (predicciones intersectadas con los alumnos activos). La lista de
 *    Fidelización sigue mostrando todas las predicciones del box; el CONTADOR
 *    de la tarjeta es el de activos. Con 0 predicciones el modelo todavía no
 *    tiene datos y la UI dice "pendiente de reentrenar".
 *  - Conversión, asistencia real y ocupación: MES EN CURSO (hoy en Chile),
 *    calculado EN VIVO por `GET /kpis/mes-en-curso` — el mes en curso todavía no
 *    tiene fila en `monthly_kpis` (el job BI publica al cierre).
 *  - Conversión: SIN mínimo de base. Se publica el porcentaje y el conteo
 *    ("2 de 3 pagaron") con los alumnos que empezaron prueba este mes. Con 0
 *    alumnos en prueba se publica 0% y el hint lo explica.
 *  - OCUPACIÓN = asistencias marcadas / CUPO de las clases realizadas
 *    (`metricas_service.ocupacion_promedio`). ASISTENCIA REAL = asistencias
 *    marcadas / RESERVAS CONFIRMADAS de esas mismas clases
 *    (`kpis_populate.calcular_asistencia_mes`). Son dos denominadores distintos:
 *    ocupación mide uso del cupo; asistencia real mide cumplimiento de reservas.
 *    El panel de ocupación usa exactamente la misma fórmula que la tarjeta.
 *  - Ingreso del mes, Ventas Bazar, Membresías del mes y MRR: `pagos` aprobados
 *    del mes (misma fuente que "Pagos del día") y membresías activas por plan.
 *    NUNCA `transacciones_financieras` (esa es la caja). Los planes de prueba
 *    (nombre con "prueba"/"test"/"trial", incluido el de $1.500) NO son
 *    membresías: quedan fuera del ranking y del MRR.
 */
import { useCallback, useEffect, useState } from 'react';
import api from '../../services/api';
import { hoyChileStr } from '../../utils/fecha';
import { resumenPagosDelDia } from '../../utils/pagosDelDia';
import {
    useAlumnosActivosResumen, useIngresoMes, useMembresiasMes, useMrr,
    usePagosDelDia,
} from '../../hooks/queries';

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

export function useResumenAdmin() {
    // `churn` y `mesCurso` son lecturas EN VIVO: el snapshot diario del BI ya no
    // se usa para "Alumnos activos" (ese número sale de `/reportes/`, que cuenta
    // las suscripciones vigentes hoy) ni para la asistencia del día.
    const [datos, setDatos] = useState({ churn: null, mesCurso: null });
    const [errores, setErrores] = useState({});
    const [cargando, setCargando] = useState(true);

    // ── Tarjetas de NEGOCIO del mes: todo desde `pagos` ──────────────────────
    // Ingreso del mes + Ventas Bazar, ranking de membresías y MRR comparten la
    // MISMA fuente que "Pagos del día". Nada de `transacciones_financieras`.
    const alumnosActivosQ = useAlumnosActivosResumen(10);
    const ingresoMesQ = useIngresoMes();
    const membresiasMesQ = useMembresiasMes();
    const mrrQ = useMrr();

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
        const [churnRes, mesRes] = await Promise.allSettled([
            // Churn EN VIVO: el conteo sale de `predictions_churn` (la lectura que
            // ya usa Fidelización), no del snapshot diario del BI.
            api.get('/api/v1/kpis/churn'),
            // MES EN CURSO calculado en vivo (embudo de prueba→plan, asistencia real y
            // ocupación del mes a la fecha). NO se pide `/kpis/mensual`: el mes en curso
            // todavía no tiene fila en `monthly_kpis` y respondería 404.
            api.get('/api/v1/kpis/mes-en-curso'),
        ]);

        const errs = {};
        const churn = churnRes.status === 'fulfilled' ? churnRes.value.data : null;
        if (churnRes.status === 'rejected') errs.churn = motivoError(churnRes.reason);

        // La clave del error sigue siendo `mensual`: es la que leen las tres tarjetas
        // del bloque mensual (Conversión, Asistencia real, Ocupación).
        const mesCurso = mesRes.status === 'fulfilled' ? mesRes.value.data : null;
        if (mesRes.status === 'rejected') errs.mensual = motivoError(mesRes.reason);

        setDatos({ churn, mesCurso });
        setErrores(errs);
        setCargando(false);
    }, []);

    useEffect(() => { cargar(); }, [cargar]);

    // "Alumnos activos" EN VIVO: suscripción vigente HOY (misma base que el
    // riesgo). El total y la lista salen del MISMO endpoint, así que la tarjeta
    // y su panel no pueden discrepar.
    const alumnosActivos = numOrNull(alumnosActivosQ.data?.total);
    const alumnosActivosLista = Array.isArray(alumnosActivosQ.data?.alumnos)
        ? alumnosActivosQ.data.alumnos : [];
    const alumnosActivosError = alumnosActivosQ.error
        ? motivoError(alumnosActivosQ.error) : '';

    // Riesgo EN VIVO: críticos + altos de las predicciones INTERSECTADAS con
    // los alumnos activos (`criticos_activos`/`altos_activos` de `/kpis/churn`).
    // Así el riesgo NUNCA supera a los activos. Con 0 predicciones el modelo
    // todavía no tiene datos (la tarjeta dice "pendiente de reentrenar"); con
    // predicciones y 0 en riesgo se muestra 0, que es un dato real.
    const criticos = numOrNull(datos.churn?.criticos_activos);
    const altos = numOrNull(datos.churn?.altos_activos);
    const totalPredicciones = numOrNull(datos.churn?.total);
    const alumnosRiesgo = criticos === null || altos === null
        ? null : criticos + altos;
    const riesgoPendiente = alumnosRiesgo === null
        || totalPredicciones === null || totalPredicciones === 0;

    // ── Conversión prueba→plan del MES EN CURSO ──────────────────────────────
    // SIN mínimo de base: con 1 alumno en prueba ya se publica (antes se ocultaba
    // hasta llegar a 5 y el admin veía "n/d" aunque hubiera datos). El texto dice
    // SIEMPRE el conteo ("2 de 3 pagaron") además del porcentaje.
    const baseConversion = numOrNull(datos.mesCurso?.alumnos_prueba);
    const rateCrudo = numOrNull(datos.mesCurso?.conversion_rate);
    // Con 0 alumnos en prueba no hay división: el mes se publica en 0% (y el
    // hint dice "sin alumnos en prueba") en vez de un "n/d" que el admin no
    // puede distinguir de un endpoint caído.
    const conversionRate = baseConversion === 0 ? 0 : rateCrudo;
    const planComprado = numOrNull(datos.mesCurso?.alumnos_plan_comprado);
    const clasePrueba = numOrNull(datos.mesCurso?.alumnos_clase_prueba_ejecutada);
    const conversionHint = baseConversion === null
        ? 'Sin datos del mes en curso'
        : baseConversion === 0
            ? 'Sin alumnos en prueba este mes'
            : `${planComprado ?? 0} de ${baseConversion} pagaron plan`
                + ` · ${clasePrueba ?? 0} hicieron clase de prueba`;

    // Asistencia real del mes: reservas confirmadas de clases realizadas CON
    // asistencia marcada / reservas confirmadas de esas mismas clases
    // (`kpis_populate.calcular_asistencia_mes`, la MISMA definición del BI).
    const asistenciaReal = numOrNull(datos.mesCurso?.asistencia_promedio);
    // Ocupación del mes: asistencias REALES / cupos de las clases realizadas
    // (`metricas_service.ocupacion_promedio`). Antes se multiplicaba por la tasa
    // de asistencia y el número quedaba compuesto (marcado como pendiente en el
    // docstring). Ahora la tarjeta y el panel por clase miden lo mismo:
    // asistencia real sobre cupo.
    const ocupacionReal = numOrNull(datos.mesCurso?.ocupacion_promedio);

    // Período de las tarjetas: el MES EN CURSO en Chile (no el último mes cerrado).
    const hoy = hoyChileStr();
    const [anioHoy, mesHoy] = String(hoy).split('-').map(Number);
    const periodoTexto = Number.isFinite(mesHoy) && mesHoy >= 1 && mesHoy <= 12
        ? `${MESES_LARGOS[mesHoy - 1]} ${anioHoy}`
        : null;

    const pagosDiaError = pagosDiaQ.error ? motivoError(pagosDiaQ.error) : '';

    // ── Negocio del mes (fuente: `pagos` aprobados + membresías activas) ─────
    const ingresoMes = ingresoMesQ.data ?? null;
    const membresiasMes = membresiasMesQ.data ?? null;
    const mrrResumen = mrrQ.data ?? null;
    const ventasBazar = ingresoMes ? numOrNull(ingresoMes.total_bazar_clp) : null;
    // Pedidos del Bazar dentro de los cobros del mes: el panel/la tarjeta lo
    // muestran junto al monto, sin pedir otra consulta.
    const ventasBazarPedidos = Array.isArray(ingresoMes?.pagos)
        ? ingresoMes.pagos.filter((p) => p?.origen === 'bazar').length
        : null;

    const ingresoMesError = ingresoMesQ.error ? motivoError(ingresoMesQ.error) : '';
    const membresiasMesError = membresiasMesQ.error
        ? motivoError(membresiasMesQ.error) : '';
    const mrrError = mrrQ.error ? motivoError(mrrQ.error) : '';

    const erroresFinales = { ...errores };
    // `diario` se conserva como clave porque la vista móvil ya la lee para
    // "Alumnos activos"; ahora el motivo viene de `/admin/alumnos-activos`.
    if (alumnosActivosError) erroresFinales.diario = alumnosActivosError;
    if (pagosDiaError) erroresFinales.pagosDia = pagosDiaError;
    if (ingresoMesError) erroresFinales.ingresoMes = ingresoMesError;
    if (membresiasMesError) erroresFinales.membresiasMes = membresiasMesError;
    if (mrrError) erroresFinales.mrr = mrrError;

    return {
        ...datos,
        cargando,
        errores: erroresFinales,
        // "Recargar" del Dashboard: refresca TODO lo que alimenta el hook. Las
        // consultas de React Query comparten caché con las pantallas que usan el
        // mismo dato, así que refrescar acá también las actualiza.
        recargar: () => {
            cargar();
            alumnosActivosQ.refetch();
            ingresoMesQ.refetch();
            membresiasMesQ.refetch();
            mrrQ.refetch();
            pagosDiaQ.refetch();
        },
        alumnosActivos,
        alumnosActivosResumen: alumnosActivosQ.data ?? null,
        alumnosActivosLista,
        alumnosActivosCargando: alumnosActivosQ.isPending,
        alumnosActivosError,
        alumnosRiesgo,
        riesgoPendiente,
        criticos,
        altos,
        baseConversion,
        planComprado,
        clasePrueba,
        conversionRate,
        conversionHint,
        asistenciaReal,
        ocupacionReal,
        periodoTexto,
        periodoAnio: anioHoy,
        periodoMes: mesHoy,
        // ── Negocio del mes ──
        ingresoMes,
        ingresoMesCargando: ingresoMesQ.isPending,
        ingresoMesError,
        membresiasMes,
        membresiasMesCargando: membresiasMesQ.isPending,
        membresiasMesError,
        mrr: mrrResumen,
        mrrCargando: mrrQ.isPending,
        mrrError,
        ventasBazar,
        ventasBazarPedidos,
        ventasBazarCargando: ingresoMesQ.isPending,
        ventasBazarError: ingresoMesError,
        // "Ingresos de hoy" = total de los cobros que lista "Pagos del día".
        // Mientras la consulta no tiene datos se devuelve null (la tarjeta pinta
        // "n/d"), nunca un 0 que se lea como "no entró plata".
        ingresosHoy: hayPagosDia ? resumenPagosDia.totalClp : null,
        cobrosHoy: hayPagosDia ? resumenPagosDia.cantidad : null,
        pagosDiaCargando: pagosDiaQ.isPending,
    };
}

export default useResumenAdmin;

