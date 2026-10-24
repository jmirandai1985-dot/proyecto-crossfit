// Test aislado de la pantalla unificada "Pendientes" (frontend/src/utils/pendientes.js).
//   Ejecutar:  node scripts/test-pendientes.mjs
//
// Valida, sin navegador ni framework, TODO lo que decide la pantalla y la tarjeta
// de publicación de promociones:
//   1. Las cuatro pestañas (orden de trabajo, `key` = `cola`, textos).
//   2. Lectura defensiva del resumen: nada se convierte en NaN y `total` se suma.
//   3. Pestaña por defecto / validación y traducción del `?tab=`.
//   4. Deep-links (`rutaPendientes`) y compatibilidad con `?cola=` viejo.
//   5. Badge del menú (incluido el tope "99+").
//   6. Fechas de la ventana de publicación en hora LOCAL (no UTC).
//   7. Validación del formulario de publicación y estado del chip "Carrusel".
import {
    TABS_PENDIENTES, CONTADORES_VACIOS, normalizarResumen, totalPendientes,
    pendientesDe, tabPorDefecto, esTabValida, resolverTab, rutaPendientes,
    mapearColaLegacy, textoBadge, fechaISO, ventanaPublicacionSugerida,
    validarPublicacion, tarjetaSugerida, estadoPublicacion,
} from '../src/utils/pendientes.js';
import { readFileSync } from 'node:fs';

/** Lee un archivo del repo (para comprobar el montaje en las pantallas). */
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
const igual = (recibido, esperado, msg) => {
    const ok_ = JSON.stringify(recibido) === JSON.stringify(esperado);
    ok(ok_, `${msg} (esperado ${JSON.stringify(esperado)}, recibido ${JSON.stringify(recibido)})`);
};

console.log('== 1. Pestañas ==');
igual(TABS_PENDIENTES.map((tab) => tab.key),
    ['solicitudes', 'pedidos', 'registros', 'premios'],
    'cuatro pestañas en orden de trabajo');
ok(TABS_PENDIENTES.every((tab) => tab.cola === tab.key),
    'la clave del resumen coincide con el `?tab=`');
ok(TABS_PENDIENTES.every((tab) => tab.label && tab.icono && tab.descripcion),
    'cada pestaña tiene label, icono y descripción');
igual(Object.keys(CONTADORES_VACIOS).sort(),
    ['pedidos', 'premios', 'registros', 'solicitudes', 'total'],
    'CONTADORES_VACIOS cubre las cuatro colas + total');
ok(Object.values(CONTADORES_VACIOS).every((n) => n === 0), 'todos los contadores vacíos valen 0');

console.log('== 2. normalizarResumen / totalPendientes / pendientesDe ==');
igual(normalizarResumen(null), CONTADORES_VACIOS, 'sin datos => contadores en cero');
igual(normalizarResumen({}), CONTADORES_VACIOS, 'objeto vacío => contadores en cero');
igual(
    normalizarResumen({ solicitudes: 2, pedidos: '3', registros: 0, premios: null }),
    { solicitudes: 2, pedidos: 3, registros: 0, premios: 0, total: 5 },
    'acepta números y strings, y normaliza null',
);
igual(
    normalizarResumen({ solicitudes: -4, pedidos: 'x', registros: 2.9, premios: undefined }),
    { solicitudes: 0, pedidos: 0, registros: 2, premios: 0, total: 2 },
    'negativos, NaN y decimales no rompen el badge',
);
igual(
    normalizarResumen({ solicitudes: 1, pedidos: 1, total: 999 }),
    { solicitudes: 1, pedidos: 1, registros: 0, premios: 0, total: 2 },
    'el total se recalcula y NO se confía en el del backend',
);
igual(totalPendientes({ solicitudes: 1, pedidos: 2, registros: 3, premios: 4 }), 10,
    'totalPendientes suma las cuatro colas');
igual(totalPendientes({ total: 7 }), 0, 'un `total` suelto no se cuela como pendientes');
igual(pendientesDe('pedidos', { pedidos: 5 }), 5, 'pendientesDe lee la cola pedida');
igual(pendientesDe('premios', {}), 0, 'pendientesDe devuelve 0 si no está en el resumen');
igual(pendientesDe('regalos', { premios: 5 }), 0, 'pendientesDe ignora claves que no son colas');

console.log('== 3. Pestaña por defecto y ?tab= ==');
igual(tabPorDefecto({}), 'solicitudes', 'sin pendientes abre Solicitudes');
igual(tabPorDefecto({ registros: 2 }), 'registros', 'abre la primera pestaña CON pendientes');
igual(tabPorDefecto({ premios: 1, pedidos: 1 }), 'pedidos',
    'respeta el orden de trabajo (pedidos antes que premios)');
ok(esTabValida('premios'), 'esTabValida acepta una pestaña real');
ok(!esTabValida('cola-solicitudes') && !esTabValida(undefined) && !esTabValida(''),
    'esTabValida rechaza valores viejos, vacíos y undefined');
