// Test aislado de los planes de LARGA DURACIÓN y de la matrícula del panel.
//   Ejecutar:  node scripts/test-planes-larga-duracion.mjs   (npm run test:planes)
//
// Sin navegador ni framework, como el resto de `scripts/test-*.mjs`:
//   1. reglas PURAS de `src/utils/planes.js` (meses, categoría, ahorro, calculadora);
//   2. CONTRATO de la fuente de `pages/admin/Planes.jsx` (panel de matrícula, tarjeta
//      unisex, toggle ilimitado, clases por mes, comparación y badge de ahorro);
//   3. CONTRATO de `pages/alumno/SolicitarPlan.jsx` (sección "Planes extendidos" y
//      línea de matrícula con el total);
//   4. hooks/keys nuevas de `hooks/queries.js` (una sola fuente de la config).
import { readFileSync } from 'node:fs';
import {
    ahorroDelPlan, creditosDesdeClasesPorMes, esPlanLargo, mesesDelPlan,
    planesComparables,
} from '../src/utils/planes.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const planesSrc = leer('../src/pages/admin/Planes.jsx');
const solicitarSrc = leer('../src/pages/alumno/SolicitarPlan.jsx');
const queriesSrc = leer('../src/hooks/queries.js');

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    const a = JSON.stringify(obtenido);
    const b = JSON.stringify(esperado);
    if (a === b) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${b} · obtenido: ${a})`);
    }
};
const ok = (cond, msg) => eq(Boolean(cond), true, msg);
const coincide = (fuente, patron, msg) => ok(patron.test(fuente), msg);

const plan = (extra) => ({
    genero: null, es_comercial: true, precio_clp: 200000, activo: true,
    duracion_dias: 180, ...extra,
});
const mensual = { genero: 'masculino', es_comercial: true, precio_clp: 60000, activo: true, duracion_dias: 30 };

console.log('== 1. Meses del plan ==');
eq(mesesDelPlan(180), 6, '180 días = 6 meses');
eq(mesesDelPlan(30), 1, '30 días = 1 mes');
eq(mesesDelPlan(90), 3, '90 días = 3 meses');
eq(mesesDelPlan(45), 2, '45 días redondea a 2 meses');
eq(mesesDelPlan(0), 1, 'duración 0/ausente = 1 mes (nunca 0)');
eq(mesesDelPlan(null), 1, 'null = 1 mes');

console.log('\n== 2. Qué es un plan de larga duración (genero NULL) ==');
ok(esPlanLargo(plan()), 'unisex + comercial + con precio + activo -> sí');
ok(!esPlanLargo(plan({ genero: 'masculino' })), 'con género -> no (va en su tarjeta)');
ok(!esPlanLargo(plan({ precio_clp: 0 })), 'el plan "Prueba" (gratis) -> no');
ok(!esPlanLargo(plan({ es_comercial: false, precio_clp: 25000 })),
    'el "Pase de regreso" (no comercial) -> no');
ok(!esPlanLargo(plan({ activo: false })), 'inactivo -> no');
ok(!esPlanLargo(null), 'null -> no (no explota)');

console.log('\n== 3. Mensuales comparables (para el selector) ==');
eq(planesComparables([mensual, plan(), { ...mensual, activo: false }, { ...mensual, duracion_dias: 90 }]).length, 1,
    'sólo los mensuales ACTIVOS con género');
ok(planesComparables([{ ...mensual, genero: 'femenino' }]).length === 1,
    'sirve para las 4 categorías (incluye femenino/estudiante)');
ok(planesComparables([{ ...mensual, precio_clp: 0 }]).length === 0,
    'un mensual gratis no es referencia');

console.log('\n== 4. Ahorro (se recalcula, no se guarda) ==');
const ahorro = ahorroDelPlan({ precio_clp: 150000, duracion_dias: 90 }, mensual);
eq(ahorro.meses, 3, '90 días contra 3 mensuales');
eq(ahorro.contra, 180000, 'N meses × precio del mensual');
eq(ahorro.ahorro, 30000, 'ahorro = contra - precio del plan');
eq(ahorro.pct, 17, 'porcentaje redondeado (30.000/180.000 = 17%)');
eq(ahorroDelPlan({ precio_clp: 200000, duracion_dias: 90 }, mensual), null,
    'ahorro NEGATIVO -> null (no se anuncia un sobreprecio como ahorro)');
eq(ahorroDelPlan({ precio_clp: 180000, duracion_dias: 90 }, mensual), null,
    'ahorro 0 -> null (no hay nada que celebrar)');
eq(ahorroDelPlan({ precio_clp: 150000, duracion_dias: 90 }, null), null,
    'sin referencia -> null');
eq(ahorroDelPlan({ precio_clp: 150000, duracion_dias: 90 }, { precio_clp: 0 }), null,
    'referencia sin precio -> null');

console.log('\n== 5. Calculadora "clases por mes" ==');
eq(creditosDesdeClasesPorMes('20', 180), 120, '20 clases/mes × 6 meses = 120');
eq(creditosDesdeClasesPorMes(20, 30), 20, 'un mensual: el total es el mismo número');
eq(creditosDesdeClasesPorMes('', 180), null, 'vacío -> null (no inventa 0)');
eq(creditosDesdeClasesPorMes('x', 180), null, 'texto inválido -> null');
eq(creditosDesdeClasesPorMes('-5', 180), null, 'negativo -> null');

console.log('\n== 6. Planes.jsx: panel de matrícula + tarjeta unisex ==');
coincide(planesSrc, /data-testid="panel-matricula"/, 'el panel de matrícula existe');
coincide(planesSrc, /data-testid="toggle-matricula"/, 'toggle activa/inactiva');
coincide(planesSrc, /data-testid="monto-matricula"/, 'input de monto editable');
coincide(planesSrc, /Activa desde el/, 'texto "Activa desde el <fecha>"');
coincide(planesSrc, /data-testid="contador-matricula"/, 'contador de alumnos cobrados');
coincide(planesSrc, /alumnos nuevos cobrados hasta hoy/, 'el contador se explica solo');
coincide(planesSrc, /data-testid="guardar-matricula"/, 'botón para guardar la config');
coincide(planesSrc, /Larga duración \(unisex\)/, 'tarjeta "Larga duración (unisex)"');
coincide(planesSrc, /\[\.\.\.TARJETAS, TARJETA_LARGA\]\.map/,
    'la tarjeta unisex se renderiza AL MISMO NIVEL que las 4 de siempre');
coincide(planesSrc, /const TARJETA_LARGA = \{[\s\S]{0,400}?genero: null/,
    'la tarjeta unisex filtra por genero NULL');

console.log('\n== 7. Planes.jsx: modal (ilimitado / clases por mes / comparación) ==');
coincide(planesSrc, /data-testid="plan-ilimitado"/, 'toggle Ilimitado');
coincide(planesSrc, /data-testid="plan-limitado"/, 'toggle Limitado');
coincide(planesSrc, /data-testid="plan-clases-por-mes"/, 'campo "Clases por mes"');
coincide(planesSrc, /data-testid="plan-total-creditos"/, 'texto de ayuda con el total');
coincide(planesSrc, /= \{totalCreditosMostrado\} créditos totales para los/,
    'muestra "= N créditos totales para los D días"');
coincide(planesSrc, /data-testid="plan-referencia"/, 'selector "Comparar ahorro contra"');
coincide(planesSrc, /<option value="">Unisex \(sin género\)<\/option>/,
    'el modal puede crear/editar un plan unisex');
coincide(planesSrc, /genero: formNormalizado\.genero \|\| null/,
    'unisex viaja como null (no como string vacío)');
coincide(planesSrc, /plan_referencia_id: !formNormalizado\.genero && planReferenciaId/,
    'la referencia se guarda sólo en planes unisex');
coincide(planesSrc, /data-testid=\{`badge-ahorro-\$\{p\.id\}`\}/, 'badge verde de ahorro');
coincide(planesSrc, /data-testid=\{`ahorro-detalle-\$\{p\.id\}`\}/, 'línea "vs. N meses de ..."'); 
ok(!/[\u{1F300}-\u{1FAFF}]/u.test(planesSrc), 'el panel nuevo no agrega emojis');

console.log('\n== 8. SolicitarPlan.jsx: "Planes extendidos" + matrícula ==');
coincide(solicitarSrc, /const planesExtendidos = React\.useMemo\([\s\S]{0,120}?planes\.filter\(esPlanLargo\)/,
    'los largos salen en su propia lista');
coincide(solicitarSrc, /\)\.filter\(\(p\) => !esPlanLargo\(p\)\)/,
    'y NO se mezclan con los regulares/estudiantes de la categoría');
coincide(solicitarSrc, /data-testid="planes-extendidos"/, 'sección propia en la pantalla');
coincide(solicitarSrc, /planesExtendidos\.length === 0/,
    'el "no hay planes" contempla la sección nueva');
coincide(solicitarSrc, /data-testid="resumen-matricula"/, 'línea "Matrícula (alumno nuevo)"');
coincide(solicitarSrc, /data-testid="resumen-total"/, 'total sumado en el resumen');
coincide(solicitarSrc, /Matrícula \(alumno nuevo\)/, 'el alumno ve el concepto');
coincide(solicitarSrc, /formatearPrecio\(totalAPagar\(planSeleccionado\)\)/,
    'el botón de Mercado Pago anuncia el total con matrícula');

console.log('\n== 9. queries.js: hooks y claves de la matrícula ==');
coincide(queriesSrc, /matriculaConfig: \['matricula', 'config'\]/, 'clave del panel');
coincide(queriesSrc, /miMatricula: \['matricula', 'mi-estado'\]/, 'clave del alumno');
coincide(queriesSrc, /export function useMatriculaConfig\(\)/, 'hook del panel');
coincide(queriesSrc, /export function useGuardarMatriculaConfig\(\)/, 'mutación del panel');
coincide(queriesSrc, /export function useMiMatricula\(\)/, 'hook del alumno');
coincide(queriesSrc, /api\.put\('\/api\/v1\/matricula'/, 'el panel guarda por PUT /matricula');
coincide(queriesSrc, /api\.get\('\/api\/v1\/matricula\/mi-estado'/, 'el alumno consulta su estado');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));

process.exit(fallos === 0 ? 0 : 1);

