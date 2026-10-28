// Test aislado de las reglas puras del padrón de alumnos — `src/utils/alumnos.js`.
//   Ejecutar:  node scripts/test-alumnos.mjs
//
// Estas reglas estaban DENTRO de `pages/admin/Alumnos.jsx` y ahora las comparten la
// tabla de escritorio (≥768px) y la vista móvil del padrón (<768px, A5). Acá se fija
// el contrato que ambas tienen que cumplir, sin navegador ni framework:
//   1. vigencia de la suscripción por DÍA CHILENO (el día de vencimiento vale completo)
//   2. de varias vigentes manda la del vencimiento más lejano (criterio del backend)
//   3. la suscripción de UN alumno se busca por `usuario_id`, no por el id de la fila
//   4. params del padrón paginado: skip correcto y `buscar` que no viaja vacío
//   5. badge de estado: mismos textos y mismas clases de siempre
//   6. el tramo pedido FUERA DE RANGO retrocede al último válido (no deja la tabla vacía)
//   7. el "Mostrando A-B de N" del pie (última página incompleta incluida)
//   9. qué solicitud abre el modal "Voucher": la del ARCHIVO real (pendiente primero) y
//      `null` cuando el alumno nunca subió comprobante (antes se inventaba uno)
import {
    badgeEstado, estadoSolicitudPlan, nombrePlan, paginaFueraDeRango, paginaValida, paramsAlumnos,
    rangoMostrado, solicitudConComprobante, suscripcionDeAlumno, suscripcionVigente,
    suscripcionVigenteHoy, totalPaginas,
} from '../src/utils/alumnos.js';
import { sumarDiasInstante } from '../src/utils/fecha.js';

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

// Instantes relativos a AHORA (en días): se usan instantes ISO, que es lo que manda
// el backend en `fecha_expiracion`.
const ayer = sumarDiasInstante(new Date(), -1);
const manana = sumarDiasInstante(new Date(), 1);
const enUnaSemana = sumarDiasInstante(new Date(), 7);
const vencida = { id: 1, usuario_id: 9, fecha_expiracion: ayer.toISOString() };
const vigenteCorta = { id: 2, usuario_id: 9, fecha_expiracion: manana.toISOString() };
const vigenteLarga = { id: 3, usuario_id: 9, fecha_expiracion: enUnaSemana.toISOString() };
const sinFecha = { id: 4, usuario_id: 9, fecha_expiracion: null };

console.log('== 1. Vigencia por día chileno ==');
ok(suscripcionVigenteHoy(new Date()), 'un vencimiento de HOY está vigente (el día vale completo)');
ok(suscripcionVigenteHoy(manana), 'un vencimiento de mañana está vigente');
ok(!suscripcionVigenteHoy(ayer), 'un vencimiento de ayer NO está vigente');
ok(!suscripcionVigenteHoy(null), 'vencimiento NULL -> no vigente');
ok(!suscripcionVigenteHoy(undefined), 'vencimiento ausente -> no vigente');
ok(!suscripcionVigenteHoy(''), 'vencimiento vacío -> no vigente (nunca "vigente por accidente")');
ok(!suscripcionVigenteHoy('no-es-fecha'), 'fecha inválida -> no vigente');

console.log('\n== 2. De varias, la vigente con el vencimiento más lejano ==');
eq(suscripcionVigente([]), null, 'lista vacía -> null');
eq(suscripcionVigente(), null, 'lista ausente -> null (no explota)');
eq(suscripcionVigente([vencida]), null, 'sólo vencidas -> null');
eq(suscripcionVigente([vencida, vigenteCorta]), vigenteCorta, 'mezcla vencida+vigente -> la vigente');
eq(suscripcionVigente([vigenteCorta, vigenteLarga]), vigenteLarga, 'dos vigentes -> la de vencimiento más lejano');
eq(suscripcionVigente([vigenteLarga, sinFecha]), vigenteLarga, 'una fila sin fecha no gana');
eq(suscripcionVigente([sinFecha]), null, 'la única fila no tiene fecha -> null');
ok(suscripcionVigente([vigenteCorta, vigenteLarga]) === vigenteLarga, 'devuelve el OBJETO de la lista (no una copia)');

