/**
 * Datos y reglas compartidas por el Dashboard admin (escritorio y móvil).
 *
 * Reglas de negocio que viven acá para que las dos vistas no diverjan:
 *  - Alumnos activos: snapshot diario del BI (`/kpis/diario`), no un conteo
 *    propio del frontend.
 *  - Alumnos en riesgo: críticos + altos del snapshot de churn. Si el modelo
 *    no tiene datos reales (0) o la consulta falla, se devuelve null y la UI
 *    muestra n/d + "pendiente de reentrenar"; nunca un número inventado.
 *  - Conversión: sólo se publica con una base de 5 alumnos de prueba.
 *  - Ocupación: asistencia real sobre cupo de clases pasadas. Se deriva del
 *    snapshot mensual (asistencia real / reservas × reservas / cupo), sin
 *    mezclar reservas con asistencia en el texto.
 */
import { useCallback, useEffect, useState } from 'react';
import api from '../../services/api';
import { fechaSolaAInstante, hoyChileStr } from '../../utils/fecha';

const MIN_BASE_CONVERSION = 5;
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
        diario: null, churn: null, mensual: null, periodo: null, caja: null,
    });
    const [errores, setErrores] = useState({});
    const [cargando, setCargando] = useState(true);

    const cargar = useCallback(async () => {
        setCargando(true);
        const [diarioRes, churnRes, periodosRes, cajaRes] = await Promise.allSettled([
            cargarUltimoDiario(),
            api.get('/api/v1/kpis/churn'),
            api.get('/api/v1/kpis/mensual/periodos'),
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

        let periodo = null;
        let mensual = null;
        if (periodosRes.status === 'fulfilled') {
            const cerrados = (periodosRes.value.data?.periodos || []).filter((p) => !p.parcial);
            periodo = cerrados.length ? cerrados[cerrados.length - 1] : null;
            if (periodo) {
                try {
                    const rMes = await api.get('/api/v1/kpis/mensual', {
                        params: { year: periodo.year, month: periodo.month },
                    });
                    mensual = rMes.data;
                } catch (error) {
                    errs.mensual = motivoError(error);
                }
            }
        } else {
            errs.mensual = motivoError(periodosRes.reason);
        }

        setDatos({ diario, churn, mensual, periodo, caja });
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

    const baseConversion = numOrNull(datos.mensual?.alumnos_prueba);
    const conversionConBase = baseConversion !== null && baseConversion >= MIN_BASE_CONVERSION;
    const conversionRate = conversionConBase ? numOrNull(datos.mensual?.conversion_rate) : null;
    const conversionHint = conversionConBase
        ? `Base de ${baseConversion} alumnos`
        : `n/d · base de ${baseConversion ?? 'n/d'}, mínimo ${MIN_BASE_CONVERSION}`;

    const asistenciaReal = numOrNull(datos.mensual?.asistencia_promedio);
    const reservasSobreCupo = numOrNull(datos.mensual?.ocupacion_promedio);
    // asistencia real / reservas × reservas / cupo = asistencia real / cupo.
    const ocupacionReal = asistenciaReal !== null && reservasSobreCupo !== null
        ? Math.round(((asistenciaReal * reservasSobreCupo) / 100) * 10) / 10
        : null;

    const periodoTexto = datos.periodo
        ? `${MESES_LARGOS[datos.periodo.month - 1]} ${datos.periodo.year}`
        : null;

    return {
        ...datos,
        cargando,
        errores,
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
    };
}

export default useResumenAdmin;

