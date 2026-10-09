// Test aislado de la pantalla "Pedidos listos para entrega" (admin móvil <768px):
// qué pedido se lista, qué dice cada fila y cómo se arma el mapa de avisos enviados.
//   Ejecutar:  node scripts/test-pedidos-retiro.mjs
import {
    esListoParaEntrega, codigoRetiro, textoProducto, textoEspera,
    textoInformado, mapaInformados,
} from '../src/utils/pedidosEntrega.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── Qué se lista: validado + con código + sin entregar ───────────────────────
eq(esListoParaEntrega({ estado: 'validado', codigo_retiro: 'UB-7K3M', entregado_en: null }),
    true, 'validado con código y sin entregar -> se lista');
eq(esListoParaEntrega({ estado: 'validado', codigo_retiro: 'UB-7K3M', entregado_en: '2026-08-10T12:00:00Z' }),
    false, 'ya entregado -> fuera (aunque siga "validado")');
eq(esListoParaEntrega({ estado: 'pendiente', codigo_retiro: null, entregado_en: null }),
    false, 'pendiente (sin validar) -> fuera');
eq(esListoParaEntrega({ estado: 'validado', codigo_retiro: null, entregado_en: null }),
    false, 'validado sin código de retiro -> fuera (no hay qué mostrar)');
eq(esListoParaEntrega(null), false, 'sin pedido -> false (no rompe)');

// ── Textos de la fila ────────────────────────────────────────────────────────
eq(codigoRetiro({ codigo_retiro: 'UB-7K3M' }), 'UB-7K3M', 'muestra el código real');
eq(codigoRetiro({}), 'UB-XXXX', 'sin código usa el placeholder del panel');
eq(textoProducto({ producto_nombre: 'Botella', cantidad: 2 }), 'Botella x2', 'producto + cantidad');
eq(textoProducto({ producto_nombre: 'Botella', cantidad: 1 }), 'Botella', 'cantidad 1 no se escribe');
eq(textoProducto({}), 'Producto', 'sin nombre no queda en blanco');

const AHORA = Date.parse('2026-08-10T15:00:00Z');
const haceHoras = (h) => new Date(AHORA - h * 3600000).toISOString();
eq(textoEspera({ updated_at: haceHoras(3) }, AHORA), 'Esperando hace 3 h', 'tiempo esperando');
eq(textoEspera({ updated_at: null }, AHORA), '', 'sin fecha de validación no inventa tiempo');
eq(textoInformado(haceHoras(0.05), AHORA), 'Informado hace 3 min', 'cuándo se le avisó');
eq(textoInformado(null, AHORA), '', 'sin aviso -> cadena vacía (la fila no lo muestra)');

// ── Mapa de avisos (una sola llamada de auditoría) ───────────────────────────
const filas = [
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: 7, fecha: haceHoras(2) },
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: 7, fecha: haceHoras(1) },
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: 8, fecha: haceHoras(5) },
    { accion: 'EMAIL_MANUAL', entidad: 'usuario', entidad_id: 9, fecha: haceHoras(5) },
    { accion: 'UPDATE', entidad: 'pedido', entidad_id: 10, fecha: haceHoras(5) },
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: null, fecha: haceHoras(5) },
];
const mapa = mapaInformados(filas);
eq(Object.keys(mapa).length, 2, 'sólo los avisos de pedidos entran al mapa');
eq(mapa[7], filas[1].fecha, 'del mismo pedido queda el aviso MÁS RECIENTE');
eq(mapa[8], filas[2].fecha, 'cada pedido con su propia fecha');
eq(mapa[9], undefined, 'un correo manual de OTRA entidad no se cuela');
eq(mapa[10], undefined, 'una acción que no es EMAIL_MANUAL tampoco');
eq(Object.keys(mapaInformados(null)).length, 0, 'sin filas -> mapa vacío (no rompe)');
eq(Object.keys(mapaInformados(undefined)).length, 0, 'sin llamada -> mapa vacío');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
