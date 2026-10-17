// Test aislado del bug "la foto de un producto del Bazar no carga" (Parte B).
//   Ejecutar:  node scripts/test-imagenes-bazar.mjs   (npm run test:imagenes)
//
// POR QUÉ EXISTE: en PROD el valor de STORAGE_R2_PUBLIC_BASE_URL llegó con el bucket y la
// access key PEGADOS (varias líneas). El backend guardó ese texto crudo como `imagen_url`,
// el navegador no pudo cargarlo y el producto ("poleron") mostró la foto rota. "poleras"
// se veía bien porque NO tiene foto: cae al emoji del respaldo.
//
// Esta guarda comprueba, sin navegador:
//   1. `urlArchivo` descarta una URL con espacios/saltos (devuelve null, no una URL rota),
//   2. las pantallas que muestran productos usan `ImagenProducto` (con respaldo),
//   3. el componente esconde el <img> cuando falla o la URL no sirve,
//   4. la capa de almacenamiento toma SÓLO la primera URL y valida ANTES de subir.
import { readFileSync } from 'node:fs';

import { urlArchivo } from '../src/utils/imagen.js';

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
const eq = (obtenido, esperado, msg) => ok(obtenido === esperado, `${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);

console.log('== 1. urlArchivo normaliza y descarta URLs que el navegador no puede cargar ==');
eq(urlArchivo(null), null, 'sin URL -> null (la pantalla usa su respaldo)');
eq(urlArchivo(''), null, 'cadena vacía -> null');
eq(urlArchivo('https://pub-x.r2.dev/publico/a.webp'),
    'https://pub-x.r2.dev/publico/a.webp', 'URL absoluta válida se usa tal cual');
eq(urlArchivo('  /static/uploads/a.jpg  '), '/static/uploads/a.jpg',
    'ruta relativa: se recortan los espacios (en Node no hay VITE_API_URL)');
const ROTA = 'https://pub-x.r2.dev\n\nbucket\n\nAKIAFALSA\n\n/publico/a.webp';
eq(urlArchivo(ROTA), null, 'la URL multilínea que guardó PROD -> null (no <img> roto)');
eq(urlArchivo('https://pub-x.r2.dev/publico/a b.webp'), null, 'una URL con espacio interno -> null');

console.log('== 2. Las pantallas que muestran productos usan el componente con respaldo ==');
for (const [nombre, archivo] of [
    ['Inventario del admin', '../src/pages/admin/Bazar.jsx'],
    ['Catálogo del alumno', '../src/pages/alumno/Bazar.jsx'],
    ['Inicio móvil (Tienda)', '../src/pages/alumno/InicioMobile.jsx'],
    ['Carrusel de marketing', '../src/components/CarruselMarketing.jsx'],
]) {
    const src = leer(archivo);
    ok(/import ImagenProducto from/.test(src), `${nombre}: importa ImagenProducto`);
    ok(src.includes('<ImagenProducto'), `${nombre}: lo monta`);
    // Único <img> directo permitido: el flyer a pantalla completa del carrusel (no es un
    // producto). Cualquier foto de producto tiene que pasar por el componente.
    const directos = [...src.matchAll(/<img\s+src=\{([^}]+)\}/g)].map((m) => m[1].trim());
    const permitidos = archivo.includes('CarruselMarketing') ? ['urlArchivo(flyer.imagen_url)'] : [];
    ok(directos.every((expr) => permitidos.includes(expr)),
        `${nombre}: sin <img> de producto sin respaldo (${directos.join(', ') || 'ninguno'})`);
}

console.log('== 3. El respaldo esconde el <img> cuando la foto falla ==');
const componente = leer('../src/components/ImagenProducto.jsx');
ok(componente.includes('onError={() => setFallo(true)}'), 'marca el fallo cuando el navegador no carga');
ok(componente.includes('if (!src || fallo) return respaldo;'),
    'devuelve el respaldo (emoji/ícono) en vez del ícono de imagen rota');
ok(componente.includes('useEffect'), 'al cambiar la foto (edición) vuelve a intentar');

console.log('== 4. El backend no vuelve a guardar una base multilínea ==');
const storage = leer('../../backend/app/services/storage.py');
ok(storage.includes('partes = crudo.split()'), 'toma sólo el primer token de la variable');
ok(storage.includes('len(partes) > 1'), 'avisa si trae valores de más (sin loguear credenciales)');
ok(storage.includes('base = _url_publica_base()'), 'valida la base ANTES de subir el archivo');
ok(storage.includes('if not base.lower().startswith(("http://", "https://")):'),
    'exige una URL http(s) (un valor suelto no se guarda)');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