igual(resolverTab('registros', {}), 'registros', 'resolverTab respeta un ?tab= válido');
igual(resolverTab('foo', {}), 'solicitudes', 'un ?tab= inválido cae en la pestaña por defecto');
igual(resolverTab(undefined, { pedidos: 4 }), 'pedidos',
    'sin ?tab= se usa la pestaña con pendientes');

console.log('== 4. Deep-links y enlace viejo ?cola= ==');
igual(rutaPendientes('solicitudes'), '/admin/pendientes?tab=solicitudes',
    'rutaPendientes arma el enlace nuevo');
igual(rutaPendientes('premios'), '/admin/pendientes?tab=premios',
    'rutaPendientes sirve para la pestaña de premios');
igual(rutaPendientes('no-existe'), '/admin/pendientes?tab=solicitudes',
    'rutaPendientes cae en Solicitudes con una pestaña inventada');
igual(rutaPendientes(), '/admin/pendientes?tab=solicitudes',
    'rutaPendientes sin argumento apunta a Solicitudes');
igual(mapearColaLegacy('registros'), 'registros', '?cola=registros se mantiene');
igual(mapearColaLegacy('solicitudes'), 'solicitudes', '?cola=solicitudes se mantiene');
igual(mapearColaLegacy('pedidos'), 'pedidos', '?cola=pedidos ahora tiene pestaña propia');
igual(mapearColaLegacy(undefined), 'solicitudes', '?cola= desconocido cae en Solicitudes');

console.log('== 5. Badge del menú ==');
igual(textoBadge(0), '', '0 no dibuja badge');
igual(textoBadge(-3), '', 'un negativo no dibuja badge');
igual(textoBadge('x'), '', 'NaN no dibuja badge');
igual(textoBadge(1), '1', 'un pendiente se muestra tal cual');
igual(textoBadge('7'), '7', 'acepta el número como string');
igual(textoBadge(99), '99', '99 todavía entra en el círculo');
igual(textoBadge(100), '99+', '100+ se abrevia');

console.log('== 6. Fechas de publicación (hora local) ==');
igual(fechaISO(new Date(2026, 0, 5)), '2026-01-05', 'fechaISO rellena mes y día');
igual(fechaISO(new Date(2026, 11, 31)), '2026-12-31', 'fechaISO no adelanta el año');
// 23:30 en Chile: `toISOString()` ya sería el día siguiente en UTC. La ventana se
// guarda como `date`, así que tiene que usar la fecha local.
igual(fechaISO(new Date(2026, 9, 23, 23, 30)), '2026-10-23',
    'fechaISO usa la fecha LOCAL, no la UTC');
igual(ventanaPublicacionSugerida(new Date(2026, 9, 23)),
    { vigente_desde: '2026-10-23', vigente_hasta: '2026-11-22' },
    'la ventana sugerida dura 30 días y cruza el mes');
igual(ventanaPublicacionSugerida(new Date(2026, 9, 23), 0),
    { vigente_desde: '2026-10-23', vigente_hasta: '2026-10-23' },
    'con 0 días la tarjeta empieza y termina el mismo día');
igual(ventanaPublicacionSugerida(new Date(2026, 11, 20), 20),
    { vigente_desde: '2026-12-20', vigente_hasta: '2027-01-09' },
    'la ventana cruza el año');

console.log('== 7. Validación del formulario de publicación ==');
const tarjetaOk = {
    titulo: 'Invita y gana',
    texto: 'Con 3 referidos te llevas un mes gratis.',
    vigente_desde: '2026-10-23',
    vigente_hasta: '2026-11-22',
};
igual(validarPublicacion(tarjetaOk), [], 'una tarjeta completa no tiene errores');
igual(validarPublicacion({ ...tarjetaOk, titulo: '   ' }).length, 1,
    'un título en blanco es un error');
igual(validarPublicacion({ ...tarjetaOk, texto: '' }).length, 1, 'un texto vacío es un error');
igual(validarPublicacion({ ...tarjetaOk, titulo: 'x'.repeat(151) }).length, 1,
    'el título tiene tope de 150 caracteres');
igual(validarPublicacion({ ...tarjetaOk, texto: 'x'.repeat(1001) }).length, 1,
    'el texto tiene tope de 1000 caracteres');
igual(validarPublicacion({ ...tarjetaOk, titulo: 'x'.repeat(150), texto: 'y'.repeat(1000) }),
    [], 'los topes exactos sí se aceptan');
igual(validarPublicacion({ ...tarjetaOk, vigente_hasta: '2026-10-22' }).length, 1,
    'la vigencia no puede terminar antes de empezar');
igual(validarPublicacion({ ...tarjetaOk, vigente_hasta: '2026-10-23' }), [],
    'empezar y terminar el mismo día es válido');
igual(validarPublicacion({}).length, 3, 'un formulario vacío acumula los tres errores');
igual(validarPublicacion().length, 3, 'sin argumentos no explota y reporta lo mismo');

