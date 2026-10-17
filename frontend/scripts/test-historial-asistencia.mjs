// Test aislado de la pestaña "Historial de Asistencia" (coach + admin) y de los DOS arreglos de
// la tarjeta grande del Resumen del coach.
//   Ejecutar:  node scripts/test-historial-asistencia.mjs   (npm run test:historial)
//
// POR QUÉ EXISTE: el Historial es la pantalla de SÓLO LECTURA del mes —pide un rango y dibuja
// anillos, calendario y detalle— y su aritmética vive afuera, en `utils/historialAsistencia.js`.
// Sin navegador ni framework se puede romper en silencio:
//   1. el BACKEND: que `/historial` deje de ser un GET puro, que se le cuele una escritura, que
//      pierda el alcance por rol o que se lleve su propia copia de los contadores (dos
//      definiciones del mismo número entre la pestaña Asistencia y el Historial);
//   2. el FRONT: que la pantalla vuelva a pedir el mes clase por clase, que se invente cuentas
//      propias en vez de usar el util puro, que le cuele un hook de escritura o que no quede
//      montada en ninguna de sus dos entradas (el menú del coach y la página del admin);
//   3. los DOS bugs de la tarjeta grande del Resumen: "Marcar asistencia" abría la pestaña sin
//      desplegar ESA clase, y "Faltan" se medía contra las reservas y no contra el CUPO.
// La matemática del util se corre DE VERDAD (es puro y no importa nada).
import { readFileSync } from 'node:fs';

import { COACH_SUBTABS, MENU_BY_ROL } from '../src/config/menu.js';
import {
    DIAS_SEMANA, MESES, aniosDisponibles, calendarioDelMes, fechaLarga, mesesDelAnio,
    porcentaje, presentesDe, resumenDia, resumenPorDiaSemana, totalesDe,
} from '../src/utils/historialAsistencia.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
// Sin comentarios: un patrón que sólo vive en un comentario no es una guarda (mismo criterio que
// los otros tests de pantalla). El texto VISIBLE de la pantalla sí se busca sobre el original.
const sinComentarios = (src) => src
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

const API = leer('../../backend/app/api/v1/asistencia.py');
const UTIL = leer('../src/utils/historialAsistencia.js');
const PANTALLA = leer('../src/components/HistorialAsistencia.jsx');
const QUERIES = leer('../src/hooks/queries.js');
const DASH = leer('../src/pages/coach/DashboardCoach.jsx');
const ADMIN = leer('../src/pages/admin/Asistencia.jsx');
// Pestaña propia del admin (Parte A): el historial ya no se apila debajo de Asistencia.
const ADMIN_HISTORIAL = leer('../src/pages/admin/HistorialAsistencia.jsx');
const CLASES = leer('../src/components/AsistenciaClases.jsx');
const RESUMEN = leer('../src/components/ResumenCoach.jsx');
const APP = leer('../src/App.jsx');

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


console.log('== 1. El util del historial es PURO (toda la matemática vive ahí) ==');
eq((UTIL.match(/^import /gm) || []).length, 0, 'el util no importa nada: se puede correr con Node tal cual');
ok(!/\b(document|window|fetch|localStorage)\b/.test(UTIL), 'no toca el DOM ni la red');
ok(/export const porcentaje = \(parte, base\)/.test(UTIL), 'exporta el % (la única definición)');
ok(/export const calendarioDelMes = \(anio, mes, clases, hoy = fechaSola\(\)\)/.test(UTIL),
    '`hoy` entra por parámetro: la grilla es pura y testeable');

console.log('== 2. El backend: un GET del mes, sin escribir nada ==');
// Los cortes se hacen sobre el archivo real, para mirar cada endpoint por separado.
const pyHist = API.slice(API.indexOf('def historial_mes('),
    API.indexOf('@router.get("/clases/{clase_id}/alumnos"', API.indexOf('def historial_mes(')));
