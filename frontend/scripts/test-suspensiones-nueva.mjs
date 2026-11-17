// Test aislado del modal "+ Nueva suspensión" (pantalla Suspensiones del admin).
//   Ejecutar:  node scripts/test-suspensiones-nueva.mjs   (npm run test:suspensiones)
//
// El repo no usa jsdom ni un framework de componentes: acá se fija, sin navegador,
//   1. la regla PURA que detecta la creación (`src/utils/suspensiones.js`), y
//   2. el CONTRATO de la fuente de los archivos que arman el flujo:
//      - `components/admin/NuevaSuspensionModal.jsx` (2 pasos + el panel real),
//      - `pages/admin/Suspensiones.jsx` (botón + refresco del listado),
//      - `hooks/queries.js` (clave familia + mutationKey de la creación).
// Además comprueba que el panel compartido y su uso en la ficha NO cambiaron.
import { readFileSync } from 'node:fs';
import { haySuspensionNueva, idsSuspensionesCreadas } from '../src/utils/suspensiones.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

const modalSrc = leer('../src/components/admin/NuevaSuspensionModal.jsx');
const paginaSrc = leer('../src/pages/admin/Suspensiones.jsx');
const queriesSrc = leer('../src/hooks/queries.js');
const panelSrc = leer('../src/components/admin/SuspensionSaludPanel.jsx');
const fichaSrc = leer('../src/components/FichaAlumnoTabs.jsx');

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

console.log('== 1. Ids de suspensiones creadas ==');
eq(idsSuspensionesCreadas([1, null, undefined, '3', 'x']), [1, 3],
    'se quedan los ids numéricos (strings incluidos) y se descarta la basura');
eq(idsSuspensionesCreadas(undefined), [], 'sin datos -> lista vacía (no explota)');
eq(idsSuspensionesCreadas(null), [], 'null -> lista vacía');

console.log('\n== 2. ¿Apareció una suspensión nueva? ==');
eq(haySuspensionNueva(new Set([1]), [1]), false,
    'el mismo id de antes NO cierra el modal (reabrir al mismo alumno no dispara nada)');
eq(haySuspensionNueva(new Set([1]), [1, 2]), true,
    'un id nuevo SÍ: la creación salió bien');
eq(haySuspensionNueva(new Set(), []), false, 'sin ids -> no hay novedad');
eq(haySuspensionNueva([1, 2], ['2']), false,
    'la foto inicial también acepta array y los strings se normalizan');
eq(haySuspensionNueva(new Set([1]), ['2']), true,
    'un id creado después de abrir el paso 2 se detecta aunque llegue como string');
eq(haySuspensionNueva(new Set([1, 2]), [2, 1]), false,
    'el orden no importa: los mismos ids no son una novedad');

console.log('\n== 3. La clave familia de Suspensiones (React Query) ==');
// Cómo matchea React Query un prefijo: parte por parte, en orden.
const esPrefijo = (clave, prefijo) => prefijo.length <= clave.length
    && prefijo.every((parte, i) => clave[i] === parte);
const FAMILIA = ['admin', 'suspensiones'];
ok(esPrefijo(['admin', 'suspensiones', '', '', '', ''], FAMILIA),
    'el listado (con cualquier filtro) cuelga de la familia');
ok(esPrefijo(['admin', 'suspensiones', 'resumen'], FAMILIA),
    'el resumen de KPIs cuelga de la familia (se refrescan juntos)');
ok(!esPrefijo(['admin', 'suspensiones-salud', 7], FAMILIA),
    'el historial por alumno (suspensiones-salud) NO se toca al refrescar la pantalla');


console.log('\n== 4. queries.js: clave familia + mutación observable ==');
coincide(queriesSrc, /suspensionesAdminFamilia: \['admin', 'suspensiones'\],/,
    'la familia del listado/resumen existe como clave propia');
coincide(queriesSrc, /export const MUTACION_CREAR_SUSPENSION_SALUD = \['suspension-salud', 'crear'\];/,
    'la creación exporta la clave de mutación que observa el modal');
coincide(queriesSrc, /mutationKey: MUTACION_CREAR_SUSPENSION_SALUD,/,
    'useCrearSuspensionSalud declara esa clave de mutación');
eq((queriesSrc.match(/qc\.invalidateQueries\(\{ queryKey: claves\.suspensionesAdminFamilia \}\);/g) || []).length, 2,
    'crear Y cancelar refrescan la pantalla Suspensiones (2 invalidaciones de la familia)');

console.log('\n== 5. Suspensiones.jsx: botón + apertura del modal ==');
coincide(paginaSrc, /data-testid="btn-nueva-suspension"\s*\n\s*className="[^"]*bg-orange-500[^"]*"/,
    'el botón "+ Nueva suspensión" usa el naranja del resto del panel');
