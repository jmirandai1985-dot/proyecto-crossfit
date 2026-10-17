// Test aislado del panel de Notificaciones en MOBILE (Parte D).
//   Ejecutar:  node scripts/test-campana-movil.mjs   (npm run test:campana)
//
// POR QUÉ EXISTE: el panel era `absolute right-0 w-80` colgado de la campana. En un
// teléfono la campana está cerca del borde derecho, así que el panel arrancaba FUERA de
// la pantalla por la izquierda y se comía las primeras letras ("lotificaciones",
// "LAN APROBADO", fechas). Es el MISMO componente para alumno, admin y coach: este test
// cuida que siga anclado al viewport en mobile y que no vuelva el ancho fijo.
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

const CAMPANA = leer('../src/components/CampanaNotificaciones.jsx');
const LAYOUT = leer('../src/components/Layout.jsx');

console.log('== 1. En mobile el panel se ancla al viewport (no desborda a la izquierda) ==');
ok(/className="fixed inset-x-2 top-\[calc\(env\(safe-area-inset-top\)\+4\.5rem\)\][^"]*"/.test(CAMPANA),
    'mobile: fixed + inset-x-2 (8px a cada lado) y debajo del header (respetando el notch)');
ok(CAMPANA.includes('sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2'),
    'desde sm vuelve al dropdown alineado a la derecha de la campana');
ok(CAMPANA.includes('sm:w-96'), 'en escritorio conserva el ancho de siempre');
ok(!/className="absolute right-0 mt-2 w-80/.test(CAMPANA),
    'ya no queda el panel `w-80` colgado de la campana (la causa del recorte)');
const clases = [...CAMPANA.matchAll(/className="([^"]+)"/g)].map((m) => m[1]).join(' ');
ok(!/\bw-80\b/.test(clases), 'no hay ningún ancho fijo de 320px que desborde en mobile');
ok(CAMPANA.includes('sm:max-w-[calc(100vw-2rem)]'),
    'en pantallas angostas el ancho nunca supera el viewport');

console.log('== 2. Sigue siendo el MISMO panel para los tres roles ==');
ok(LAYOUT.includes('<CampanaNotificaciones />'), 'Layout monta la campana compartida');
ok(/rol === 'alumno' \|\| rol === 'administrador' \|\| rol === 'admin' \|\| rol === 'coach'/
    .test(LAYOUT), 'alumno, admin y coach ven la MISMA campana (un solo fix)');
ok(CAMPANA.includes('fixed inset-0 z-40'), 'el fondo para cerrar al tocar fuera sigue ahí');
ok(CAMPANA.includes('max-h-[70vh] overflow-y-auto'),
    'la lista larga sigue scrolleando dentro del panel');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