const pyHoy = API.slice(API.indexOf('def clases_hoy('), API.indexOf('def historial_mes('));
const pyHelper = API.slice(API.indexOf('def _contadores_de_clases('), API.indexOf('def clases_hoy('));
ok(pyHist.length > 0 && pyHoy.length > 0 && pyHelper.length > 0,
    'los tres pedazos de asistencia.py se ubicaron (historial / clases-hoy / helper)');
ok(API.includes('@router.get("/historial")\ndef historial_mes('), 'GET /historial es el endpoint del mes');
for (const metodo of ['post', 'put', 'patch', 'delete']) {
    ok(!API.includes(`@router.${metodo}("/historial")`), `no hay @router.${metodo}("/historial")`);
}
for (const marca of ['db.commit(', 'db.flush(', 'db.add(', 'db.delete(', 'db.execute(',
    'update(', 'registrar_auditoria(']) {
    ok(!pyHist.includes(marca), `el endpoint no llama a ${marca}`);
}
ok(!/BackgroundTasks/.test(pyHist), 'no agenda trabajo de fondo (leer no encola nada)');
ok(/Depends\(get_current_coach\)/.test(pyHist), 'lo sirve el guard del coach (coach + admin, no el alumno)');
ok(/anio: int = Query\(\.\.\., ge=2000, le=2100/.test(pyHist)
    && /mes: int = Query\(\.\.\., ge=1, le=12/.test(pyHist),
    'anio/mes los valida FastAPI: un mes con basura da 422, no una consulta rara');
ok(/Clase\.cancelada == False/.test(pyHist), 'las clases canceladas quedan fuera (no bajan el % del día)');
ok(/"alcance": "coach" if rol == "coach" else "box"/.test(pyHist), 'el alcance por rol viaja en la respuesta');
ok(/condicion_mis_clases\(current_user\["usuario_id"\]\)/.test(pyHist),
    'el coach ve lo suyo con la MISMA definición de "mis clases" que /clases-hoy');
ok(/GET  \/historial/.test(API), 'el router lo documenta en su docstring (como el resto)');

console.log('== 2b. Los contadores del mes son los MISMOS del día ==');
eq((API.match(/def _contadores_de_clases\(/g) || []).length, 1, 'el helper está definido UNA sola vez');
ok(/_contadores_de_clases\(db, ids\)/.test(pyHist), 'el mes lo usa');
ok(/_contadores_de_clases\(db, ids\)/.test(pyHoy), 'y la pestaña Asistencia (el día) también');
ok(/no_cancelada\(Reserva\.estado\)/.test(pyHelper), 'una reserva cancelada no es un cupo ocupado');
ok(/Reserva\.asistio\.is_\(True\)/.test(pyHelper), '`marcados_count` sale de `asistio`, como el Resumen');
ok(/Reserva\.asistencia_marcada_at\.is_\(None\)/.test(pyHelper),
    'una clase con reservas sin marcar NO es "marcada" (es la que está pendiente)');
ok(!/"faltan"/.test(pyHelper), 'al backend no le toca calcular "faltan" (es aritmética de presentación)');

console.log('== 2c. La respuesta lleva HECHOS y ningún porcentaje ==');
for (const hecho of ['"cupo_maximo":', '"reservas_count":', '"marcados_count":', '"marcada":',
    '"alumnos":', '"estado":', '"disciplina_nombre":']) {
    ok(pyHist.includes(hecho), `la respuesta del mes trae ${hecho}`);
}
ok(/"asistio": bool\(r\.asistio\)/.test(pyHist), 'cada alumno viaja con su `asistio` (el ✓/✗ del detalle)');
for (const prohibido of ['"pct"', '"porcentaje"', '* 100']) {
    ok(!pyHist.includes(prohibido), `${prohibido} no viaja: el % se calcula UNA vez, en el front`);
}
ok(/estado_clase\(/.test(pyHist), 'el estado de cada clase lo decide el helper compartido de `clases_service`');
eq((pyHist.match(/ahora_santiago\(\)/g) || []).length, 1,
    'una sola lectura del reloj para todo el mes (dos clases del mismo día no pueden discrepar)');
ok(/primer_dia = date\(anio, mes, 1\)/.test(pyHist)
    && /date\(anio, 12, 31\) if mes == 12/.test(pyHist)
    && /date\(anio, mes \+ 1, 1\) - timedelta\(days=1\)/.test(pyHist),
    'el rango del mes es inclusivo de punta a punta (diciembre corta el 31, no pide el mes 13)');

console.log('== 3. El mes se pide UNA vez (y el detalle de un día no vuelve a la API) ==');
ok(/historialAsistencia: \(anio, mes\) => \['asistencia', 'historial', anio, mes\]/.test(QUERIES),
    'la clave del mes cuelga de [\'asistencia\'] (confirmar hoy refresca el mes abierto)');
ok(/export function useHistorialAsistencia\(anio, mes\)/.test(QUERIES), 'el hook del mes existe');
ok(QUERIES.includes("api.get('/api/v1/asistencia/historial'") && /params: \{ anio: a, mes: m \}/.test(QUERIES),
    'pega al endpoint del mes con `anio` y `mes`');
ok(/enabled: valido/.test(QUERIES), 'con un mes a medio armar no dispara el request (`enabled`)');

const pantallaCodigo = sinComentarios(PANTALLA);
ok(!/services\/api/.test(PANTALLA), 'la pantalla no importa `services/api` (todo pasa por el hook)');
ok(!/api\./.test(pantallaCodigo) && !/fetch\(/.test(pantallaCodigo), 'y no hace requests propias');
const hooksUsados = [...pantallaCodigo.matchAll(/\b(use[A-Z][A-Za-z0-9]*)\s*\(/g)].map((m) => m[1]);
const buscarDatos = hooksUsados.filter((h) => !['useState', 'useMemo', 'useEffect', 'useRef',
    'useCallback', 'useContext'].includes(h));
eq(JSON.stringify([...new Set(buscarDatos)]), JSON.stringify(['useHistorialAsistencia']),
    'una sola consulta para todo el mes: abrir un día NO vuelve a la API');

console.log('== 4. La pantalla es de SÓLO LECTURA ==');
for (const escritura of ['useMutation', 'useConfirmarAsistencia', 'useAmpliarCupo',
    'ModalAgregarSinReserva', 'AsistenciaClases']) {
    ok(!pantallaCodigo.includes(escritura), `no monta ${escritura} (marcar sigue en la pestaña Asistencia)`);
}
ok(/useHistorialAsistencia\(anio, mes\)/.test(pantallaCodigo), 'lee el mes con el hook del historial');
ok(PANTALLA.includes('sólo lectura: acá no se marca asistencia'),
    'y lo dice en pantalla (el usuario no tiene que adivinar por qué no hay botones)');
const importados = (PANTALLA.match(/\{([^}]+)\}\s*from '\.\.\/utils\/historialAsistencia'/) || [null, ''])[1]
    .split(',').map((s) => s.trim()).filter(Boolean);
eq(importados.length, 9, `la pantalla importa sus ${importados.length} helpers del util COMPARTIDO`);
for (const nombre of importados) {
    ok(new RegExp(`export const ${nombre} =`).test(UTIL), `el util exporta ${nombre} (lo que usa existe)`);
}
for (const marca of ['historial-selector-mes', 'historial-selector-anio', 'historial-anillo-',
    'historial-dia-', 'historial-detalle-dia', 'historial-bloque-']) {
    ok(PANTALLA.includes(marca), `la pantalla tiene ${marca} (los tres niveles del mes)`);
}

console.log('== 5. Está montada en sus DOS entradas (coach y admin) ==');
const sub = COACH_SUBTABS.find((s) => s.key === 'historial');
ok(sub, 'COACH_SUBTABS declara la sub-pestaña `historial`');
eq(sub?.path, '/coach/dashboard?tab=historial', 'y navega a su propio query');
eq(COACH_SUBTABS.length, 7, 'el menú del coach sigue teniendo 7 pestañas (se sumó una, no se cambió otra)');
ok(DASH.includes('activeTab === \'historial\''), 'DashboardCoach tiene su rama de contenido');
ok(/import HistorialAsistencia from '\.\.\/\.\.\/components\/HistorialAsistencia'/.test(DASH)
    && DASH.includes('<HistorialAsistencia />'), 'y monta el componente (import + render)');
ok(DASH.includes("activeTab === 'resumen' || activeTab === 'historial'"),
    'el Historial va sobre el fondo oscuro del Layout (como el Resumen, sin panel claro)');
ok(/import HistorialAsistencia from '\.\.\/\.\.\/components\/HistorialAsistencia'/.test(ADMIN_HISTORIAL)
    && ADMIN_HISTORIAL.includes('<HistorialAsistencia />'),
    'la pestaña Historial del admin monta el MISMO componente compartido');
ok(ADMIN_HISTORIAL.includes('<Layout>'),
    'y vive dentro del Layout del panel (pestaña propia, no apilada)');
ok(!/import\s+HistorialAsistencia/.test(ADMIN) && !/<HistorialAsistencia\s*\/>/.test(ADMIN),
    'la página Asistencia ya NO apila el historial (se separó en su pestaña)');
ok(ADMIN.includes('<AsistenciaClases variant="dark" />'),
    'sin tocar el marcado del admin (el componente compartido sigue montado igual)');
const itemHistorialAdmin = MENU_BY_ROL.administrador.find((i) => i.path === '/admin/historial');
ok(itemHistorialAdmin && itemHistorialAdmin.label === 'Historial',
    'el menú del admin tiene la entrada "Historial" -> /admin/historial');
eq((APP.match(/path="historial"/g) || []).length, 1,
    'la ruta del admin existe (una sola: el coach navega por query)');
ok(APP.includes("import('./pages/admin/HistorialAsistencia')"),
    'y la ruta carga la página propia del admin (chunk lazy)');

console.log('== 6. La matemática del util, corrida de verdad ==');
eq(porcentaje(0, 0), 0, 'sin cupos (base 0) el porcentaje es 0, no NaN');
eq(porcentaje(3, 16), 19, '3 presentes de 16 cupos = 19%');
eq(porcentaje(99, 10), 100, 'más presentes que cupos no pasa de 100%');

// Una clase real del mes: 16 cupos, 4 reservas y 4 alumnos (3 vinieron, 1 no). 2026-10-05 = lunes.
const CLASE = {
    id: 7, fecha: '2026-10-05', hora_inicio: '19:00', hora_fin: '20:00', disciplina_nombre: 'WOD',
    coach: 'Seba', cupo_maximo: 16, reservas_count: 4, marcados_count: 3, marcada: false,
    estado: 'realizada',
    alumnos: [
        { alumno_id: 1, nombre: 'Ana', asistio: true },
        { alumno_id: 2, nombre: 'Beto', asistio: true },
        { alumno_id: 3, nombre: 'Cami', asistio: true },
        { alumno_id: 4, nombre: 'Dani', asistio: false },
    ],
};
eq(presentesDe(CLASE), 3, '"presente" sale de `marcados_count` (el MISMO dato del Resumen del coach)');
eq(presentesDe({ ...CLASE, marcados_count: undefined }), 3,
    'sin el contador (backend viejo) se cuenta con la lista de alumnos');
eq(presentesDe({}), 0, 'una clase vacía no devuelve NaN');

const tot = totalesDe([CLASE]);
eq(tot.clases, 1, 'el mes cuenta sus clases');
eq(tot.presentes, 3, 'los presentes del mes suman los de cada clase');
eq(tot.ausentes, 1, 'ausente = reservó y no llegó (el coach tiene que verlo)');
eq(tot.reservas, 4, 'las reservas vigentes del mes');
eq(tot.cupos, 16, 'los cupos del mes (el denominador del %)');
eq(tot.libres, 12, 'los cupos que quedaron libres');
eq(tot.pct, 19, 'el % del mes es contra los CUPOS: la misma cuenta del anillo del Resumen');
eq(tot.cerradas, 0, 'una clase con reservas sin marcar NO cuenta como cerrada');
eq(totalesDe([]).pct, 0, 'un mes sin clases no divide por cero');
eq(totalesDe([CLASE, { ...CLASE, id: 8, marcados_count: 16, marcada: true }]).pct, 59,
    'dos clases se suman antes de sacar el % (no se promedian porcentajes)');

const anillos = resumenPorDiaSemana([CLASE]);
eq(anillos.length, 7, 'los 7 anillos se dibujan siempre (aunque el día esté vacío)');
eq(anillos[0].clave, 'lun', 'la semana empieza el lunes (misma regla que la grilla del coach)');
eq(anillos[0].totales.clases, 1, 'la clase del lunes cae en el anillo del lunes');
eq(anillos[1].totales.clases, 0, 'y los demás días quedan en cero, sin esconderse');
eq(anillos[0].pct, 19, 'cada anillo trae el % que dibuja el arco');
eq(anillos[0].alumnosPresentes.length, 3, 'el anillo abre la lista de quiénes vinieron');
eq(anillos[0].alumnosAusentes.length, 1, 'y la de quiénes no');

const semanas = calendarioDelMes(2026, 10, [CLASE], '2026-10-16');
eq(semanas.length, 5, 'octubre 2026 entra en 5 semanas (lunes primero)');
ok(semanas.every((s) => s.length === 7), 'todas las filas del calendario tienen 7 celdas');
eq(semanas[0][0], null, 'el hueco previo al día 1 es una celda VACÍA (no un día de otro mes)');
const dias = semanas.flat().filter(Boolean);
eq(dias.length, 31, 'octubre tiene 31 días (el último día sale del calendario, no de una lista)');
eq(dias.find((c) => c.hoy).dia, 16, 'el día de hoy queda marcado con `hoy`');
ok(dias.find((c) => c.dia === 17).esFuturo,
    'un día que todavía no ocurrió queda `esFuturo` (sin asistencia que mirar)');
ok(!dias.find((c) => c.dia === 15).esFuturo, 'y uno que ya pasó, no');
eq(dias.find((c) => c.dia === 5).totales.pct, 19, 'cada celda trae el % del día (la misma cuenta que los anillos)');
eq(dias.find((c) => c.dia === 6).totales.clases, 0, 'y los días sin clases quedan en cero');
eq(calendarioDelMes(2026, 11, [], '2026-11-10').flat().filter(Boolean).length, 30, 'noviembre tiene 30 días');
eq(calendarioDelMes(2026, 13, [], '2026-10-16').length, 0, 'un mes inválido no arma grilla (no revienta)');
eq(calendarioDelMes('2026', '10', [], '2026-10-16').length, 5,
    'el mes que llega del <select> como string también sirve');

const detalle = resumenDia([CLASE], '2026-10-05');
eq(detalle.fichas.length, 1, 'el detalle del día trae una ficha por bloque horario');
eq(detalle.fichas[0].hora, '19:00', 'la ficha muestra la hora del backend recortada a HH:MM');
eq(detalle.fichas[0].disciplina, 'WOD', 'y la disciplina de la clase');
eq(detalle.fichas[0].pct, 19, 'la ficha del bloque cuenta igual que el resto de la pantalla');
eq(detalle.titulo, 'Lunes 5 de octubre', 'el día se titula en castellano, sin `Date` (no lo corre la zona horaria)');
eq(resumenDia([CLASE], '2026-10-06').fichas.length, 0, 'un día sin clases no tiene fichas');
eq(mesesDelAnio().length, 12, 'el selector de meses tiene los 12');
eq(JSON.stringify(aniosDisponibles(2026)), JSON.stringify([2026, 2025, 2024]),
    'el selector de años ofrece el actual y los 2 anteriores');
eq(JSON.stringify(DIAS_SEMANA.map((d) => d.clave)),
    JSON.stringify(['lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom']), 'los 7 días van de lunes a domingo');
eq(MESES.length, 12, 'los meses están completos (sin huecos en el arreglo)');

console.log('== 7. "Marcar asistencia" abre ESA clase (bug de la tarjeta grande) ==');
ok(/onClick=\{\(\) => onAbrirAsistencia && onAbrirAsistencia\(proximaClase\)\}/.test(RESUMEN),
    'la tarjeta grande le pasa la clase al callback');
ok(!/onClick=\{onAbrirAsistencia\}/.test(RESUMEN),
    'ya no está el onClick sin argumento (abría la pestaña sin desplegar ninguna clase)');
ok(/`onAbrirAsistencia\(clase\)`/.test(RESUMEN), 'y la prop se documenta como `onAbrirAsistencia(clase)`');
ok(/const irAMarcarAsistencia = \(clase\) => \{/.test(DASH),
    'DashboardCoach arma el destino con la clase pedida');
ok(DASH.includes('`/coach/dashboard?tab=asistencia&clase=${id}`'), 'el id viaja en el query (`?clase=`)');
ok(DASH.includes(": '/coach/dashboard?tab=asistencia');"),
    'sin id cae a la pestaña a secas (no navega a una URL rota)');
ok(/onAbrirAsistencia=\{irAMarcarAsistencia\}/.test(DASH), 'y es lo que recibe el Resumen');
ok(/import \{ useLocation \} from 'react-router-dom'/.test(CLASES),
    'AsistenciaClases lo lee del router (sin props nuevas)');
ok(/new URLSearchParams\(location\.search\)\.get\('clase'\)/.test(CLASES), 'lee el `?clase=` del query');
ok(/const encontrada = clases\.find\(\(c\) => String\(c\.id\) === clasePedida\)/.test(CLASES),
    'busca ESA clase en la lista del día');
ok(/pedidoAbiertoRef\.current === location\.key/.test(CLASES),
    'un refetch no reabre el modal que el usuario cerró (guardia por `location.key`)');
ok(/if \(!clasePedida \|\| cargando\) return;/.test(CLASES),
    'espera a que llegue la lista del día antes de abrir (si no, no encuentra nada)');
ok(/const AsistenciaClases = \(\{ variant = 'light', franjas = false, permitirSinReserva = false \} = \{\}\)/
    .test(CLASES), 'la firma del componente compartido no cambió (tests de franjas / walk-in)');

console.log('== 8. "Faltan" se mide contra el CUPO (bug de la tarjeta grande) ==');
const filaCupo = RESUMEN.indexOf('const cupo = Number(proximaClase?.cupo_maximo) || 0;');
const filaYa = RESUMEN.indexOf('const yaMarcaron = reservasProxima.filter((r) => r.asistio).length;');
const filaFaltan = RESUMEN.indexOf('const faltan = Math.max((cupo || conReserva) - yaMarcaron, 0);');
ok(filaCupo > -1, 'la tarjeta grande lee el CUPO de la clase');
ok(filaYa > -1, '"ya marcaron" sale de las reservas de ESA clase (no de un contador aparte)');
ok(filaFaltan > filaCupo && filaFaltan > filaYa,
    'las tres cuentas están y en orden (cupo → ya marcaron → faltan)');
ok(!/const faltan = Math\.max\(conReserva - yaMarcaron, 0\)/.test(RESUMEN),
    'se fue la cuenta vieja: medía contra las reservas y una clase de 16 cupos con 3 marcas decía "faltan 1"');
ok(/textoProgreso\(proximaClase, cupo \|\| undefined\)/.test(RESUMEN),
    'el pie de la tarjeta usa ese MISMO cupo: el texto y el número no pueden contar distinto');
ok(/aria-label=\{`\$\{marcados\} de \$\{cupo\} cupos`\}/.test(RESUMEN),
    'y el donut también (los tres comparten el cupo de la clase)');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);