console.log('\n== 3. La suscripción de UN alumno (columna Plan Activo) ==');
const listaBox = [
    { id: 10, usuario_id: 1, plan_id: 5 },
    { id: 11, usuario_id: 2, plan_id: 6 },
];
eq(suscripcionDeAlumno(listaBox, 2), listaBox[1], 'busca por `usuario_id` (no por el id de la suscripción)');
eq(suscripcionDeAlumno(listaBox, 10), null, 'el id de la SUSCRIPCIÓN no cuenta como alumno');
eq(suscripcionDeAlumno(listaBox, 99), null, 'alumno sin plan -> null');
eq(suscripcionDeAlumno(undefined, 1), null, 'lista ausente (suscripciones cargando) -> null');
eq(suscripcionDeAlumno([], 1), null, 'lista vacía -> null');

console.log('\n== 4. Nombre del plan (con catálogo incompleto) ==');
eq(nombrePlan([{ id: 5, nombre: 'Crossfit Ilimitado' }], 5), 'Crossfit Ilimitado', 'plan en el catálogo -> su nombre');
eq(nombrePlan([], 5), 'Plan ID 5', 'plan fuera del catálogo -> "Plan ID 5" (nunca vacío)');
eq(nombrePlan(undefined, 7), 'Plan ID 7', 'catálogo ausente -> "Plan ID 7"');
eq(nombrePlan([{ id: '5', nombre: 'otro' }], 5), 'Plan ID 5', 'sólo id estricto (5 no es "5")');

console.log('\n== 5. Badge de estado ==');
eq(badgeEstado({ estado: 'activo' }), { texto: 'activo', clase: 'bg-green-100 text-green-800' }, 'activo -> verde');
eq(badgeEstado({ estado: 'pendiente_activacion' }), { texto: 'pendiente', clase: 'bg-amber-100 text-amber-800' }, 'pendiente_activacion -> "pendiente" ámbar');
eq(badgeEstado({ estado: 'rechazado' }), { texto: 'rechazado', clase: 'bg-red-100 text-red-800' }, 'rechazado -> rojo');
eq(badgeEstado({ estado: 'baja' }), { texto: 'baja', clase: 'bg-zinc-700 text-zinc-300' }, 'baja -> gris');
eq(badgeEstado({ activo: true }), { texto: 'activo', clase: 'bg-green-100 text-green-800' }, 'sin `estado` pero activo -> activo (flag derivado)');
eq(badgeEstado({}), { texto: 'baja', clase: 'bg-zinc-700 text-zinc-300' }, 'sin `estado` ni `activo` -> baja');
eq(badgeEstado({ estado: 'activo', activo: false }), { texto: 'activo', clase: 'bg-green-100 text-green-800' }, 'manda `estado`, no el flag');

console.log('\n== 6. Params del padrón paginado (server-side) ==');
eq(paramsAlumnos(), { rol: 'alumno', limit: 25, skip: 0, buscar: undefined }, 'default: alumnos, 25 por página, página 1, sin búsqueda');
eq(paramsAlumnos({ rol: 'coach' }).rol, 'coach', 'el rol viaja (el padrón de coaches usa el mismo hook)');
eq(paramsAlumnos({ pagina: 3, porPagina: 25 }).skip, 50, 'página 3 de 25 -> skip 50');
eq(paramsAlumnos({ pagina: 2, porPagina: 50 }).skip, 50, 'página 2 de 50 -> skip 50');
eq(paramsAlumnos({ pagina: 0 }).skip, 0, 'página 0 (borde) -> skip 0, nunca negativo');
eq(paramsAlumnos({ buscar: '  Ana  ' }).buscar, 'Ana', 'la búsqueda viaja recortada');
eq(paramsAlumnos({ buscar: '   ' }).buscar, undefined, 'búsqueda en blanco -> undefined (no viaja el param)');
ok('buscar' in paramsAlumnos({ buscar: 'x' }), 'la clave `buscar` existe (axios omite el undefined)');

console.log('\n== 7. Paginación: tramo fuera de rango retrocede ==');
eq(totalPaginas(0, 25), 1, 'sin resultados -> 1 página (nunca 0)');
eq(totalPaginas(25, 25), 1, 'justo una página llena -> 1');
eq(totalPaginas(26, 25), 2, '26 -> 2 páginas');
eq(totalPaginas(60, 25), 3, '60 con 25 -> 3 páginas');
ok(!paginaFueraDeRango(1, 60, 25), 'página 1 de 3 está dentro');
ok(!paginaFueraDeRango(3, 60, 25), 'página 3 de 3 está dentro');
ok(paginaFueraDeRango(4, 60, 25), 'página 4 de 3 quedó fuera');
ok(paginaFueraDeRango(2, 0, 25), 'tras vaciar el padrón / buscar algo sin resultados, la página 2 quedó fuera');
eq(paginaValida(4, 60, 25), 3, 'fuera por arriba -> último tramo válido');
eq(paginaValida(2, 0, 25), 1, 'fuera por arriba con total 0 -> página 1');
eq(paginaValida(2, 60, 25), 2, 'una página VÁLIDA no se toca');
eq(paginaValida(0, 60, 25), 1, 'página 0 -> 1');

