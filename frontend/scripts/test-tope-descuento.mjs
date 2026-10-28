// Test aislado: el "Descuento máximo de beneficios" vive en Fidelización, no en Configuración.
//   Ejecutar:  node scripts/test-tope-descuento.mjs
//
// Es una regla de FIDELIZACIÓN (tope de lo que un beneficio puede regalar sobre el próximo plan),
// así que se edita junto a los beneficios que la usan. La API/columna NO cambian
// (`PUT /configuracion` con `beneficio_descuento_max_pct`), sólo se movió la UI.
import { readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

const configuracion = leer('../src/pages/admin/Configuracion.jsx');
const beneficios = leer('../src/components/BeneficiosPanel.jsx');
const fidelizacion = leer('../src/pages/admin/Fidelizacion.jsx');
const backend = leer('../../backend/app/api/v1/configuracion.py');

console.log('== 1. Configuración ya no lo muestra ==');
ok(!configuracion.includes('beneficio_descuento_max_pct'),
    'Configuracion.jsx no referencia el campo');
ok(!configuracion.includes('config-descuento-max'),
    'ya no existe el input `config-descuento-max`');

console.log('== 2. Fidelización → Beneficios lo edita ==');
ok(fidelizacion.includes('<BeneficiosPanel'), 'Fidelización monta el panel de Beneficios');
ok(beneficios.includes("useConfiguracionBancaria"), 'lee la config con el hook compartido');
ok(beneficios.includes('useGuardarConfiguracion'), 'guarda con el hook compartido');
ok(beneficios.includes('beneficio_descuento_max_pct'),
    'usa el MISMO campo de la API');
ok(beneficios.includes('data-testid="beneficios-tope-descuento"'), 'tiene su bloque propio');
ok(beneficios.includes('data-testid="beneficios-descuento-max"'), 'tiene el input del tope');
ok(beneficios.includes('data-testid="beneficios-guardar-tope"'), 'tiene botón de guardar');
ok(beneficios.includes('pct < 0 || pct > 100'),
    'valida el rango 0..100 antes de mandar');
ok(beneficios.includes('Number.isInteger(pct)'),
    'rechaza decimales (el backend espera un entero)');
ok(beneficios.includes('mutateAsync({ beneficio_descuento_max_pct: pct })'),
    'manda SOLO el tope (no pisa el resto de la configuración)');
ok(beneficios.includes('topeRellenado'), 'rellena una sola vez (no pisa lo que se escribe)');

console.log('== 3. El contrato del backend queda igual ==');
ok(backend.includes('beneficio_descuento_max_pct'), 'la API sigue exponiendo el campo');
ok(backend.includes('TOPE_DESCUENTO_DEFAULT'), 'sigue habiendo default (50)');

console.log('');
if (fallos > 0) {
    console.log(`${fallos} chequeo(s) fallaron.`);
    process.exit(1);
}
console.log('Todos los chequeos pasaron.');
