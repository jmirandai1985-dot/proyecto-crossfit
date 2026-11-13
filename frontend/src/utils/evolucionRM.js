/**
 * Evolución de RMs por MOVIMIENTO — cálculos del Performance Hub (Fase 2, Bloque 2).
 *
 * POR QUÉ EXISTE: los cuadrantes del Performance Hub agrupan por CATEGORÍA y el gráfico
 * semanal mezcla movimientos distintos. Acá se compara, por cada movimiento individual,
 * el último registro contra el anterior de ESE MISMO movimiento. Eso es una mejora real:
 * a diferencia de un WOD (cuyo contenido cambia cada vez), un RM es siempre el mismo
 * ejercicio.
 *
 * H-03: la categoría/valor/unidad de un RM NO se recalculan acá; salen de `utils/rm.js`
 * (la única fuente de verdad). `hoy` se inyecta (default: calendario de Chile) para que
 * los días sin testear se puedan probar sin depender del reloj.
 */
import { inferirCategoriaRM, unidadRM, valorRM } from './rm.js';
import { fechaSolaAInstante, hoyChileStr } from './fecha.js';
import { pctProgresoNivel } from './progresoNivel.js';

const MS_DIA = 24 * 60 * 60 * 1000;

/**
 * Días enteros entre dos fechas 'YYYY-MM-DD', ancladas a MEDIODÍA UTC (misma regla que
 * `fmtFechaCortaChile`) para que la zona horaria del navegador no las corra un día.
 * Devuelve `null` si alguna fecha es ilegible.
 */
export function diasEntre(fechaDesde, fechaHasta) {
    const a = fechaSolaAInstante(fechaDesde);
    const b = fechaSolaAInstante(fechaHasta);
    if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
    return Math.max(0, Math.round((b.getTime() - a.getTime()) / MS_DIA));
}

/**
 * Nombre de un movimiento normalizado para comparar pares conocidos: minúsculas y sin la
 * aclaración entre paréntesis ("Back Squat (Sentadilla Trasera)" → "back squat").
 */
export function nombreComparable(nombre) {
    return String(nombre || '')
        .toLowerCase()
        .replace(/\s*\([^)]*\)/g, '')
        .trim();
}

// Pares de movimientos que se comparan en el tip gris ("comparación"). Hardcodeados a
// propósito: son las relaciones de fuerza que más miran los coaches; no hace falta tabla.
const PARES_COMPARACION = [
    ['Back Squat', 'Front Squat'],
    ['Snatch', 'Clean'],
    ['Deadlift', 'Back Squat'],
];

/**
 * Agrupa el historial de RMs por `movimiento_id` y devuelve, por movimiento, el resumen
 * para la sección "Evolución por movimiento". Orden: por fecha del último registro, el más
 * reciente primero (los que no tienen fecha legible quedan al final).
 */