console.log('== 8. Texto sugerido de la tarjeta ==');
igual(tarjetaSugerida({
    nombre: 'Mes gratis', premio_texto: '1 mes gratis', umbral_referidos_convertidos: 3,
}), {
    titulo: 'Mes gratis',
    texto: 'Invita a tus amigos al box: con 3 referidos convertidos en el mes ganas 1 mes gratis.',
}, 'usa el nombre de la promoción como título y el premio en el texto');
igual(tarjetaSugerida({
    nombre: 'Primer referido', premio_texto: '7 días gratis', umbral_referidos_convertidos: 1,
}).texto, 'Invita a tus amigos al box: con 1 referido convertido en el mes ganas 7 días gratis.',
    'el singular de 1 referido está bien escrito');
igual(tarjetaSugerida({ nombre: 'Sin premio', umbral_referidos_convertidos: 2 }).texto,
    'Invita a tus amigos al box y gana premios al llegar a 2 referidos convertidos en el mes.',
    'sin premio configurado igual propone un texto');
igual(tarjetaSugerida({}).titulo, 'Invita y gana', 'sin nombre usa un título por defecto');
igual(tarjetaSugerida().titulo, 'Invita y gana', 'sin argumentos no explota');
igual(tarjetaSugerida({ nombre: '  Mes gratis  ' }).titulo, 'Mes gratis',
    'recorta los espacios del nombre');

console.log('== 9. Chip del carrusel ==');
const hoy = new Date(2026, 9, 23);
igual(estadoPublicacion({ publicada: false }, hoy),
    { clave: 'sin_publicar', texto: 'Sin publicar', vencida: false },
    'sin aviso vinculado el chip dice "Sin publicar"');
igual(estadoPublicacion({ publicada: true, publicada_hasta: '2026-11-22' }, hoy),
    { clave: 'vigente', texto: 'Publicada', vencida: false },
    'una ventana futura está publicada');
igual(estadoPublicacion({ publicada: true, publicada_hasta: '2026-10-23' }, hoy),
    { clave: 'vigente', texto: 'Publicada', vencida: false },
    'el último día de la ventana todavía cuenta');
igual(estadoPublicacion({ publicada: true, publicada_hasta: '2026-10-22' }, hoy),
    { clave: 'vencida', texto: 'Publicación vencida', vencida: true },
    'una ventana pasada queda vencida');
igual(estadoPublicacion({ publicada: true, publicada_hasta: '2026-11-22T12:00:00' }, hoy),
    { clave: 'vigente', texto: 'Publicada', vencida: false },
    'tolera una fecha con hora (serialización con timestamp)');
igual(estadoPublicacion({ publicada: true }, hoy).clave, 'vigente',
    'publicada sin fecha de fin no se marca vencida');

console.log('== 10. Lectura defensiva de `null` (crash de /admin/marketing?tab=referidos) ==');
// El parámetro por defecto `= {}` NO cubre `null`: el modal quedaba montado con
// `promocion={null}` y leer `.nombre` tiraba "Cannot read properties of null".
igual(tarjetaSugerida(null).titulo, 'Invita y gana',
    'promoción null => título por defecto (no `.nombre` de null)');
ok(tarjetaSugerida(null).texto.startsWith('Invita a tus amigos al box'),
    'promoción null => texto sugerido genérico');
ok(!tarjetaSugerida(null).texto.includes('undefined'), 'el texto por defecto no filtra "undefined"');
igual(estadoPublicacion(null, hoy),
    { clave: 'sin_publicar', texto: 'Sin publicar', vencida: false },
    'promoción null => chip "Sin publicar"');
igual(estadoPublicacion(undefined, hoy).clave, 'sin_publicar', 'sin argumento sigue funcionando');

console.log('== 11. Montaje en la app (chip y modal) ==');
const leerPend = leer('../src/components/pendientes/PanelPedidos.jsx');
const leerGestion = leer('../src/components/GestionPromocionesReferidos.jsx');
ok(/urlPedidosPorEstado\('validado'\)/.test(leerPend),
    'el chip "Validados sin retirar" enlaza con el filtro en la URL');
ok(/contarListosParaEntrega\s*\(/.test(leerPend),
    'el contador sale de la MISMA regla que la pantalla de entrega');
ok(/🚚 Validados sin retirar/.test(leerPend) && /validadosQ\.isLoading/.test(leerPend),
    'el chip muestra el contador (y "…" mientras carga)');
ok(/\{publicando && \(/.test(leerGestion)
    && /promocion=\{publicando\}/.test(leerGestion)
    && /onClose=\{\(\) => setPublicando\(null\)\}/.test(leerGestion),
    'el modal de publicación sólo se monta con una promoción real');

console.log('');
if (fallos > 0) {
    console.log(`== FALLARON ${fallos} comprobaciones ==`);
    process.exit(1);
}
console.log('== TODO OK ==');