console.log('\n== 8. "Mostrando A-B de N" del pie ==');
eq(rangoMostrado({ total: 0, porPagina: 25, pagina: 1, enPagina: 0 }), { totalPaginas: 1, desde: 0, hasta: 0 }, 'sin resultados -> 0-0');
eq(rangoMostrado({ total: 60, porPagina: 25, pagina: 1, enPagina: 25 }), { totalPaginas: 3, desde: 1, hasta: 25 }, 'página 1 -> 1-25 de 60');
eq(rangoMostrado({ total: 60, porPagina: 25, pagina: 2, enPagina: 25 }), { totalPaginas: 3, desde: 26, hasta: 50 }, 'página 2 -> 26-50 de 60');
eq(rangoMostrado({ total: 60, porPagina: 25, pagina: 3, enPagina: 10 }), { totalPaginas: 3, desde: 51, hasta: 60 }, 'última página incompleta -> 51-60 de 60');
eq(rangoMostrado({ total: 7, porPagina: 25, pagina: 1, enPagina: 7 }), { totalPaginas: 1, desde: 1, hasta: 7 }, 'página única -> 1-7 de 7');
eq(rangoMostrado({ total: 0, porPagina: 25, pagina: 2, enPagina: 0 }).desde, 0, 'sin datos, ninguna página inventa un "desde 26"');

console.log('\n== 9. Modal "Voucher" del padrón: qué solicitud tiene el comprobante ==');
// Lo que devuelve `/api/v1/solicitudes/alumno/{id}`: nuevas primero, con y sin archivo.
const solNuevaSinArchivo = { id: 30, estado: 'rejected', voucher_url: null, created_at: '2026-03-10T12:00:00' };
const solViejaAprobada = { id: 20, estado: 'approved', voucher_url: '/static/uploads/v20.pdf', created_at: '2026-03-01T09:00:00' };
const solPendiente = { id: 10, estado: 'pending', voucher_url: '/static/uploads/v10.jpg', created_at: '2026-02-20T09:00:00' };
const solNuevaAprobada = { id: 25, estado: 'approved', voucher_url: '/static/uploads/v25.jpg', created_at: '2026-03-05T09:00:00' };
eq(solicitudConComprobante([]), null, 'sin solicitudes -> null (el modal dice que no hay comprobante)');
eq(solicitudConComprobante(), null, 'lista ausente -> null (no explota)');
eq(solicitudConComprobante([solNuevaSinArchivo]), null,
    'solicitudes SIN archivo -> null: no hay nada que mostrar (nunca se inventa un monto)');
eq(solicitudConComprobante([solNuevaSinArchivo, solViejaAprobada]), solViejaAprobada,
    'se salta la solicitud sin archivo y toma la que sí lo tiene');
eq(solicitudConComprobante([solNuevaAprobada, solPendiente]), solPendiente,
    'si hay una PENDIENTE manda esa, aunque no sea la más nueva (es la que hay que revisar)');
eq(solicitudConComprobante([solViejaAprobada, solNuevaAprobada]), solNuevaAprobada,
    'sin pendientes -> la más NUEVA con archivo');
eq(solicitudConComprobante([solPendiente, solNuevaSinArchivo]).id, 10,
    'una pendiente SIN archivo no bloquea a la pendiente que sí lo tiene');
eq(estadoSolicitudPlan('pending').texto, 'Pendiente de revisión', 'rótulo de pendiente');
eq(estadoSolicitudPlan('approved').texto, 'Aprobada', 'rótulo de aprobada');
eq(estadoSolicitudPlan('rejected').texto, 'Rechazada', 'rótulo de rechazada');
eq(estadoSolicitudPlan('raro'), { texto: 'raro', clase: 'text-zinc-400' },
    'un estado desconocido se muestra tal cual (no rompe el modal)');
eq(estadoSolicitudPlan(null), { texto: 'Sin estado', clase: 'text-zinc-400' }, 'estado nulo -> "Sin estado"');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));

process.exit(fallos === 0 ? 0 : 1);

