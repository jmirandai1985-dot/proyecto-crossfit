// Test aislado del Resumen del coach (Bloque C) y del texto de entrega (Bloque B).
//   Ejecutar:  node scripts/test-coach-resumen.mjs   (npm run test:coach-resumen)
//
// QUÉ FIJA:
//   1. el Resumen es el del mockup: 4 KPIs (clases hoy / alumnos / WOD del día / riesgo),
//      la tarjeta ancha de Asistencia con los 3 números y "Mis clases de hoy";
//   2. los dos botones inline abren los modales REALES (+ Publicar WOD y + Agregar sin
//      reserva) y no navegan a otra pantalla;
//   3. las filas hablan como el mockup y como la pestaña Asistencia: el progreso y el estado
//      salen de `utils/franjasAsistencia`, no de una copia propia ("12/12 presentes",
//      "9/14 marcados", "Hecha" / "En curso" / "Pendiente");
//   4. la regla de negocio sigue en el copy: el alumno marca, el coach corrige; el crédito
//      se descuenta al RESERVAR (nunca "a medianoche", que no es lo que hace el backend);
//   5. mobile-first: el contenido se limita y se centra (no hay layout de PC inventado);
//   6. EL RESUMEN VIEJO NO EXISTE: el panel de tarjetas grandes que se pintaba en TODAS las
//      pestañas —encima del Resumen nuevo— se eliminó completo (ni "WODs esta semana" ni
//      sus botones), y el panel claro ya no envuelve al Resumen;
//   7. Bloque B: el coach NO promete escaneo (ni la página ni el modal), y el admin sigue
//      igual (la prop del modal arranca en true).
import { readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const RESUMEN = leer('../src/components/ResumenCoach.jsx');
const DASH = leer('../src/pages/coach/DashboardCoach.jsx');
const ENTREGA = leer('../src/pages/coach/EntregarPedido.jsx');
const MODAL_ENTREGA = leer('../src/components/ModalEntregarPedido.jsx');

// El Dashboard documenta en COMENTARIOS por qué se eliminó el Resumen viejo (los nombres
// aparecen ahí a propósito, para que nadie los reviva), así que las búsquedas de "no debe
// quedar ningún resto" se hacen sobre el código SIN comentarios: lo que importa es que no
// quede MARKUP en pantalla.
const sinComentarios = (src) => src
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '');
const DASH_CODIGO = sinComentarios(DASH);

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

console.log('== 1. Los 4 KPIs del mockup ==');
for (const id of ['kpi-clases-hoy', 'kpi-alumnos', 'kpi-riesgo', 'abrir-publicar-wod']) {
    ok(RESUMEN.includes(`data-testid="${id}"`), `el KPI "${id}" está`);
}
ok(/WOD del día/.test(RESUMEN) && /Sin publicar/.test(RESUMEN), 'el KPI del WOD dice "Sin publicar" cuando no hay');
ok(/asistentesHoy/.test(RESUMEN), 'KPI Clases hoy muestra los asistentes del día');
ok(/alumnosConRms/.test(RESUMEN) && /alumnosActivos/.test(RESUMEN), 'KPI Alumnos activos muestra "N con RMs"');
ok(/Sin asistir \{umbralRiesgo\}\+ días/.test(RESUMEN), 'KPI En riesgo dice el umbral en días');

console.log('== 2. Tarjeta de Asistencia: 3 números y el botón del walk-in ==');
for (const t of ['con reserva', 'ya marcaron', 'faltan']) {
    ok(RESUMEN.includes(t), `la tarjeta muestra "${t}"`);
}
ok(/const conReserva = proximaClase\?\.reservas_count \?\? reservasProxima\.length/.test(RESUMEN),
    'los números salen de las reservas de ESA clase (no de un contador aparte)');
ok(/data-testid="resumen-agregar-sin-reserva"/.test(RESUMEN) && /onAgregarSinReserva\(proximaClase\)/.test(RESUMEN),
    'el botón "+ Agregar alumno sin reserva" abre el modal con la clase próxima');
ok(/data-testid="tarjeta-asistencia"/.test(RESUMEN), 'la tarjeta ancha está');
ok(/Mis clases de hoy/.test(RESUMEN), 'la lista "Mis clases de hoy" está');

console.log('== 3. Los textos y los estados son los del mockup ==');
ok(/Toca para ver quiénes faltan/.test(RESUMEN),
    'la tarjeta invita a ver quiénes faltan (el texto del mockup, sin adornos agregados)');