export function evolucionPorMovimiento(registros, hoyStr = hoyChileStr()) {
    const grupos = new Map();
    (registros || []).forEach((rm) => {
        const id = rm?.movimiento_id;
        if (id === null || id === undefined) return;
        if (!grupos.has(id)) grupos.set(id, []);
        grupos.get(id).push(rm);
    });

    const resumenes = [];
    grupos.forEach((registrosMov, movimientoId) => {
        const ordenados = registrosMov.slice().sort((a, b) => {
            const ta = a?.fecha ? fechaSolaAInstante(a.fecha).getTime() : NaN;
            const tb = b?.fecha ? fechaSolaAInstante(b.fecha).getTime() : NaN;
            return (Number.isNaN(ta) ? Infinity : ta) - (Number.isNaN(tb) ? Infinity : tb);
        });

        const ultimo = ordenados[ordenados.length - 1];
        const penultimo = ordenados.length >= 2 ? ordenados[ordenados.length - 2] : null;
        const valores = ordenados.map(valorRM);
        const maximo = valores.length ? Math.max(...valores) : null;

        const valorActual = valorRM(ultimo);
        const valorAnterior = penultimo ? valorRM(penultimo) : null;
        // % de mejora contra el registro anterior de ESE MISMO movimiento; null cuando no
        // hay registro previo (el movimiento se lista igual, como "primera marca").
        const pctCambio = valorAnterior
            ? ((valorActual - valorAnterior) / valorAnterior) * 100
            : null;

        // Último PR: el registro más reciente cuyo valor iguala el máximo histórico. No es
        // lo mismo que `ultimo`: si hoy levantó menos que su mejor marca, el PR quedó en un
        // registro anterior (y los días "estancado" se cuentan desde ese PR, no desde hoy).
        const ultimoPR = [...ordenados].reverse().find((r) => valorRM(r) === maximo) || ultimo;
        const diasDesdePR = ultimoPR?.fecha ? diasEntre(ultimoPR.fecha, hoyStr) : null;

        // Últimos 6 registros (cronológico ascendente) para las reglas nuevas de tips
        // (meseta, racha, desaceleración). `ultimos3` se mantiene igual porque lo usa
        // el mini gráfico del tip "objetivo".
        const ultimos6 = ordenados.slice(-6).map((r) => ({
            fecha: r?.fecha || null,
            valor: valorRM(r),
        }));

        // Últimos 3 registros (cronológico ascendente) para el mini gráfico del tip
        // "objetivo": valor + % respecto al registro actual (el actual es el 100%).
        const ultimos3 = ultimos6.slice(-3).map((punto) => ({
            fecha: punto.fecha,
            valor: punto.valor,
            pct: valorActual ? Math.round((punto.valor / valorActual) * 100) : null,
        }));

        resumenes.push({
            movimiento_id: movimientoId,
            movimiento_nombre: ultimo?.movimiento_nombre || '',
            categoria: inferirCategoriaRM(ultimo),
            valorActual,
            valorAnterior,
            valorMaximo: maximo,
            pctCambio,
            esPR: maximo !== null && valorActual === maximo,
            diasSinTestear: ultimo?.fecha ? diasEntre(ultimo.fecha, hoyStr) : null,
            diasDesdePR,
            registros: ordenados.length,
            ultimaFecha: ultimo?.fecha || null,
            unidad: unidadRM(ultimo),
            ultimos3,
            ultimos6,
        });
    });

    resumenes.sort((a, b) => {
        const ta = a.ultimaFecha ? fechaSolaAInstante(a.ultimaFecha).getTime() : NaN;
        const tb = b.ultimaFecha ? fechaSolaAInstante(b.ultimaFecha).getTime() : NaN;
        return (Number.isNaN(tb) ? -Infinity : tb) - (Number.isNaN(ta) ? -Infinity : ta);
    });

    return resumenes;
}

// ── Reglas de los tips (TODO calculado con el histórico; nada de azar/IA) ────
// Cardio/metabólico se excluyen de TODOS los tips (decisión cerrada 05/11): no se
// comparan por intensidad y no tienen nivel de fuerza/gimnasia. Antes la exclusión
// vivía solo en `objetivosSugeridos`; ahora también aplica acá.
const CATEGORIAS_CON_TIPS = new Set(['fuerza', 'gimnastico']);

const MESETA_MIN_TESTS = 3;           // 3 tests seguidos con el mismo RM
const MESETA_MIN_DIAS = 21;           // ...repartidos en al menos 3 semanas
const SALTO_MIN_PCT = 10;             // +10% entre dos tests...
const SALTO_MAX_DIAS = 14;            // ...en 14 días o menos = salto riesgoso
const RACHA_MIN_TESTS = 3;            // 3 tests seguidos mejorando (aunque sea poco)
const DESACELERACION_MAX_RATIO = 0.6; // la mejora nueva es <=60% de la anterior
const NIVEL_CERCA_PCT = 90;           // >=90% del tramo al siguiente nivel

const numero = (valor) => String(Number(Number(valor).toFixed(2)));
const conUnidad = (valor, unidad) => {
    // "1 rep" (singular) en gimnasia; el resto de unidades no cambia.
    const textoUnidad = unidad === 'reps' && Number(valor) === 1 ? 'rep' : unidad;
    return `${numero(valor)}${textoUnidad ? ` ${textoUnidad}` : ''}`;
};
const esElegible = (r) => Boolean(r) && CATEGORIAS_CON_TIPS.has(r.categoria);
const elegibles = (resumenes) => (resumenes || []).filter(esElegible);

