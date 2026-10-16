// Test aislado del retiro de "Gestión de Clases" del panel del coach (aprobado):
// su vista semanal queda FUSIONADA en la pestaña Clases y TODO lo que sólo vivía en esa
// pantalla se portó al panel (edición de un WOD publicado, carga masiva por Excel, aviso
// rápido del día, tomar/soltar clase y cubrir suplencia). La pantalla se retiró por
// completo: menú, ruta y archivo.
//   Ejecutar:  node scripts/test-clases-sin-gestion.mjs   (npm run test:clases-coach)
//
// POR QUÉ EXISTE: el coach reportó que tocar una clase en "Mis clases de hoy" lo llevaba a
// la pantalla vieja (la configuración antigua) y tardaba en cargar. Se decidió sacarla del
// menú y publicar/editar en la MISMA pantalla. Este test fija lo que no puede volver atrás,
// sin navegador:
//   1. el menú del coach ya no ofrece `/coach/gestion-clases` (y sí sus otras dos puertas);
//   2. la vista semanal sigue existiendo como sub-pestaña Clases del panel;
//   3. el Dashboard no NAVEGA a la pantalla vieja: abre `ModalPublicarWod` con esa clase
//      (fila del Resumen y lista móvil de la semana), y el botón "Gestionar Clases" —que era
//      el otro link— ya no está;
//   4. la grilla Lun→Dom + el filtro "Ver todas / Ver solo con WOD publicado" siguen ahí, y
//      el lápiz/celda publica con ESE MISMO modal (Bloque 1, verificado intacto);
//   5. los avisos de clase de la campana llevan al panel (`?tab=clases`), no a la vieja;
//   6. la pantalla vieja NO existe más (archivo, ruta e import borrados) y ninguna de sus
//      funciones exclusivas se perdió: editar un WOD publicado, la carga por Excel, el aviso
//      rápido y tomar/soltar/suplencia tienen su lugar en el panel.
import { existsSync, readFileSync, readdirSync } from 'node:fs';

import { COACH_SUBTABS, MENU_BY_ROL } from '../src/config/menu.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};
const ok = (cond, msg) => eq(Boolean(cond), true, msg);
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

const DASH = leer('../src/pages/coach/DashboardCoach.jsx');
const CAMPANA = leer('../src/components/CampanaNotificaciones.jsx');
const APP = leer('../src/App.jsx');
const MODAL = leer('../src/components/ModalPublicarWod.jsx');
const ACCIONES = leer('../src/components/AccionesClaseCoach.jsx');
const VIEJA = '../src/pages/coach/GestionClases.jsx';

console.log('== 1. El menú del coach ya no ofrece Gestión de Clases ==');
const rutasCoach = MENU_BY_ROL.coach.filter((i) => i.path).map((i) => i.path);
ok(!rutasCoach.includes('/coach/gestion-clases'),
    `sin ítem a /coach/gestion-clases (quedan: ${rutasCoach.join(', ')})`);
ok(rutasCoach.includes('/coach/dashboard') && rutasCoach.includes('/coach/entregar-pedido'),
    'las otras dos puertas del coach siguen');

console.log('== 2. La vista semanal sigue siendo la sub-pestaña Clases ==');
ok(COACH_SUBTABS.some((s) => s.key === 'clases' && s.path === '/coach/dashboard?tab=clases'),
    'COACH_SUBTABS conserva la pestaña Clases (ahí vive la grilla fusionada)');

