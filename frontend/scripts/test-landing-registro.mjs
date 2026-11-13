// Test aislado de la landing pública del alta (/landing): labels visibles, rediseño
// con Tailwind y lógica de envío intacta. El proyecto no renderiza componentes en sus
// tests: se verifica el FUENTE del JSX (mismo patrón que `test-referidos.mjs`).
//   Ejecutar:  node scripts/test-landing-registro.mjs   (`npm run test:landing`)
//
// POR QUÉ EXISTE: el formulario se apoyaba en los placeholders y un `<input type="date">`
// NO muestra placeholder (Android abría el calendario sin decir qué fecha pedía, y
// parecía que estuviera agendando una clase). Además estaba fuera del lenguaje visual
// del resto de la app. Este test congela las dos cosas y la lógica del POST.
import { readFileSync } from 'node:fs';

const PANTALLA = readFileSync(
    new URL('../src/pages/LandingPage.jsx', import.meta.url), 'utf8');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};
const eq = (obtenido, esperado, msg) => ok(obtenido === esperado,
    `${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);

// ── 1. Label visible en TODOS los campos ─────────────────────────────────────
console.log('== 1. Cada campo tiene su <label> visible (no solo placeholder) ==');
ok(PANTALLA.includes('htmlFor={id}'),
    'el <label> se enlaza con htmlFor al id del campo');
const CAMPOS = [
    ['nombre', 'Nombre completo'],
    ['rut', 'RUT (sin puntos, con guión)'],
    ['correo', 'Correo electrónico'],
    ['genero', 'Sexo'],
    ['peso_kg', 'Peso (kg)'],
    ['estatura_cm', 'Estatura (cm)'],
    ['telefono', 'Teléfono'],
    ['fecha_nacimiento', 'Fecha de nacimiento'],
];
for (const [id, label] of CAMPOS) {
    ok(PANTALLA.includes(`id="${id}"`), `${id}: el campo tiene id para el label`);
    ok(PANTALLA.includes(`label="${label}"`), `${id}: el label dice "${label}"`);
}
eq((PANTALLA.match(/\brequired\b/g) || []).length, 8,
    'los 8 campos siguen siendo obligatorios');

// ── 2. Fecha de nacimiento: label visible y CERO placeholder ─────────────────
console.log('== 2. Fecha de nacimiento (el bug de Android) ==');
const inicioFecha = PANTALLA.indexOf('id="fecha_nacimiento"');
const bloqueFecha = PANTALLA.slice(
    inicioFecha, PANTALLA.indexOf('</Campo>', inicioFecha));
ok(bloqueFecha.includes('label="Fecha de nacimiento"'),
    'la fecha tiene su label arriba (texto visible en Android)');
ok(bloqueFecha.includes('type="date"'),
    'sigue siendo el selector de fecha nativo');
ok(!bloqueFecha.includes('placeholder='),
    'la fecha NO depende del placeholder (no se muestra en type="date")');
ok(bloqueFecha.includes('no estás agendando una clase'),
    'el texto aclara que la fecha es de la ficha, no una reserva');
ok(bloqueFecha.includes('[color-scheme:dark]'),
    'el icono del calendario se ve sobre el tema oscuro');

// ── 3. Rediseño: Tailwind y lenguaje visual del panel ────────────────────────
console.log('== 3. Tailwind y lenguaje visual del resto de la app ==');
ok(PANTALLA.includes('className="relative min-h-screen'),
    'la página usa clases Tailwind (no estilos inline)');
ok(!PANTALLA.includes('style={{'),
    'no quedan estilos inline (colores hardcodeados)');
ok(PANTALLA.includes('login-input'),
    'reusa el input compartido del Login público');
ok(PANTALLA.includes('className={CLASE_INPUT}'),
    'los campos comparten UNA clase de input (consistencia)');
ok(PANTALLA.includes('bg-[#ff8c00]'),
    'usa el naranja de marca en el CTA');
ok(PANTALLA.includes("bg-[url('/imgs/portada.webp')]"),
    'usa la portada del box como fondo, igual que el Login');
ok(PANTALLA.includes('/imgs/logo.png'),
    'muestra el logo de Urban Training Box');
ok(PANTALLA.includes('data-testid="landing-form"')
    && PANTALLA.includes('data-testid="mensaje-landing"'),
    'el formulario y el mensaje tienen testids estables');

// ── 4. La lógica de envío NO cambia ──────────────────────────────────────────
console.log('== 4. Lógica del POST intacta ==');
ok(PANTALLA.includes("axios.post('/api/v1/alumnos/registro/alumno-nuevo'"),
    'pega al MISMO endpoint de alta');
ok(/useSearchParams/.test(PANTALLA) && /searchParams\.get\('inv'\)/.test(PANTALLA),
    'sigue leyendo ?inv=<token>');
ok(PANTALLA.includes('payload.token_invitacion = tokenInvitacion'),
    'manda token_invitacion solo cuando vino en el link');
ok(PANTALLA.includes('/^\\d{7,8}-[\\dkK]$/'),
    'mantiene la validación de RUT');
ok(PANTALLA.includes('sexo: formData.genero'),
    'mapea genero -> sexo como antes');
ok(PANTALLA.includes('peso_kg: parseFloat(formData.peso_kg)')
    && PANTALLA.includes('estatura_cm: parseInt(formData.estatura_cm)'),
    'peso y estatura se convierten igual que antes');
ok(PANTALLA.includes('email_enviado === false && d.password_provisional'),
    'detecta el correo fallido y muestra la contraseña provisional');
ok(PANTALLA.includes('password: d.password_provisional'),
    'la contraseña provisional se pinta en el aviso');
ok(PANTALLA.includes('setFormData(FORM_VACIO)'),
    'el formulario se limpia después de un envío exitoso');
ok(PANTALLA.includes('RUT inválido (ej: 12345678-9)'),
    'mantiene el mensaje de RUT inválido');
ok(PANTALLA.includes('¡Solicitud recibida! Revisa tu correo (incluyendo SPAM).'),
    'mantiene el mensaje de éxito');
ok(PANTALLA.includes('Registro creado, pero no pudimos enviarte el correo'),
    'mantiene el aviso cuando el correo no salió');

// ── 5. Sin emojis en el formulario público ───────────────────────────────────
console.log('== 5. Sin emojis (color y jerarquía en su lugar) ==');
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;
ok(!EMOJI.test(PANTALLA), 'la pantalla no tiene emojis');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