// Serie cronológica ascendente del movimiento. `ultimos6` (nuevo) permite ver una
// meseta/racha más larga; si un resumen viejo no lo trae, se usa `ultimos3`.
function serie(resumen) {
    const puntos = (resumen?.ultimos6?.length ? resumen.ultimos6 : resumen?.ultimos3) || [];
    return puntos
        .map((p) => ({ fecha: p?.fecha || null, valor: Number(p?.valor) }))
        .filter((p) => Number.isFinite(p.valor));
}

const mismoValor = (a, b) => Math.abs(a - b) < 1e-9;

// Cuántos tests FINALES consecutivos quedaron en el mismo valor.
function rachaIgualFinal(puntos) {
    let cantidad = 1;
    for (let i = puntos.length - 1; i > 0; i--) {
        if (!mismoValor(puntos[i].valor, puntos[i - 1].valor)) break;
        cantidad++;
    }
    return puntos.length ? cantidad : 0;
}

// Cuántos tests FINALES consecutivos mejoraron (estrictamente) respecto del anterior.
function rachaMejoraFinal(puntos) {
    let cantidad = 1;
    for (let i = puntos.length - 1; i > 0; i--) {
        if (!(puntos[i].valor > puntos[i - 1].valor)) break;
        cantidad++;
    }
    return puntos.length ? cantidad : 0;
}

// Días entre el primero y el último test de la racha final de `cantidad` tests.
function diasDeRacha(puntos, cantidad) {
    if (cantidad < 2 || puntos.length < cantidad) return null;
    const desde = puntos[puntos.length - cantidad]?.fecha;
    const hasta = puntos[puntos.length - 1]?.fecha;
    if (!desde || !hasta) return null;
    return diasEntre(desde, hasta);
}

// Detalle de nivel por movimiento. El panel inyecta `nivel_fuerza`/`nivel_gimnastico`
// con el MISMO objeto de `/nivel-general` (nivel, siguiente_nivel, umbrales y
// valor_faltante). También se acepta el detalle aplanado para no atar el util al caller.
function nivelDetalleDe(resumen) {
    const deFuerza = resumen?.nivel_fuerza;
    const deGimnasia = resumen?.nivel_gimnastico;
    const objeto = (v) => v && typeof v === 'object';
    if (resumen?.categoria === 'gimnastico' && objeto(deGimnasia)) return deGimnasia;
    if (objeto(deFuerza)) return deFuerza;
    if (objeto(deGimnasia)) return deGimnasia;
    if (resumen && resumen.nivel
        && (resumen.umbral_actual != null || resumen.umbral_siguiente != null)) {
        return resumen;
    }
    return null;
}

/**
 * Tips de la sección "Para ti", derivados de los resúmenes de `evolucionPorMovimiento`.
 *
 * Todo es RULE-BASED sobre datos reales del histórico (cero texto genérico y cero IA):
 *  - riesgo (rojo):      salto >= +10% entre dos tests separados por <= 14 días.
 *  - nivel (azul):       a >=90% del tramo para el siguiente nivel de fuerza/gimnasia
 *                        (`nivel_fuerza`/`nivel_gimnastico` del detalle de nivel).
 *  - racha (verde):      3+ tests seguidos mejorando, aunque la mejora sea chica.
 *  - meseta (amarillo):  3+ tests seguidos con el MISMO RM en >= 21 días.
 *  - desaceleracion:     la última mejora es <=60% de la anterior (ambas positivas).
 *  - logro (verde):      el movimiento con mayor % de mejora (> 0).
 *  - alerta (naranja):   el movimiento con más días sin testear (> 30, con 2+ tests).
 *  - comparacion (gris): un par conocido cuyos % de mejora difieren en más de 2x.
 *
 * Sólo fuerza/gimnástico: cardio/metabólico se excluyen (decisión 05/11). Cada tipo
 * aparece como máximo una vez y sólo si hay datos que lo justifiquen.
 */
