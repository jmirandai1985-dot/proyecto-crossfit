// Test aislado del Resumen del coach (Bloque C) y del texto de entrega (Bloque B).
//   Ejecutar:  node scripts/test-coach-resumen.mjs   (npm run test:coach-resumen)
//
// QUÉ FIJA:
//   1. el Resumen es el rediseño energético del mockup (`mockup-dashboard-energetico.html`):
//      título "Asistencia de hoy", la tarjeta grande de la clase en curso con el donut SVG
//      (marcados vs cupo) y "Marcar asistencia", la tarjeta del WOD del día, "+ Agregar
//      alumno sin reserva", "Avisos para alumnos", la fila horizontal con el resto de las
//      clases del día y el gráfico de ocupación por horario;
//   2. los dos botones inline abren los modales REALES (+ Publicar WOD, + Nuevo aviso, + Agregar
//      sin reserva) y no navegan a otra pantalla;
//   3. las tarjetas hablan como el mockup y como la pestaña Asistencia: el progreso y el estado
//      salen de `utils/franjasAsistencia`, no de una copia propia ("9/14 marcados",
//      "Hecha" / "En curso" / "Pendiente");
//   4. la regla de negocio sigue en el copy: el alumno marca, el coach corrige; el crédito
//      se descuenta al RESERVAR (nunca "a medianoche", que no es lo que hace el backend);
//   5. mobile-first: el contenido se limita y se centra (no hay layout de PC inventado);
//   6. EL RESUMEN VIEJO NO EXISTE: el grid 2x2 de KPIs y su panel claro se eliminaron (ni
//      "Alumnos activos" ni "En riesgo" ni "WODs esta semana" ni sus botones);
//   7. Bloque 10: la sección de avisos lee `GET /marketing/vigentes` (abierto a cualquier
//      sesión) y publica con el aviso rápido, que fija tipo y ventana en el backend;
//   8. Bloque B: el coach del mesón entrega pedidos con el input manual (la página NO promete
//      escaneo) y el admin sigue igual (la prop del modal arranca en true).
import { readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const RESUMEN = leer('../src/components/ResumenCoach.jsx');
const DASH = leer('../src/pages/coach/DashboardCoach.jsx');
const ENTREGA = leer('../src/pages/coach/EntregarPedido.jsx');
const MODAL_ENTREGA = leer('../src/components/ModalEntregarPedido.jsx');
// Bloque 2: el aviso del walk-in pasó a ser un TOAST y el texto lo escribe el modal (pegado a
// la rama que ejecuta), no el Resumen. Se lee el modal para seguir fijando el mismo copy.
const MODAL_WALKIN = leer('../src/components/ModalAgregarSinReserva.jsx');

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

console.log('== 1. El rediseño energético (mockup dashboard-energetico) ==');
for (const id of ['coach-resumen', 'tarjeta-asistencia', 'wod-del-dia', 'resumen-avisos',
    'resumen-ocupacion', 'abrir-publicar-wod']) {
    ok(RESUMEN.includes(`data-testid="${id}"`), `el bloque "${id}" está`);
}
ok(/Asistencia de hoy/i.test(RESUMEN), 'el título dice "Asistencia de hoy"');
ok(/programada\{clasesHoy\.length === 1 \? '' : 's'\}/.test(RESUMEN),
    'el subtítulo cuenta cuántas clases hay programadas hoy');
ok(/const Donut = \(/.test(RESUMEN) && /strokeDashoffset/.test(RESUMEN),
    'el donut es SVG propio (marcados vs cupo), sin librerías');
ok(/DE \{cupo\} CUPOS/.test(RESUMEN), 'el donut grande muestra el cupo');
ok(/Marcar asistencia/.test(RESUMEN) && /data-testid="abrir-marcar-asistencia"/.test(RESUMEN),
    'el botón "Marcar asistencia" del mockup está y lleva a la pestaña Asistencia');
ok(/En curso ahora/.test(RESUMEN) && /Próxima clase/.test(RESUMEN),
    'la tarjeta distingue la clase en curso de la que sigue');
ok(/restoDelDia\.map/.test(RESUMEN) && /resumen-clases-hoy-scroll/.test(RESUMEN),
    'el resto del día va en una fila horizontal scrolleable con mini-donut');
ok(/Ocupación por horario/.test(RESUMEN) && /ocupacion\(reservasDe\(clase\), clase\.cupo_maximo\)/.test(RESUMEN),
    'el gráfico de barras reusa el helper de ocupación compartido');
eq(/kpi-clases-hoy|kpi-alumnos|kpi-riesgo/.test(RESUMEN), false,
    'sin el grid 2x2 de KPIs sueltos que reemplaza el rediseño');

console.log('== 1b. Avisos para alumnos (Bloque 10) ==');
ok(/data-testid="resumen-nuevo-aviso"/.test(RESUMEN) && /onNuevoAviso/.test(RESUMEN),
    'la sección tiene "+ Nuevo aviso"');
ok(/etiquetaTipo\(aviso\.tipo\)/.test(RESUMEN) && /resumen-lista-avisos/.test(RESUMEN),
    'lista los avisos vigentes con el nombre de su tipo (util del carrusel)');
ok(/data-testid="resumen-sin-avisos"/.test(RESUMEN), 'y su estado vacío explicado');
ok(/useAvisosMarketingVigentes/.test(DASH) && /avisos=\{avisosVigentes\}/.test(DASH),
    'el panel lee GET /marketing/vigentes (abierto a cualquier sesión autenticada)');
ok(/onNuevoAviso=\{\(\) => setModalAviso\(true\)\}/.test(DASH) && /<ModalAvisoRapido/.test(DASH),
    'y el alta es el MISMO aviso rápido (tipo `aviso` y ventana HOY: los fija el backend)');

console.log('== 2. Tarjeta grande: 3 números y el walk-in ==');
for (const t of ['con reserva', 'ya marcaron', 'faltan']) {
    ok(RESUMEN.includes(t), `la tarjeta muestra "${t}"`);
}
ok(/const conReserva = proximaClase\?\.reservas_count \?\? reservasProxima\.length/.test(RESUMEN),
    'los números salen de las reservas de ESA clase (no de un contador aparte)');
ok(/data-testid="resumen-agregar-sin-reserva"/.test(RESUMEN) && /onAgregarSinReserva\(proximaClase\)/.test(RESUMEN),
    'el botón "+ Agregar alumno sin reserva" abre el modal con la clase próxima');
ok(/data-testid="tarjeta-asistencia"/.test(RESUMEN), 'la tarjeta ancha está');
ok(/restoDelDia = clasesHoy\.filter/.test(RESUMEN),
    'el resto del día excluye la clase que ya está en la tarjeta grande');

console.log('== 3. Los textos y los estados son los del mockup ==');
ok(/textoProgreso\(proximaClase, cupo \|\| undefined\)/.test(RESUMEN),
    'la tarjeta dice el progreso con el MISMO helper de la pestaña Asistencia');
ok(/from '\.\.\/utils\/franjasAsistencia'/.test(RESUMEN),
    'el Resumen usa los helpers de la pestaña Asistencia, no una copia propia');
ok(/estadoFila\(clase\)/.test(RESUMEN) && /etiquetaEstado\(estado\)/.test(RESUMEN),
    'el badge de cada tarjeta del día sale de estadoFila/etiquetaEstado (Hecha / En curso / Pendiente)');
ok(/const esperados = reservasDe\(clase\)/.test(RESUMEN),
    'el tope del progreso sale de las reservas de ESA clase, no del cupo nominal');
eq(/medianoche[^.]{0,60}(crédito|token|plan)|(crédito|token|plan)[^.]{0,60}medianoche/i.test(RESUMEN), false,
    'el Resumen NO dice que el crédito se descuente a medianoche (se descuenta al reservar)');
// Bloque 2: el aviso del walk-in ya NO se pinta como bloque del Resumen (ahí vive el "qué
// contestó el backend" del WOD). Ahora es un TOAST y el texto sale del MODAL, que es quien
// sabe qué rama ejecutó. El invariante es el MISMO —el coach se entera de si se descontó el
// crédito—, sólo cambió de dueño: del Resumen al modal + `<Toast>`.
ok(/Se ha descontado un token del plan de \$\{a\.nombre\}/.test(MODAL_WALKIN),
    'el aviso del walk-in dice que descontó el token del plan');
ok(/quedó presente sin cargo \(queda en su historial\)/.test(MODAL_WALKIN),
    'y cuando no tiene plan, dice que quedó sin cargo');
ok(/setToastWalkin\(alumno\.mensaje\)/.test(DASH) && /<Toast texto=\{toastWalkin\} \/>/.test(DASH),
    'el Resumen muestra ese texto como toast (sobrevive al cierre del modal)');

console.log('== 4. Mobile-first declarado ==');
ok(/mx-auto max-w-3xl/.test(RESUMEN), 'el Resumen acota y centra el contenido (mobile-first)');
ok(/items-start justify-center gap-8/.test(RESUMEN),
    'la tarjeta grande apila y centra: donut, nombre, los 3 números y el botón');
ok(/flex gap-3 overflow-x-auto/.test(RESUMEN),
    'las clases del día se recorren en horizontal (sin grilla de escritorio inventada)');

console.log('== 5. Cableado y limpieza del Resumen viejo ==');
ok(/<ResumenCoach/.test(DASH) && /activeTab === 'resumen' &&/.test(DASH), 'el Resumen está montado en su pestaña');
ok(/<ModalPublicarWod/.test(DASH) && /<ModalAgregarSinReserva/.test(DASH), 'los dos modales están montados');
ok(DASH.includes('clase={wodArchivo ? null : (claseWod || proximaClase || clasesHoy[0] || null)}'),
    'el modal de WOD sabe sobre que clase publica (el lapiz de Clases elige la clase)');
ok(DASH.includes('clasesSemana={clasesSemana}'),
    'y le pasa la semana del coach: de ahi salen los horarios por franja');
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

console.log('== 6. Parte 2.2: el coach ESCANEA el código (y sigue pudiendo escribirlo) ==');
const ESCANER = leer('../src/components/EscanerCodigoRetiro.jsx');
ok(/permitirEscanear/.test(ENTREGA) && !/mencionarEscaneo=\{false\}/.test(ENTREGA),
    'la pantalla del coach habilita el lector de cámara');
ok(/📷 Escanear/.test(ENTREGA), 'y se lo cuenta al mesón en pantalla');
ok(/Ingresa\{mencionarEscaneo \? ' o escanea' : ''\}/.test(MODAL_ENTREGA),
    'el modal compone el texto según la prop (por defecto, el de siempre)');
ok(/permitirEscanear = false/.test(MODAL_ENTREGA),
    'la prop arranca en false: el admin queda igual que siempre');
ok(/data-testid="abrir-escaner-retiro"/.test(MODAL_ENTREGA) && /<EscanerCodigoRetiro/.test(MODAL_ENTREGA),
    'el modal ofrece el botón y monta el escáner');
ok(/const limpio = normalizarCodigoRetiro\(valor\)/.test(MODAL_ENTREGA)
    && /await entregarPedido\.mutateAsync\(limpio\)/.test(MODAL_ENTREGA),
    'al leer completa el input y dispara la MISMA entrega (un solo camino)');
ok((MODAL_ENTREGA.match(/<input/g) || []).length === 1,
    'el input manual sigue siendo el único input: escanear no lo reemplaza');
ok(/BarcodeDetector/.test(ESCANER) && !/jsqr|html5-qrcode|zxing/i.test(ESCANER),
    'el lector es el nativo del navegador (sin librerías nuevas)');
ok(/data-testid="escaner-volver-teclado"/.test(ESCANER),
    'y siempre se puede volver al teclado desde la cámara');

console.log('== 7. El 0 del panel explica la causa (bug de PROD) ==');
// En PROD el panel mostraba Clases hoy / Alumnos activos / En riesgo en 0 con las requests
// en 200 OK, sin decir por qué. Dos arreglos: (a) lo MÍO no se pierde aunque su disciplina no
// esté en mi lista (la clase me la asignó el admin o la tomé yo), y (b) cuando el coach no
// tiene NADA asignado, la pantalla lo dice en vez de mostrar un 0 mudo.
ok(/const esMiClase = \(c\) => coachDisciplinas\.includes\(c\.disciplina_id\)/.test(DASH),
    'el filtro local reconoce las clases de mis disciplinas');
ok(/c\.coach_id === usuario_id/.test(DASH) && /c\.horario_coach_id === usuario_id/.test(DASH),
    'y también las que me asignaron a mí y las de mi horario vigente (coach_id / horario_coach_id)');
eq(/coachDisciplinas\.length > 0[\s\S]{0,90}: lista;/.test(DASH), false,
    'sin el "si no tengo disciplinas muestro TODAS las clases del box"');
ok(/const sinAsignaciones = useMemo/.test(DASH) && /sinAsignaciones=\{sinAsignaciones\}/.test(DASH),
    'el Resumen recibe si el coach no tiene nada asignado');
ok(/sinAsignaciones = false/.test(RESUMEN), 'la prop arranca en false (nadie queda en el estado vacío)');
ok(/Todavía no tienes clases asignadas/.test(RESUMEN), 'el estado vacío lo dice cuando no hay nada asignado');
ok(/data-testid="resumen-sin-clases"/.test(RESUMEN), 'la lista "Mis clases de hoy" tiene su estado vacío');
ok(/pídele al admin que te asigne tus disciplinas u horarios/.test(RESUMEN),
    'el estado vacío dice qué hacer (y a quién pedírselo)');


console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
