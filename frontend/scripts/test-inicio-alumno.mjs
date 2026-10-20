// Test aislado del Inicio del alumno: tarjetas de la Tienda y carrusel de avisos.
//   Ejecutar:  node scripts/test-inicio-alumno.mjs   (npm run test:inicio)
//
// POR QUÉ EXISTE:
//   1. (Parte C) las tarjetas de "Tienda Urban Box" eran <div> decorativos: tocar no hacía
//      nada. Ahora abren el flujo de compra de ESE producto (`/alumno/bazar?producto=<id>`)
//      y el Bazar tiene que leer el query y abrir el paso de pago.
//   2. (Parte G) el carrusel "Novedades del box" sólo se movía a mano. La rotación
//      automática se comprueba en el código (el test no tiene navegador).
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

const INICIO = leer('../src/pages/alumno/InicioMobile.jsx');
const BAZAR = leer('../src/pages/alumno/Bazar.jsx');
const CSS = leer('../src/pages/alumno/inicioMobile.css');
const CARRUSEL = leer('../src/components/CarruselMarketing.jsx');
const CSS_CARRUSEL = leer('../src/components/carruselMarketing.css');
const RESERVAS = leer('../../backend/app/api/v1/reservas.py');

console.log('== 1. La tarjeta de la Tienda abre ESE producto (Parte C) ==');
ok(/<button[\s\S]{0,400}className="prod"/.test(INICIO),
    'la tarjeta es un <button> (clickeable y accesible con teclado)');
ok(INICIO.includes('navigate(`/alumno/bazar?producto=${p.id}`)'),
    'navega al Bazar con el id de ESE producto');
ok(!/<div className="prod"/.test(INICIO), 'ya no queda la tarjeta decorativa <div>');
ok(INICIO.includes('aria-label={`Comprar ${p.nombre'),
    'tiene nombre accesible (lector de pantalla)');
ok(/\.ub-inicio \.prod\s*\{[^}]*cursor:\s*pointer/.test(CSS),
    'el CSS conserva el aspecto de tarjeta (font/color/alineación reseteados)');

console.log('== 2. El Bazar recibe el deep link y abre el paso de pago ==');
ok(BAZAR.includes('useSearchParams'), 'lee el query de la URL');
ok(BAZAR.includes("searchParams.get('producto')"), 'toma el id pedido');
ok(BAZAR.includes('const elegido = productos.find((p) => p.id === productoPedido)'),
    'busca ESE producto en el catálogo real');
ok(BAZAR.includes('setPaso(2)'), 'abre el paso de pago (no sólo el listado)');
ok(BAZAR.includes('deepLinkAplicado.current === productoPedido'),
    'se aplica una vez por id (volver al catálogo no reabre el paso 2)');
ok(BAZAR.includes('está agotado'), 'si el producto no tiene stock, avisa en el catálogo');

console.log('== 3. El carrusel rota solo (Parte G) ==');
ok(CARRUSEL.includes('setInterval('), 'programa el avance automático');
ok(CARRUSEL.includes('}, 5500)'), 'cada ~5,5 s (dentro de los 5-6 s pedidos)');
ok(CARRUSEL.includes('(activo + 1) % tarjetas.length'),
    'pasa a la siguiente y vuelve al inicio al llegar al final');
ok(CARRUSEL.includes('prefers-reduced-motion: reduce'),
    'respeta `prefers-reduced-motion` (no anima a quien lo desactiva)');
ok(CARRUSEL.includes('document.hidden'), 'no rota con la pestaña en segundo plano');
ok(CARRUSEL.includes('onPointerDown={pausarPorInteraccion}')
    && CARRUSEL.includes('onTouchStart={pausarPorInteraccion}'),
    'tocar/deslizar a mano PAUSA la rotación (no pelea con el dedo)');
ok(CARRUSEL.includes('setTimeout(() => setPausado(false), 10000)'),
    'y se reanuda solo 10 s después de la última interacción');
ok(CARRUSEL.includes('pista.scrollTo(') && !CARRUSEL.includes('.scrollIntoView('),
    'el avance mueve SÓLO la pista (no arrastra el scroll vertical de la página)');
ok(CARRUSEL.includes('onScroll={alDesplazar}'), 'el deslizamiento manual sigue funcionando');
ok(CARRUSEL.includes('tarjetas.length <= 1'), 'con una sola tarjeta no rota');
ok(CARRUSEL.includes('|| flyer ||'), 'con un flyer abierto tampoco');

console.log('== 4. "Tu clase de hoy" refleja el estado real (incluido no-show) ==');
ok(INICIO.includes('estado_visible'),
    'lee el estado_visible que calcula el backend (misma regla que el Historial)');
ok(INICIO.includes("falto: 'No asististe'"),
    'el estado `falto` tiene un rótulo propio (no reutiliza "Reserva confirmada")');
ok(INICIO.includes("estadoHoy === 'falto'"),
    'el hero dibuja un mensaje específico cuando el alumno no asistió');
ok(INICIO.includes("data-estado={estadoHoy || 'sin-clase'}"),
    'el hero expone su estado para que el CSS lo distinga');
ok(!INICIO.includes('reservaHoy?.asistio === true'),
    'ya no reduce la asistencia a la primera reserva del día');
ok(INICIO.includes('const asistioHoy = reservasDeHoy.some('),
    'la barra inferior sigue verde si asistió a ALGUNA clase de hoy');
ok(INICIO.includes('reservasDeHoy'),
    'separa las reservas de hoy antes de elegir la del hero');
ok(/\.ub-inicio \.hero\[data-estado="falto"\]/.test(CSS),
    'el CSS tiene un tratamiento visual para el no-show');
ok(!CSS.includes('.ub-inicio[data-checked="1"] .hero'),
    'el color del hero ya no depende de una asistencia global del día');
ok(RESERVAS.includes('func.abs(Clase.fecha - hoy)'),
    'el endpoint ordena por cercanía a HOY: la reserva de hoy no se pierde por el limit=100');

console.log('== 5. Las tarjetas del carrusel abren SU producto ==');
ok(CARRUSEL.includes('const irAProducto = (productoId)'),
    'el carrusel tiene un único abridor de producto (mismo deep link que la Tienda)');
ok(CARRUSEL.includes('navigate(`/alumno/bazar?producto=${productoId}`)'),
    'navega al Bazar con el id del producto tocado');
ok(CARRUSEL.includes('className="cm-abrir"'),
    'la tarjeta de UN producto envuelve su contenido en un <button>');
ok(CARRUSEL.includes('onClick={() => onAbrir(aviso.producto_id)}'),
    'tocar la tarjeta de UN producto abre ESE producto');
ok(CARRUSEL.includes('onClick={() => onVerProducto(aviso.producto_id)}'),
    'tocar una miniatura abre ESE producto (no sólo el catálogo)');
ok(CARRUSEL.includes('onVerProducto={irAProducto}'),
    'las miniaturas reciben el abridor del carrusel');
ok(/button\.cm-mini\s*\{[^}]*cursor:\s*pointer/.test(CSS_CARRUSEL),
    'las miniaturas se ven clickeables (cursor pointer)');
ok(/\.cm-tarjeta\.cm-producto \.cm-abrir\s*\{/.test(CSS_CARRUSEL),
    'el botón de la tarjeta conserva el layout de foto + texto');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
