// Test aislado del walk-in del coach ("+ Agregar alumno sin reserva").
//   Ejecutar:  node scripts/test-walkin.mjs   (npm run test:walkin)
//
// POR QUÉ EXISTE: el botón toca DINERO (¿se le descuenta el crédito al alumno o no?) y
// PERMISOS (un coach agregando gente a una clase). Nada de eso lo nota un test de lógica,
// así que quedan fijadas las piezas que pueden volver a romperse sin que nadie se entere:
//   1. el modal NO reimplementa dinero: con `puede_reservar` usa los endpoints que ya
//      existen (reserva del staff + marcado);
//   2. sin créditos usa el endpoint de presencia sin cargo (`/sin-reserva`);
//   3. la rama la decide el BACKEND (`puede_reservar`), nunca un mensaje de error;
//   4. `AsistenciaClases` sólo muestra el botón con la prop opcional, y SÓLO el coach la
//      pasa (el admin queda igual);
//   5. los endpoints del backend existen, con el candado de dinero (409) y el
//      `tokens_gastados = 0` del camino sin cargo.
import { readFileSync, readdirSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const MODAL = leer('../src/components/ModalAgregarSinReserva.jsx');
const ASIST = leer('../src/components/AsistenciaClases.jsx');
const DASH = leer('../src/pages/coach/DashboardCoach.jsx');
const HOOKS = leer('../src/hooks/queries.js');
const API = leer('../../backend/app/api/v1/asistencia.py');

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

console.log('== 1. Con créditos: se reusan los endpoints que ya existen ==');
ok(MODAL.includes('useCrearReserva') && MODAL.includes('useMarcarAsistenciaReserva'),
    'el camino con crédito usa la reserva del staff y el marcado (nada nuevo de dinero)');
ok(/crearReserva\.mutateAsync\(\{[\s\S]*?alumno_id: alumno\.alumno_id/.test(MODAL),
    'la reserva va a nombre del alumno elegido');
ok(MODAL.includes('marcarAsistencia.mutateAsync({ reservaId: reserva.id, asistio: true })'),
    'después de reservar, se lo deja PRESENTE');
eq(MODAL.includes('api.post('), false, 'el modal no pega a la API por su cuenta (todo por hooks)');

console.log('== 2. Sin créditos: presencia sin cargo ==');
ok(MODAL.includes('presenteSinReserva.mutateAsync('), 'usa la mutación de presencia sin cargo');
ok(!/presenteSinReserva\.mutateAsync[\s\S]{0,400}catch/.test(MODAL)
    || MODAL.indexOf('crearReserva.mutateAsync') < MODAL.indexOf('presenteSinReserva.mutateAsync'),
    'el camino sin cargo no es un "fallback" del camino con crédito');

console.log('== 3. La rama la decide el backend ==');
ok(/if \(alumno\.puede_reservar\)/.test(MODAL), 'la bifurcación mira `puede_reservar`');
eq(/status === 409|response\?\.status/.test(MODAL), false,
    'no se adivina la rama leyendo el status de un error');

console.log('== 4. Prop opcional en AsistenciaClases (el walk-in sigue sólo en el coach) ==');
ok(/const AsistenciaClases = \(\{\s*variant = 'light', franjas = false, permitirSinReserva = false,\s*permitirFiltroDisciplina = false,\s*\} = \{\}\)/.test(ASIST),
    'la prop arranca en false (DOM idéntico para quien no la pasa)');
ok(/permitirSinReserva && \(/.test(ASIST), 'el botón "+ Agregar alumno sin reserva" está detrás de la prop');
ok(/permitirSinReserva && modalSinReserva && claseSeleccionada && \(/.test(ASIST),
    'el modal sólo se monta con la prop');
ok(/<AsistenciaClases franjas permitirSinReserva \/>/.test(DASH),
    'el panel del coach la pasa; el admin no pide walk-in');

const fuentes = (url) => readdirSync(url, { withFileTypes: true }).flatMap((e) =>
    (e.isDirectory() ? fuentes(new URL(e.name + '/', url)) : [new URL(e.name, url)]));
const CON_ASISTENCIA = fuentes(new URL('../src/', import.meta.url))
    .filter((u) => /\.(jsx|js)$/.test(u.pathname))
    .map((u) => readFileSync(u, 'utf8'))
    .filter((txt) => txt.includes('<AsistenciaClases'));
eq(CON_ASISTENCIA.filter((txt) => txt.includes('permitirSinReserva')).length, 1,
    'sólo UNA pantalla (el coach) pide el walk-in');

console.log('== 5. Backend: endpoints y candados ==');
ok(API.includes('@router.post("/clases/{clase_id}/sin-reserva"'),
    'existe POST /asistencia/clases/{id}/sin-reserva');
ok(API.includes('@router.get("/clases/{clase_id}/elegibles")'),
    'existe GET /asistencia/clases/{id}/elegibles (la lista del modal)');
ok(API.includes('VIA_SIN_CARGO = "sin_cargo"'), 'la presencia sin cargo queda marcada como tal');
ok(/tokens_gastados=0/.test(API), 'sin cargo = 0 créditos gastados');
ok(/asistio=True/.test(API), 'el walk-in entra presente');
ok(API.includes('status.HTTP_409_CONFLICT'), 'con plan y créditos el endpoint se planta (409)');
ok(/clase\.fecha != hoy_santiago\(\)/.test(API), 'la ventana es el día de la clase (hora de Chile)');
ok(/verificar_coach_disciplina\(/.test(API), 'valida la disciplina del coach');
ok(API.includes('registrar_auditoria('), 'deja auditoría (acción sensible del box)');
ok(/Clase\.asistentes_confirmados < Clase\.cupo_maximo/.test(API), 'toma el aforo con el UPDATE atómico');
ok(/alumno_id: int = Field\(\.\.\., gt=0\)/.test(leer('../../backend/app/schemas/asistencia.py')),
    'el body del walk-in es sólo `{ alumno_id }`');

console.log('== 6. Bloque 2: la confirmación es lo único que ejecuta el descuento ==');
ok(/const \[confirmando, setConfirmando\] = useState\(null\)/.test(MODAL),
    'el modal tiene el paso de confirmación como estado propio');
ok(/onClick=\{\(\) => setConfirmando\(a\)\}/.test(MODAL),
    'tocar un nombre SÓLO abre la tarjeta (todavía no llama a `agregar`)');
eq(/onClick=\{\(\) => agregar\(a\)\}/.test(MODAL), false,
    'no queda ningún click que agregue directo (era el descuento de un toque)');
ok(/const confirmar = \(\) => \{\s*if \(confirmando\) agregar\(confirmando\);/.test(MODAL),
    '`Confirmar` es el único camino a `agregar` (los endpoints de siempre)');
ok(/data-testid="cancelar-token"/.test(MODAL) && /data-testid="confirmar-token-btn"/.test(MODAL),
    'la tarjeta tiene Cancelar y Confirmar');
ok(/const cancelar = \(\) => \{\s*if \(ocupado\) return;\s*setError\(''\);\s*setConfirmando\(null\);/.test(MODAL),
    'Cancelar vuelve a la lista sin escribir nada');
ok(/Se le descontará 1 token del plan a \$\{a\.nombre\}/.test(MODAL),
    'con créditos, la tarjeta dice qué token se le descuenta y a quién');
ok(/Su plan es ILIMITADO: no se le descuenta cupo de clases\./.test(MODAL),
    'con plan ilimitado (creditos NULL) promete la verdad: sin descuento de cupo');
ok(/'Ilimitado · no se le descuenta cupo'/.test(MODAL),
    'la pista de la lista tampoco promete un descuento que no ocurre');
ok(/Se ha descontado un token del plan de \$\{a\.nombre\}/.test(MODAL)
    && /mensaje: mensajeExito\(alumno\)/.test(MODAL),
    'el toast posterior nace en el modal y viaja en `onAgregado` (una sola fuente de texto)');
ok(/<Toast texto=\{toast\} \/>/.test(ASIST) && /setToast\(alumno\.mensaje\)/.test(ASIST),
    'el detalle de Asistencia pinta ese texto como toast');
ok(/<Toast texto=\{toastWalkin\} \/>/.test(DASH) && /setToastWalkin\(alumno\.mensaje\)/.test(DASH),
    'y el Resumen del coach también');
const TOAST = leer('../src/components/Toast.jsx');
ok(/const Toast = \(\{ texto/.test(TOAST) && /role="status"/.test(TOAST),
    'el toast es un componente compartido y se anuncia (role="status")');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