ok(paginaSrc.includes('+ Nueva suspensión'), 'el rótulo es texto plano (sin emoji ni icono)');
coincide(paginaSrc, /\{modalNueva && \(/, 'el modal se monta sólo cuando se pide');
coincide(paginaSrc, /<NuevaSuspensionModal[\s\S]{0,200}?onCerrar=\{cerrarModalNueva\}[\s\S]{0,200}?onCreada=\{alCrearSuspension\}/,
    'el modal recibe el cierre y el aviso de creación');
coincide(paginaSrc, /qc\.invalidateQueries\(\{ queryKey: claves\.suspensionesAdminFamilia \}\);/,
    'al crear/cerrar se invalida listado + resumen (useSuspensionesAdmin y useResumenSuspensiones)');
coincide(paginaSrc, /data-testid="aviso-suspension-creada"/,
    'queda un aviso de "creada" en la pantalla cuando el modal se cierra solo');
eq((paginaSrc.match(/setModalNueva\(false\)/g) || []).length, 2,
    'el modal se cierra tanto al crear como al cerrar a mano');

console.log('\n== 6. NuevaSuspensionModal.jsx: paso 1 busca como el padrón ==');
coincide(modalSrc, /const ESPERA_BUSQUEDA_MS = 350;/, 'debounce de 350 ms, igual que Alumnos.jsx');
coincide(modalSrc, /termino \? ESPERA_BUSQUEDA_MS : 0/, 'al vaciar la caja no se espera nada');
coincide(modalSrc, /const RESULTADOS_POR_BUSQUEDA = 8;/, 'el selector pide pocos resultados, no una tabla');
coincide(modalSrc, /useAlumnosPaginados\(\{[\s\S]{0,200}?buscar: busqueda,/,
    'reusa useAlumnosPaginados con la búsqueda server-side (`buscar`)');
coincide(modalSrc, /data-testid="buscar-alumno-suspension"/, 'el input de búsqueda existe');
coincide(modalSrc, /\{a\.nombre\}/, 'cada resultado muestra el nombre');
coincide(modalSrc, /\{a\.correo\}/, 'cada resultado muestra el correo');
coincide(modalSrc, /data-testid=\{`elegir-alumno-\$\{a\.id\}`\}/, 'cada resultado es clickeable (id del alumno)');

console.log('\n== 7. NuevaSuspensionModal.jsx: paso 2 monta el panel REAL ==');
coincide(modalSrc, /<SuspensionSaludPanel usuarioId=\{alumno\.id\} \/>/,
    'monta SuspensionSaludPanel tal cual, con el usuarioId elegido');
coincide(modalSrc, /data-testid="cambiar-alumno-suspension"/, 'hay botón para volver al paso 1');
ok(modalSrc.includes('Cambiar de alumno'), 'el botón de volver dice "Cambiar de alumno"');
eq((modalSrc.match(/data-testid="cerrar-nueva-suspension"/g) || []).length, 2,
    'hay botón de cerrar en los dos pasos');
coincide(modalSrc, /useMutationState\(/, 'el padre observa la mutación de creación (no toca el panel)');
coincide(modalSrc, /status: 'success',[\s\S]{0,200}?m\.state\.data\?\.suspension\?\.id/,
    'sólo cuenta la creación confirmada (la vista previa no trae `suspension`)');
coincide(modalSrc, /haySuspensionNueva\(previasRef\.current, actuales\)/,
    'la regla pura decide si apareció una suspensión nueva');

console.log('\n== 8. Responsive: entra en un celular sin pantalla aparte ==');
for (const clase of ['max-h-[92dvh]', 'overflow-y-auto', 'sm:max-w-2xl', 'sm:items-center', 'rounded-t-2xl']) {
    ok(modalSrc.includes(clase), `el modal usa ${clase}`);
}

console.log('\n== 9. El panel compartido y la ficha NO cambiaron ==');
coincide(panelSrc, /const SuspensionSaludPanel = \(\{ usuarioId \}\) => \{/,
    'SuspensionSaludPanel sigue recibiendo sólo `usuarioId`');
ok(!panelSrc.includes('onCreada'), 'el panel no recibió callbacks nuevos (no se modificó)');
ok(fichaSrc.includes('SuspensionSaludPanel usuarioId={alumnoId}'),
    'FichaAlumnoTabs lo sigue montando igual');
ok(!/[\u{1F300}-\u{1FAFF}]/u.test(modalSrc), 'el modal nuevo no agrega emojis');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));

process.exit(fallos === 0 ? 0 : 1);
