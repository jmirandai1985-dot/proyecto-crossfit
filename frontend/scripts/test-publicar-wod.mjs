// Test aislado del modal "Publicar WOD" + carga del archivo semanal (Bloque D).
//   Ejecutar:  node scripts/test-publicar-wod.mjs   (npm run test:publicar-wod)
//
// POR QUÉ EXISTE: el modal publica entrenamientos para TODA la semana (y avisos con fecha)
// reusando endpoints que ya estaban en producción. Sus piezas:
//   1. "Aplicar a" usa el `clase_ids` de batch-create: [esta clase] sólo en "este horario";
//      "todo el día" y "la semana" van SIN `clase_ids` (todas las clases de cada fecha);
//   2. la semana es LUNES→DOMINGO y sale del util compartido (`utils/fecha.semanaEnCurso`);
//   3. el aviso del día reusa el aviso rápido del coach (mismo endpoint), no uno nuevo;
//   4. el archivo se previsualiza (no escribe) y sólo "Programar semana" publica;
//   5. el backend que lo recibe es del coach, valida la disciplina y guarda la semana +
//      los avisos en UNA transacción.
import { readFileSync, existsSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const MODAL = leer('../src/components/ModalPublicarWod.jsx');
const FECHA = leer('../src/utils/fecha.js');
const HOOKS = leer('../src/hooks/queries.js');
const WODS_API = leer('../../backend/app/api/v1/wods.py');
const SERVICIO = leer('../../backend/app/services/wod_semana.py');
const AVISOS = leer('../../backend/app/services/avisos_marketing.py');

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

console.log('== 1. Formulario manual: reusa batch-create y su alcance ==');
ok(/useCrearWodsBatch/.test(MODAL) && /crearBatch\.mutateAsync\(\{[\s\S]*params: \{ disciplina_id/
    .test(MODAL), 'publica con POST /wods/batch-create (el endpoint de Gestión de Clases)');
// Bloque 1: los horarios elegidos son los que viajan como `clase_ids` (una clase por dia);
// "Todos los horarios" omite la clave a proposito (el backend vincula todas las clases).
ok(MODAL.includes('if (planPublicacion.claseIds) body.clase_ids = planPublicacion.claseIds;'),
    'los horarios elegidos = solo esas clases (`clase_ids`); "todos" va sin el');
ok(MODAL.includes('wods: planPublicacion.fechas.map((fecha) => ({'),
    'un WOD por cada dia que se va a publicar (los que marca la grilla)');
ok(/fuerza_habilidad: form\.musculacion\.trim\(\)/.test(MODAL)
    && /wod_principal: form\.wod_descripcion\.trim\(\)/.test(MODAL),
    'musculación → fuerza_habilidad y descripción → wod_principal');
ok(/'publicado'/.test(MODAL), 'el WOD sale publicado (se ve el día que le toca)');

console.log('== 2. La semana sale del util compartido (lunes→domingo) ==');
ok(/import \{[^}]*\bsemanaEnCurso\b[^}]*\} from '\.\.\/utils\/fecha'/.test(MODAL),
    'el modal no calcula fechas: usa `utils/fecha.semanaEnCurso`');
ok(/export function semanaEnCurso/.test(FECHA) && /lunes→domingo/.test(FECHA),
    'el util documenta y aplica la regla lunes→domingo');

console.log('== 3. El aviso es el MISMO del aviso rápido ==');
ok(/usePublicarAvisoRapido/.test(MODAL) && /avisoRapido\.mutateAsync\(/.test(MODAL),
    'publica el aviso por POST /marketing/aviso-rapido (sin endpoint nuevo)');
ok(/Aviso que verán los alumnos hoy/.test(MODAL),
    'el campo dice "hoy" (el aviso rápido es del día, también con "la semana")');

console.log('== 4. El archivo: vista previa primero, programar después ==');
ok(/accept="\.xlsx"/.test(MODAL), 'sólo acepta .xlsx');
ok(/usePrevisualizarSemana/.test(MODAL) && /useProgramarSemana/.test(MODAL),
    'usa la vista previa y el programar (dos pasos, como el mockup)');
ok(/data-testid="previa-semana"/.test(MODAL) && /data-testid="programar-semana"/.test(MODAL),
    'la vista previa y el botón "Programar semana" están');
ok(/data-testid="errores-archivo"/.test(MODAL), 'los errores del archivo se muestran');
ok(/Cancelar y volver al formulario manual/.test(MODAL), 'se puede volver al formulario manual');
ok(/fecha \| calentamiento \| musculacion \| wod_nombre \| wod_tipo \| wod_descripcion \| aviso/
    .test(MODAL), 'la ayuda muestra el ORDEN exacto de las columnas');

console.log('== 5. Hooks: los endpoints correctos ==');
ok(/api\.post\('\/api\/v1\/wods\/semana-archivo', datos/.test(HOOKS)
    && /multipart\/form-data/.test(HOOKS), 'la vista previa sube el .xlsx como multipart');
ok(/api\.post\(\s*'\/api\/v1\/wods\/programar-semana'/.test(HOOKS), 'el programar usa su endpoint');
ok(/qc\.invalidateQueries\(\{ queryKey: \['marketing'\] \}\)/.test(HOOKS),
    'programar la semana refresca también el carrusel de avisos del alumno');

console.log('== 6. Backend: endpoints, permisos y una sola transacción ==');
ok(WODS_API.includes('@router.post("/semana-archivo"'), 'existe POST /wods/semana-archivo');
ok(WODS_API.includes('@router.post("/programar-semana"'), 'existe POST /wods/programar-semana');
ok(/verificar_coach_disciplina\(\s*\n\s*coach_id, disciplina_id, db/.test(WODS_API),
    'valida la disciplina del coach (mismo filtro que POST /wods)');
ok(/nueva_wod = _crear_wod_obj\(db, tenant_id, wd\)/.test(WODS_API),
    'los WODs se crean con la MISMA función que batch-create');
ok(/db\.add\(AvisoMarketing\(/.test(WODS_API) && /db\.rollback\(\)/.test(WODS_API),
    'los avisos entran en la misma transacción (y hay rollback)');
ok(/payload_aviso_de_fecha/.test(AVISOS) && /rango_vigencia\(fecha, fecha\)/.test(AVISOS),
    'la ventana del aviso del día la arma `rango_vigencia` (una sola definición)');
ok(/def payloads_de_semana/.test(SERVICIO) && /TIPO_OTRO/.test(SERVICIO),
    'el mapeo a la tabla y el "Otro" viven en el servicio');
ok(existsSync(new URL('../../backend/tests/test_wod_semana.py', import.meta.url)),
    'el parseo tiene su test puro (sin base de datos)');
ok(/def leer_archivo/.test(SERVICIO) && /load_workbook/.test(SERVICIO),
    'el parseo usa openpyxl (ya estaba en requirements por los reportes)');


console.log('== 6. Bloque 1: una sola UI de entrada (dias + horarios por franja) ==');
ok(MODAL.includes('data-testid="wod-dias"') && MODAL.includes('data-testid={`wod-dia-${fecha}`}'),
    'el modo manual trae la grilla de dias de la semana (Lun-Dom)');
ok(MODAL.includes('const lunesDeLaSemana = useMemo(() => semanaEnCurso(fechaClase)'),
    'la grilla es la semana en curso del util compartido (lunes a domingo)');
ok(MODAL.includes("from '../utils/franjasAsistencia'") && MODAL.includes('franjaDe(h) === f.id'),
    'los horarios se agrupan por franja con el util compartido (Manana/Tarde/Noche)');
ok(MODAL.includes('data-testid="alcance-todos"'),
    '"Todos los horarios" publica en todas las clases de cada dia (sin `clase_ids`)');
ok(MODAL.includes('data-testid={`horario-${h}`}'),
    'y cada horario se puede elegir por separado');
ok(MODAL.includes('data-testid="dias-sin-horario"'),
    'un dia marcado sin clase a ese horario avisa que NO se publica (no se crea un WOD suelto)');
ok(MODAL.includes('clasesSemana = []'),
    'la semana llega por prop (el panel ya la tiene): sin ella queda el horario de la clase');
const DASH = leer('../src/pages/coach/DashboardCoach.jsx');
eq((DASH.match(/<ModalPublicarWod/g) || []).length, 1,
    'el Resumen y la pestana Clases montan el MISMO modal (una sola montura en el panel)');
ok(DASH.includes('onClick={() => { setClaseWod(clase); setModalWod(true); }}'),
    'el lapiz de la pestana Clases abre ESE modal con su horario');
eq(DASH.includes('gestion-clases?fecha=${fechaISO}&clase='), false,
    'la celda de Clases ya no manda al formulario viejo');
// El modo EDICIÓN (antes: el formulario viejo de Gestión de Clases, ya retirada) vive en el
// mismo modal: se pre-carga con el WOD publicado y guarda con `PUT /wods/{id}`.
ok(MODAL.includes('wodEdicion') && MODAL.includes('useGuardarWod')
    && MODAL.includes('wodId: wodEdicion.id'),
    'editar un WOD publicado es un modo del mismo modal (PUT, sin crear otro WOD)');
ok(DASH.includes('abrirEditarWod') && DASH.includes('wodEdicion={wodEdicion}'),
    'el panel lo abre desde la grilla (✏️) y desde el detalle del WOD');
ok(DASH.includes('abrirCargaMasiva') && DASH.includes('soloArchivo={wodArchivo}'),
    'la carga masiva del Excel entra por el MISMO modal, sin clase');


console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
