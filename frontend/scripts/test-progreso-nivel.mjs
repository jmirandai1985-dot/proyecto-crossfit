// Test aislado del cálculo de la barra de nivel por movimiento (Performance Hub).
//   Ejecutar:  node scripts/test-progreso-nivel.mjs   (npm run test:nivel)
//
// `src/utils/progresoNivel.js` devuelve el % entre el umbral del nivel actual y
// el siguiente, con clamps a [0, 100] y el caso "Elite" (sin siguiente umbral).
import { pctProgresoNivel } from '../src/utils/progresoNivel.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

eq(pctProgresoNivel(80, { umbral_actual: 70, umbral_siguiente: 90 }), 50, '80 entre 70 y 90 -> 50%');
eq(pctProgresoNivel(70, { umbral_actual: 70, umbral_siguiente: 90 }), 0, 'en el umbral actual -> 0%');
eq(pctProgresoNivel(90, { umbral_actual: 70, umbral_siguiente: 90 }), 100, 'en el umbral siguiente -> 100%');
eq(pctProgresoNivel(100, { umbral_actual: 70, umbral_siguiente: 90 }), 100, 'por encima del siguiente se clampa a 100');
eq(pctProgresoNivel(60, { umbral_actual: 70, umbral_siguiente: 90 }), 0, 'por debajo del actual se clampa a 0');

eq(pctProgresoNivel(80, null), 0, 'sin detalle -> 0');
eq(pctProgresoNivel(80, { umbral_actual: null, umbral_siguiente: 90 }), 0, 'umbral actual nulo -> 0');
eq(pctProgresoNivel(80, { umbral_actual: 70, umbral_siguiente: null }), 0, 'umbral siguiente nulo -> 0');

eq(pctProgresoNivel(90, { nivel: 'Elite', umbral_actual: 90, umbral_siguiente: 90 }), 100,
    'Elite sin umbral siguiente -> barra llena (100)');
eq(pctProgresoNivel(90, { nivel: 'Intermedio', umbral_actual: 90, umbral_siguiente: 90 }), 0,
    'umbral siguiente <= actual y NO es Elite -> 0');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
