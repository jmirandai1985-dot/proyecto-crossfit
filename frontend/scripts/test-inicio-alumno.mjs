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

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
