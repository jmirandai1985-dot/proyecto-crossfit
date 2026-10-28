// Test aislado del stacking móvil de Avisos/Notificaciones y del orden por severidad.
//   Ejecutar:  node scripts/test-avisos-capas.mjs
//
// Sin navegador ni framework:
//   1. La campana y los modales de aviso usan capas declaradas en `utils/capas.js`.
//   2. El modal de aviso queda SIEMPRE por encima del panel de la campana (era el bug: los
//      dos usaban z-50 y el orden dependía del DOM / del `z-30` del header).
//   3. La lista de la campana se ordena por severidad (críticas primero) y luego por fecha.
import { readFileSync } from 'node:fs';

import { CLASES_CAPA, ORDEN_CAPAS } from '../src/utils/capas.js';
import {
    ordenarPorSeveridad, severidadDe, SEVERIDAD_NOTIFICACION,
} from '../src/utils/notificacionesPanel.js';

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

// ── 1. Las capas ─────────────────────────────────────────────────────────────
ok(ORDEN_CAPAS.modalAviso > ORDEN_CAPAS.notificaciones,
    `el modal de aviso (${ORDEN_CAPAS.modalAviso}) va por encima de la campana (${ORDEN_CAPAS.notificaciones})`);
ok(CLASES_CAPA.modalAviso === 'z-[60]' && CLASES_CAPA.notificaciones === 'z-50',
    'las clases son literales para que Tailwind las genere');

// ── 2. Los componentes usan las capas ────────────────────────────────────────
const modalMarketing = leer('../src/components/ModalAvisoMarketing.jsx');
const modalRapido = leer('../src/components/ModalAvisoRapido.jsx');
const campana = leer('../src/components/CampanaNotificaciones.jsx');

for (const [nombre, fuente] of [
    ['ModalAvisoMarketing.jsx', modalMarketing],
    ['ModalAvisoRapido.jsx', modalRapido],
]) {
    ok(fuente.includes("from '../utils/capas'"), `${nombre}: importa las capas`);
    ok(fuente.includes('${CLASES_CAPA.modalAviso}'), `${nombre}: el overlay usa la capa de modal`);
    ok(!/justify-center z-50 p-4/.test(fuente), `${nombre}: el overlay ya no fija z-50 a mano`);
}

ok(campana.includes('${CLASES_CAPA.notificaciones}'), 'CampanaNotificaciones: el panel usa su capa');
ok(campana.includes('ordenarPorSeveridad(filtrarVisibles('),
    'CampanaNotificaciones: ordena la lista por severidad');

// ── 3. Severidad ─────────────────────────────────────────────────────────────
ok(severidadDe({ tipo: 'rechazado' }) === 0, 'un plan rechazado es crítico');
ok(severidadDe({ tipo: 'pedido_entregado' }) === 2, 'un pedido entregado es informativo');
ok(severidadDe({ tipo: 'tipo_que_no_existe' }) === 2, 'un tipo desconocido no inventa urgencia');
ok(Object.values(SEVERIDAD_NOTIFICACION).every((n) => n >= 0 && n <= 2), 'la escala es 0..2');

const dia = (n) => new Date(2026, 9, n, 12, 0, 0).toISOString();
const original = [
    { id: 1, tipo: 'pedido_entregado', created_at: dia(28) },
    { id: 2, tipo: 'aprobado', created_at: dia(27) },
    { id: 3, tipo: 'rechazado', created_at: dia(20) },
    { id: 4, tipo: 'plan_activo', created_at: dia(26) },
];
const orden = ordenarPorSeveridad(original);
ok(orden.map((n) => n.id).join(',') === '3,2,1,4',
    'crítica vieja primero; a igual severidad, la más nueva (3,2,1,4)');
ok(original.map((n) => n.id).join(',') === '1,2,3,4', 'no muta la lista original');
ok(ordenarPorSeveridad([]).length === 0 && ordenarPorSeveridad(null).length === 0,
    'listas vacías/ausentes no rompen');
ok(ordenarPorSeveridad([{ id: 9, tipo: 'aprobado' }, { id: 8, tipo: 'aprobado', created_at: dia(1) }])
    .map((n) => n.id).join(',') === '8,9',
    'sin fecha válida queda al final de su grupo');

console.log('');
if (fallos > 0) {
    console.log(`${fallos} chequeo(s) fallaron.`);
    process.exit(1);
}
console.log('Todos los chequeos pasaron.');