export function tipsEvolucion(resumenes) {
    const tips = [];
    const candidatos = elegibles(resumenes);
    const conSerie = candidatos
        .map((r) => ({ r, puntos: serie(r) }))
        .filter((x) => x.puntos.length >= 2);

    // 1) Salto peligrosamente rápido (lo primero: es el único tip de seguridad).
    const salto = conSerie
        .map(({ r, puntos }) => {
            const anterior = puntos[puntos.length - 2];
            const ultimo = puntos[puntos.length - 1];
            const pct = anterior.valor > 0
                ? ((ultimo.valor - anterior.valor) / anterior.valor) * 100
                : null;
            const dias = anterior.fecha && ultimo.fecha
                ? diasEntre(anterior.fecha, ultimo.fecha)
                : null;
            return { r, anterior, ultimo, pct, dias };
        })
        .find((x) => x.pct !== null && x.pct >= SALTO_MIN_PCT
            && x.dias !== null && x.dias <= SALTO_MAX_DIAS);
    if (salto) {
        tips.push({
            tipo: 'riesgo',
            color: 'rojo',
            icono: '🚨',
            titulo: 'Salto demasiado rápido',
            detalle: `${salto.r.movimiento_nombre} pasó de ${conUnidad(salto.anterior.valor, salto.r.unidad)} a ${conUnidad(salto.ultimo.valor, salto.r.unidad)} en ${salto.dias} días (+${salto.pct.toFixed(1)}%). Un salto así no le da tiempo al tejido para adaptarse: repite el peso o sube en pasos más chicos.`,
            movimientoId: salto.r.movimiento_id,
        });
    }

    // 2) A punto de subir de nivel (detalle real de nivel por movimiento).
    const cercaDeNivel = candidatos
        .map((r) => ({ r, info: nivelDetalleDe(r) }))
        .filter(({ info }) => info && info.nivel && info.nivel !== 'Sin datos'
            && info.siguiente_nivel
            && Number.isFinite(Number(info.umbral_actual))
            && Number.isFinite(Number(info.umbral_siguiente))
            && Number(info.umbral_siguiente) > Number(info.umbral_actual))
        .map(({ r, info }) => ({
            r,
            info,
            // El nivel se calcula sobre el MEJOR RM histórico (no sobre la última
            // marca si bajó): se usa `valorMaximo` para medir el tramo real.
            pct: pctProgresoNivel(r.valorMaximo ?? r.valorActual, info),
            falta: Number(info.valor_faltante),
        }))
        .filter((x) => x.pct >= NIVEL_CERCA_PCT)
        .sort((a, b) => b.pct - a.pct || a.falta - b.falta)[0];
    if (cercaDeNivel) {
        const { r, info, pct, falta } = cercaDeNivel;
        const faltaTexto = Number.isFinite(falta) && falta > 0
            ? `Estás a ${conUnidad(falta, r.unidad)} de`
            : 'Estás muy cerca de';
        tips.push({
            tipo: 'nivel',
            color: 'azul',
            icono: '⬆️',
            titulo: 'A punto de subir de nivel',
            detalle: `${faltaTexto} pasar de ${info.nivel} a ${info.siguiente_nivel} en ${r.movimiento_nombre} (${Math.round(pct)}% del tramo recorrido).`,
            movimientoId: r.movimiento_id,
        });
    }

    // 3) Racha de consistencia: tests seguidos mejorando (aunque sea 0.5 kg/1 rep).
    const racha = conSerie
        .map(({ r, puntos }) => ({ r, puntos, tests: rachaMejoraFinal(puntos) }))
        .find((x) => x.tests >= RACHA_MIN_TESTS);
    if (racha) {
        const serieTexto = racha.puntos.slice(-racha.tests)
            .map((p) => numero(p.valor)).join(' → ');
        tips.push({
            tipo: 'racha',
            color: 'verde',
            icono: '🔥',
            titulo: 'Racha en ascenso',
            detalle: `Has mejorado ${racha.tests} tests seguidos en ${racha.r.movimiento_nombre}: ${serieTexto} ${racha.r.unidad}. La constancia vale más que un salto aislado: mantén el plan.`,
            movimientoId: racha.r.movimiento_id,
        });
    }

    // 4) Meseta real: varios tests seguidos sin mover el RM, repartidos en el tiempo.
    const meseta = conSerie
        .map(({ r, puntos }) => {
            const tests = rachaIgualFinal(puntos);
            return { r, puntos, tests, dias: diasDeRacha(puntos, tests) };
        })
        .find((x) => x.tests >= MESETA_MIN_TESTS
            && x.dias !== null && x.dias >= MESETA_MIN_DIAS);
    if (meseta) {
        const ultimo = meseta.puntos[meseta.puntos.length - 1];
        tips.push({
            tipo: 'meseta',
            color: 'amarillo',
            icono: '⏸️',
            titulo: 'Meseta real',
            detalle: `${meseta.r.movimiento_nombre} lleva ${meseta.tests} tests seguidos en ${conUnidad(ultimo.valor, meseta.r.unidad)} (${meseta.dias} días sin cambio). Cambia el estímulo (tempo, pausas, volumen) y vuelve a testear en 3-4 semanas.`,
            movimientoId: meseta.r.movimiento_id,
        });
    }

    // 5) Desaceleración: la mejora por test se está achicando (ambas positivas).
    const desaceleracion = conSerie
        .map(({ r, puntos }) => {
            if (puntos.length < 3) return null;
            const [primero, segundo, tercero] = puntos.slice(-3);
            return {
                r,
                deltaPrevio: segundo.valor - primero.valor,
                deltaUltimo: tercero.valor - segundo.valor,
            };
        })
        .filter(Boolean)
        .find((x) => x.deltaPrevio > 0 && x.deltaUltimo > 0
            && x.deltaUltimo <= x.deltaPrevio * DESACELERACION_MAX_RATIO);
    if (desaceleracion) {
        tips.push({
            tipo: 'desaceleracion',
            color: 'violeta',
            icono: '📉',
            titulo: 'El progreso se desacelera',
            detalle: `En ${desaceleracion.r.movimiento_nombre} venías subiendo ${conUnidad(desaceleracion.deltaPrevio, desaceleracion.r.unidad)} por test y el último subió ${conUnidad(desaceleracion.deltaUltimo, desaceleracion.r.unidad)}. Revisa descanso y volumen antes de forzar otro PR.`,
            movimientoId: desaceleracion.r.movimiento_id,
        });
    }

    const mejor = candidatos
        .filter((r) => r.pctCambio !== null && r.pctCambio > 0)
        .reduce((acc, r) => (!acc || r.pctCambio > acc.pctCambio ? r : acc), null);
    if (mejor) {
        tips.push({
            tipo: 'logro',
            color: 'verde',
            icono: '🚀',
            titulo: 'Tu mayor mejora',
            detalle: `${mejor.movimiento_nombre} subió ${mejor.pctCambio.toFixed(1)}% respecto a tu registro anterior.`,
            movimientoId: mejor.movimiento_id,
        });
    }

    const sinTestear = candidatos
        .filter((r) => r.diasSinTestear !== null && r.diasSinTestear > 30 && r.registros >= 2)
        .reduce((acc, r) => (!acc || r.diasSinTestear > acc.diasSinTestear ? r : acc), null);
    if (sinTestear) {
        tips.push({
            tipo: 'alerta',
            color: 'naranja',
            icono: '⚠️',
            titulo: 'Hace tiempo que no lo testeas',
            detalle: `Llevas ${sinTestear.diasSinTestear} días sin registrar ${sinTestear.movimiento_nombre}.`,
            movimientoId: sinTestear.movimiento_id,
        });
    }

    PARES_COMPARACION.forEach(([nombreIzq, nombreDer]) => {
        const a = candidatos.find((r) => nombreComparable(r.movimiento_nombre) === nombreComparable(nombreIzq));
        const b = candidatos.find((r) => nombreComparable(r.movimiento_nombre) === nombreComparable(nombreDer));
        if (!a || !b) return;
        if (a.pctCambio === null || b.pctCambio === null) return;
        if (!(a.pctCambio > 0 && b.pctCambio > 0)) return;
        const mayor = a.pctCambio >= b.pctCambio ? a : b;
        const menor = a.pctCambio >= b.pctCambio ? b : a;
        if (mayor.pctCambio > menor.pctCambio * 2) {
            tips.push({
                tipo: 'comparacion',
                color: 'gris',
                icono: '📊',
                titulo: 'Un par desparejo',
                detalle: `${mayor.movimiento_nombre} avanzó ${mayor.pctCambio.toFixed(1)}% y ${menor.movimiento_nombre} solo ${menor.pctCambio.toFixed(1)}%. Revisa qué está frenando a ${menor.movimiento_nombre}.`,
                movimientoId: menor.movimiento_id,
            });
        }
    });

    return tips;
}