ok(/from '\.\.\/utils\/franjasAsistencia'/.test(RESUMEN),
    'el Resumen usa los helpers de la pestaña Asistencia, no una copia propia');
ok(/estadoFila\(clase\)/.test(RESUMEN) && /etiquetaEstado\(estado\)/.test(RESUMEN),
    'el badge de cada fila sale de estadoFila/etiquetaEstado (Hecha / En curso / Pendiente)');
ok(/textoProgreso\(clase, esperados > 0 \? esperados : undefined\)/.test(RESUMEN),
    'el progreso de cada fila es "12/12 presentes" / "9/14 marcados" (mismo helper)');
ok(/const esperados = reservasDe\(clase\)/.test(RESUMEN),
    'el tope del progreso sale de las reservas de ESA clase, no del cupo nominal');
eq(/medianoche/i.test(RESUMEN) || /medianoche/i.test(DASH), false,
    'el Resumen NO dice que el crédito se descuente a medianoche (se descuenta al reservar)');
ok(/se le descontó 1 crédito/.test(DASH), 'el aviso del walk-in dice que descontó el crédito');
ok(/sin cargo \(queda en su historial\)/.test(DASH), 'y cuando no tiene plan, dice que quedó sin cargo');

console.log('== 4. Mobile-first declarado ==');
ok(/mx-auto max-w-2xl/.test(RESUMEN), 'el Resumen acota y centra el contenido (diseño de teléfono)');
ok(/grid-cols-2 gap-2\.5/.test(RESUMEN), 'los KPIs van en la grilla de 2 del mockup');

console.log('== 5. Cableado y limpieza del Resumen viejo ==');
ok(/<ResumenCoach/.test(DASH) && /activeTab === 'resumen' &&/.test(DASH), 'el Resumen está montado en su pestaña');
ok(/<ModalPublicarWod/.test(DASH) && /<ModalAgregarSinReserva/.test(DASH), 'los dos modales están montados');
ok(/clase=\{proximaClase \|\| clasesHoy\[0\] \|\| null\}/.test(DASH), 'el modal de WOD sabe sobre qué clase publica');
ok(/data-testid="resumen-publicado"/.test(DASH), 'el Resumen muestra qué contestó el backend');
for (const muerto of ['claseAsistenciaExpandida', 'asistenciaOverrides', 'registrosRecientes',
    'cargarAsistenciaClase', 'marcarTodosAsistencia', 'handlePublicarWOD']) {
    eq(new RegExp(`\\b${muerto}\\b`).test(DASH), false, `sin código muerto del Resumen viejo: ${muerto}`);
}

console.log('== 5b. El Resumen viejo se eliminó por completo (una sola versión en pantalla) ==');
for (const viejo of ['WODs esta semana', 'Publicar WOD de Hoy', 'Ir a Gestión de Clases',
    'Alumnos Activos', 'Clases Hoy']) {
    eq(DASH_CODIGO.includes(viejo), false, `sin restos del Resumen viejo: "${viejo}"`);
}
eq(/clasesConWodPublicado|wodsPublicados/.test(DASH_CODIGO), false,
    'sin los contadores del KPI "WODs esta semana"');
eq(/grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4/.test(DASH_CODIGO), false,
    'sin la fila de tarjetas grandes: los KPIs son sólo el grid 2x2 de ResumenCoach');
ok(/activeTab === 'resumen'[\s\S]{0,60}\? ''/.test(DASH),
    'el panel claro ya no envuelve al Resumen (va sobre el fondo oscuro del Layout)');
ok(/\{fechaCortaHoy\} · \{usuario \|\| 'Coach'\}/.test(DASH),
    'el encabezado dice "fecha · coach", como el hdr del mockup');

console.log('== 6. Bloque B: el coach no promete escaneo ==');
ok(/mencionarEscaneo=\{false\}/.test(ENTREGA), 'la pantalla del coach apaga la mención del escaneo');
eq(/escánea|escanea|📷/i.test(ENTREGA), false, 'el texto del coach no menciona escanear ni la cámara');
ok(/Ingresa\{mencionarEscaneo \? ' o escanea' : ''\}/.test(MODAL_ENTREGA),
    'el modal compone el texto según la prop (por defecto, el de siempre)');
ok(/mencionarEscaneo = true/.test(MODAL_ENTREGA), 'la prop arranca en true: el admin queda igual');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
