// Test aislado del armado del enlace de WhatsApp (ficha rápida del buscador admin).
//   Ejecutar:  node scripts/test-whatsapp.mjs
//
// `usuarios.telefono` se carga a mano y sin formato único: acá se fija que el panel
// arme SIEMPRE un wa.me válido y que, cuando el teléfono falta o es basura, el botón
// no se dibuje (null) en vez de abrir un chat roto.
import { soloDigitos, telefonoWhatsapp, enlaceWhatsapp } from '../src/utils/whatsapp.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

eq(soloDigitos('+56 9 1234 5678'), '56912345678', 'saca +, espacios y guiones');
eq(soloDigitos(null), '', 'null -> cadena vacía (no rompe)');
eq(telefonoWhatsapp('912345678'), '56912345678', 'celular local de 9 dígitos -> 56 + número');
eq(telefonoWhatsapp('+56 9 1234 5678'), '56912345678', 'celular con formato -> mismo resultado');
eq(telefonoWhatsapp('56912345678'), '56912345678', 'ya con código de país: tal cual');
eq(telefonoWhatsapp('22334455'), '5622334455', 'fijo local de 8 dígitos -> 56 + número');
eq(telefonoWhatsapp(''), null, 'sin teléfono -> null (el botón no se dibuja)');
eq(telefonoWhatsapp(null), null, 'teléfono nulo -> null');
eq(telefonoWhatsapp('123'), null, 'teléfono incompleto -> null');
eq(enlaceWhatsapp('912345678'), 'https://wa.me/56912345678', 'enlace sin mensaje');
eq(enlaceWhatsapp('912345678', 'Hola Camila'),
    'https://wa.me/56912345678?text=Hola%20Camila', 'el mensaje va codificado');
eq(enlaceWhatsapp(''), null, 'sin teléfono no hay enlace');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