console.log('== 3. Tocar una clase publica en la MISMA pantalla ==');
ok(!/irAGestionClases/.test(DASH), 'DashboardCoach no tiene el helper que navegaba a la vieja');
ok(!/navigate\(\s*'\/coach\/gestion-clases'/.test(DASH),
    'no queda ninguna navegación directa a /coach/gestion-clases');
ok(/const abrirPublicarWod = \(clase\) => \{[\s\S]{0,300}setClaseWod\(clase\);\s*\n\s*setModalWod\(true\);/.test(DASH),
    'el modal unificado se abre con la clase tocada (`claseDestino`) sin cambiar de ruta');
ok(DASH.includes('onAbrirClase={abrirClaseDeHoy}'),
    'la fila de "Mis clases de hoy" (ResumenCoach) entra por ese camino');
ok(/abrirPublicarWod\(\{ \.\.\.clase, fecha: clase\.fecha \|\| date \}\)/.test(DASH),
    'la lista móvil de la semana entra por el mismo camino');
// Si la clase YA tiene WOD no se publica otro: `batch-create` crea un WOD nuevo y re-apunta
// `clase.wod_id`, así que volver a publicar dejaría el anterior huérfano.
ok(/const abrirClaseDeHoy = \(clase\) => \{[\s\S]{0,220}if \(wod\) \{ abrirDetalleWod\(clase, wod\); return; \}/.test(DASH),
    'una clase con WOD publicado abre su detalle (no duplica el WOD)');
ok(!/📋\s*Gestionar Clases\s*<\/button>/.test(DASH),
    'el botón "📋 Gestionar Clases" de la pestaña Clases ya no existe');

console.log('== 4. La grilla semanal fusionada y el MISMO modal (Bloque 1, intacto) ==');
ok(DASH.includes("const DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']"),
    'la grilla sigue siendo Lun→Dom');
ok(DASH.includes('SCHEDULE_HOURS') && DASH.includes('data-testid="publicar-wod-celda"'),
    'las celdas por horario siguen ahí');
ok(DASH.includes('verSoloConWod') && /Ver solo con/.test(DASH),
    'el filtro "Ver todas / Ver solo con WOD publicado" sigue en la pestaña Clases');

console.log('== 4b. Punto 3: la fila de botones envuelve en el teléfono ==');
// Los cuatro botones de la fila superior (Semana anterior / siguiente / Excel / Aviso rápido)
// ocupaban más que el ancho del panel en 360px: el último se cortaba contra el borde
// (`overflow-hidden`) y se pisaba con el de al lado. Ahora la fila ENVUELVE y nada se recorta.
ok(/<div className="flex min-w-0 flex-wrap items-center justify-end gap-2">/.test(DASH),
    'la fila de los 4 botones usa flex-wrap (antes: flex items-center gap-2, que desbordaba)');
ok(/data-testid="cargar-excel-semana"/.test(DASH) && /data-testid="aviso-rapido-clases"/.test(DASH),
    'los cuatro botones siguen siendo los mismos (no cambia la función de ninguno)');
ok(/flex w-full flex-wrap items-center gap-2 rounded-xl bg-gray-100 p-2 md:inline-flex md:w-auto md:gap-3/.test(DASH),
    'el toggle "Ver todas / Ver solo con WOD publicado" envuelve en el teléfono y sigue inline en >=768px');
ok(/flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all md:flex-none/.test(DASH),
    'los dos botones del toggle se reparten el ancho sólo en <768px y el rótulo largo envuelve (sin recortarse)');
ok(/w-full px-3 py-3 flex items-center gap-3 text-left transition-colors sm:px-4/.test(DASH),
    'la lista de días gana aire en el teléfono (px-3) y queda igual desde sm');
ok(/text-lg font-bold text-gray-800 w-16 shrink-0/.test(DASH),
    'la hora de cada clase tiene más ancho (w-16) para que el resto no se comprima');
ok(DASH.includes('onClick={() => { setClaseWod(clase); setModalWod(true); }}'),
    'el lápiz/celda de la grilla abre ESE modal con su horario');
ok(DASH.includes('<ModalPublicarWod') && DASH.includes('clase={wodArchivo ? null : (claseWod || proximaClase || clasesHoy[0] || null)}'),
    'hay UNA sola montura del modal en el panel (Resumen + Clases)');

console.log('== 5. Los avisos de clase de la campana llevan al panel ==');
for (const tipo of ['clase_asignada', 'clase_reasignada', 'clase_liberada']) {
    ok(CAMPANA.includes(`${tipo}: '/coach/dashboard?tab=clases'`), `${tipo} -> ?tab=clases`);
}
ok(!/clase_(asignada|reasignada|liberada): '\/coach\/gestion-clases'/.test(CAMPANA),
    'ningún aviso de clase apunta a la pantalla retirada');

console.log('== 6. La pantalla vieja se retiró POR COMPLETO (y nada quedó sin UI) ==');
ok(!existsSync(new URL(VIEJA, import.meta.url)),
    'GestionClases.jsx ya no está en el repo (menú + ruta + archivo)');
ok(!/path="gestion-clases"/.test(APP), 'la ruta tampoco está declarada en App.jsx');
ok(!/CoachGestionClases/.test(APP), 'y no queda el import lazy huérfano (sería un chunk de más)');
// Barrido real de src/: un enlace nuevo a la pantalla retirada saltaría acá (no en el
// teléfono del coach). Es el mismo patrón que usa `test-rutas-coach.mjs` con Pizarra.
const archivosFuente = (url) => readdirSync(url, { withFileTypes: true }).flatMap((e) =>
    (e.isDirectory() ? archivosFuente(new URL(e.name + '/', url)) : [new URL(e.name, url)]));
const FUENTES = archivosFuente(new URL('../src/', import.meta.url))
    .filter((u) => /\.(jsx|js)$/.test(u.pathname));
const PATRON = /\/coach\/gestion-clases(?![\w-])/;
const enlaces = FUENTES.filter((u) => PATRON.test(readFileSync(u, 'utf8')))
    .map((u) => u.pathname.split('/src/')[1]);
eq(enlaces.length, 0, `ninguna fuente enlaza la pantalla retirada${enlaces.length ? ` (revisar: ${enlaces.join(', ')})` : ''}`);
ok(FUENTES.length > 100, `se revisan las fuentes de src/ (${FUENTES.length} archivos)`);

// Y ninguna función exclusiva se perdió al retirarla: las cuatro quedaron en el panel.
ok(/useGuardarWod/.test(MODAL) && MODAL.includes('wodId: wodEdicion.id') && /const esEdicion = Boolean\(wodEdicion\?\.id\)/.test(MODAL),
    'editar un WOD publicado = modo edición del MISMO modal (PUT /wods/{id})');
ok(DASH.includes('wodEdicion={wodEdicion}') && DASH.includes('soloArchivo={wodArchivo}'),
    'el panel le pasa el WOD a editar y la carga masiva por Excel');
ok(/data-testid="editar-wod-celda"/.test(DASH) && /->|abrirEditarWod\(/.test(DASH),
    'la grilla ofrece ✏️ Editar en la celda con WOD (sin salir del panel)');
ok(/data-testid="cargar-excel-semana"/.test(DASH) && /abrirCargaMasiva/.test(DASH),
    'la pestaña Clases ofrece "+ Cargar WODs de la semana (Excel)"');
ok(/data-testid="wod-disciplina-archivo"/.test(MODAL),
    'la carga masiva sin clase pide la disciplina (el backend la exige)');
ok(/import ModalAvisoRapido from '\.\.\/\.\.\/components\/ModalAvisoRapido'/.test(DASH)
    && /data-testid="aviso-rapido-clases"/.test(DASH),
    'el aviso rápido del día sigue disponible (botón en la pestaña Clases)');
ok(/import AccionesClaseCoach from/.test(DASH) && /<AccionesClaseCoach/.test(DASH),
    'la pestaña Clases monta tomar/soltar/suplencia en cada clase');
ok(/useAccionClase/.test(ACCIONES) && /accionClaseMut\.mutateAsync\(/.test(ACCIONES),
    'AccionesClaseCoach usa el MISMO hook de la pantalla vieja (POST /clases/{id}/tomar|soltar)');
ok(/modo_emergencia = true/.test(ACCIONES) && /Cubrir suplencia/.test(ACCIONES),
    'la cobertura de emergencia se renombró "Cubrir suplencia" (mismo parámetro del backend)');
ok(/Cubrir suplencia/.test(ACCIONES) && !/cubrir como emergencia/.test(ACCIONES),
    'el botón pasó de "Sí, cubrir como emergencia" a "Sí, cubrir suplencia"');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