// Ventana sugerida para reintentar el máximo (coherente con el umbral de 30 días que ya
// usa el badge "hace tiempo que no lo testeas" en "Evolución por movimiento").
const VENTANA_REINTENTO = 'en 3-4 semanas aprox.';

// Redondea un kg a 0.5 kg (el salto real de disco más chico del box): 78.75 → 79.0,
// 89.25 → 89.5. `Math.round(n * 2) / 2` redondea hacia el 0.5 más cercano.
function redondearMedioKg(n) {
    return Math.round(n * 2) / 2;
}

// Plan de progresión de FUERZA (kg): periodización estándar de 3 semanas
// (volumen → intensidad → intento de PR), con el peso exacto de cada bloque.
function planFuerza(valorActual, unidad) {
    const v = Number(valorActual) || 0;
    const v75 = redondearMedioKg(v * 0.75);
    const v80 = redondearMedioKg(v * 0.80);
    const v85 = redondearMedioKg(v * 0.85);
    const v90 = redondearMedioKg(v * 0.90);
    return [
        {
            texto: `2 semanas de volumen: 3-4 series x 5-6 reps al 75-80% (${v75}-${v80} ${unidad}), 2 veces por semana.`,
            valor: `${v75}-${v80} ${unidad}`,
        },
        {
            texto: `1 semana de intensidad: 3 series x 2-3 reps al 85-90% (${v85}-${v90} ${unidad}).`,
            valor: `${v85}-${v90} ${unidad}`,
        },
        {
            texto: `Intentar el nuevo objetivo: ${v + 2.5} ${unidad}.`,
            valor: `${v + 2.5} ${unidad}`,
        },
    ];
}

// Plan de progresión GIMNÁSTICO (reps): doble progresión (volumen submáximo → intento).
function planGimnastico(valorActual, unidad) {
    const v = Number(valorActual) || 0;
    // Redondeo hacia abajo (floor): nunca se prescribe más de lo que el alumno ya hace.
    const min = Math.floor(v * 0.70);
    const max = Math.floor(v * 0.80);
    return [
        {
            texto: `2-3 sesiones de volumen submáximo: series al 70-80% (${min}-${max} ${unidad}).`,
            valor: `${min}-${max} ${unidad}`,
        },
        {
            texto: `Intentar el nuevo objetivo: ${v + 1} ${unidad}.`,
            valor: `${v + 1} ${unidad}`,
        },
    ];
}

/**
 * Objetivos sugeridos para la sección "Para ti" (tip "tu RM es tu 100%").
 *
 * Por cada movimiento de fuerza/gimnástico con RM registrado se sugiere el próximo salto:
 *   - fuerza (kg)       → RM actual + 2.5 kg
 *   - gimnastico (reps) → RM actual + 1 rep
 * Incrementos FIJOS (no %): son los saltos reales de disco/rep que usan los coaches.
 * Cardio/metabólico se excluyen a propósito (decisión cerrada 05/11): no tienen
 * comparación de intensidad ni "próximo objetivo", solo guardan el RM normal.
 *
 * Cada objetivo además trae `planProgresion` (2-3 pasos con el peso/reps EXACTO de cada
 * bloque, calculado a partir del RM actual) y `ventanaReintento` ("en 3-4 semanas aprox."),
 * coherente con el umbral de 30 días del badge de "Evolución por movimiento".
 *
 * Recibe el MISMO array que devuelve `evolucionPorMovimiento` (que ya trae `diasDesdePR`
 * y `ultimos3`); devuelve un objetivo por movimiento, en el mismo orden (más reciente
 * primero).
 */
export function objetivosSugeridos(resumenes) {
    return (resumenes || [])
        .filter((r) => (r.categoria === 'fuerza' || r.categoria === 'gimnastico') && r.valorActual)
        .map((r) => {
            const incremento = r.categoria === 'gimnastico' ? 1 : 2.5;
            const planProgresion = r.categoria === 'gimnastico'
                ? planGimnastico(r.valorActual, r.unidad)
                : planFuerza(r.valorActual, r.unidad);
            return {
                movimiento_id: r.movimiento_id,
                movimiento_nombre: r.movimiento_nombre,
                categoria: r.categoria,
                valorActual: r.valorActual,
                valorMaximo: r.valorMaximo,
                esPR: r.esPR,
                objetivoSugerido: r.valorActual + incremento,
                incremento,
                unidad: r.unidad,
                diasDesdePR: r.diasDesdePR,
                diasSinTestear: r.diasSinTestear,
                ultimos3: r.ultimos3 || [],
                planProgresion,
                ventanaReintento: VENTANA_REINTENTO,
            };
        });
}

