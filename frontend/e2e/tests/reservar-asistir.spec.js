import { test, expect } from '@playwright/test';
import { creds, login, tokenDe } from '../helpers.js';

// Día de mañana en la zona de Chile (número de día del mes): sirve para reservar
// una clase FUTURA y no chocar con la de hoy, que el alumno ya puede tener
// reservada de corridas anteriores de este mismo test.
function diaDeManana() {
  const hoyStr = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Santiago',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
  const d = new Date(`${hoyStr}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.getUTCDate();
}

// Flujo: alumno reserva una clase disponible (UI), confirma que aparece en
// "Mis reservas" y se le marca la asistencia con el endpoint de check-in que ya
// usa el panel de Asistencia (staff). Se usa ese endpoint (en vez del QR del
// alumno) porque el check-in por QR sólo marca cuando la clase está "en curso"
// (-60 min a fin) y no es determinístico para un test automatizado.
test('alumno reserva clase, la ve en Mis reservas y se le marca asistencia', async ({ page, playwright }) => {
  const { alumno, admin } = creds();

  // 1. Login del alumno por UI.
  await login(page, alumno);
  await expect(page).toHaveURL(/\/alumno\/dashboard/);

  // Token del alumno y contexto de API SIN cookies: el `request` fixture comparte
  // la cookie del navegador, y una mutación por cookie exige CSRF (el DELETE de
  // limpieza daba 403 y las reservas se acumulaban entre corridas).
  const token = await tokenDe(page);
  const apiAlumno = await playwright.request.newContext({
    baseURL: new URL(page.url()).origin,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });

  // Reservas ANTES (para detectar la nueva sin depender de datos previos).
  const antesRes = await apiAlumno.get('/api/v1/reservas');
  expect(antesRes.ok()).toBeTruthy();
  const idsAntes = new Set(((await antesRes.json()) || []).map((r) => r.id));

  // 2. Reservar una clase de MAÑANA (día futuro). Se elige el día siguiente al de
  //    hoy para que la reserva quede "reservada" y no choque con la clase de hoy,
  //    que el alumno ya puede tener reservada de corridas anteriores del test.
  const diaManana = page.locator('button').filter({
    has: page.locator('span.block.text-lg', { hasText: new RegExp(`^${diaDeManana()}$`) }),
  }).first();
  await diaManana.waitFor({ state: 'visible', timeout: 45_000 });
  await diaManana.click();

  // Las secciones MAÑANA/TARDE arrancan colapsadas: hay que abrir una para ver el
  // botón "Reservar" de cada fila de la grilla.
  const seccion = page.getByRole('button', { name: /MAÑANA/ }).first();
  await seccion.waitFor({ state: 'visible', timeout: 20_000 });
  await seccion.click();

  const reservar = page.getByRole('button', { name: 'Reservar' }).first();
  await reservar.waitFor({ state: 'visible', timeout: 20_000 });
  await reservar.click();

  await expect(page.getByRole('button', { name: /Confirmar Reserva/ })).toBeVisible();
  await page.getByRole('button', { name: /Confirmar Reserva/ }).click();

  // 3. La reserva nueva se refleja en GET /reservas. Se espera por polling porque
  //    durante el submit el botón pasa a "Reservando..." (ya no matchea
  //    "Confirmar Reserva") y un `toBeHidden` pasaría antes de que el POST termine.
  let nueva;
  await expect.poll(async () => {
    const res = await apiAlumno.get('/api/v1/reservas');
    const data = await res.json();
    const lista = Array.isArray(data) ? data : [];
    nueva = lista.find((r) => !idsAntes.has(r.id));
    return Boolean(nueva);
  }, { timeout: 20_000, message: 'la reserva nueva debería reflejarse en GET /reservas' }).toBe(true);

  // La reserva quedó confirmada (el estado crudo es 'confirmada'; `estado_visible`
  // puede ser 'reservada' o 'falto' según si la clase de hoy ya pasó, así que no se
  // aserta un valor fijo).
  expect(nueva.estado).toBe('confirmada');

  // 4. Confirmar que aparece en el "Historial de Reservas" (UI). Se usa el encabezado
  //    de la tarjeta (h3 "🏋️ <disciplina>") y no getByText, porque el chip del filtro
  //    de disciplinas también contiene el nombre y puede estar oculto.
  await page.locator('nav').getByRole('link', { name: 'Historial de Reservas' }).click();
  await expect(page).toHaveURL(/\/alumno\/mis-reservas/);
  await expect(
    page.getByRole('heading', { name: nueva.disciplina_nombre || 'Clase' }).first()
  ).toBeVisible();

  // 5. Marcar asistencia con el endpoint de check-in del panel (staff/admin,
  //    determinístico: el admin no tiene la restricción de "mismo día" del coach).
  //    El contexto `request` COMPARTE las cookies del navegador: el `access_token`
  //    del alumno mandaría sobre el Bearer del admin (la cookie tiene prioridad),
  //    así que el login y el PUT van por un contexto SIN cookies.
  const adminApi = await playwright.request.newContext({
    baseURL: new URL(page.url()).origin,
    storageState: { cookies: [], origins: [] },
  });
  const adminLogin = await adminApi.post('/api/v1/auth/login', {
    data: { correo: admin.email, password: admin.password },
  });
  expect(adminLogin.ok(), 'login del admin para marcar asistencia').toBeTruthy();
  const adminToken = (await adminLogin.json()).access_token;
  // El login deja la cookie `access_token` en SU contexto; el PUT va por otro
  // contexto limpio que autentica SÓLO con Bearer (con la cookie, la mutación
  // exigiría el header CSRF y respondería 403).
  await adminApi.dispose();
  const adminMarcaApi = await playwright.request.newContext({
    baseURL: new URL(page.url()).origin,
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: { Authorization: `Bearer ${adminToken}` },
  });

  const marca = await adminMarcaApi.put(`/api/v1/reservas/${nueva.id}/asistencia`, {
    headers: { 'Content-Type': 'application/json' },
    data: { asistio: true },
  });
  expect(marca.ok(), `marcar asistencia de la reserva: ${marca.status()} ${await marca.text()}`)
    .toBeTruthy();
  expect((await marca.json()).asistio).toBe(true);
  await adminMarcaApi.dispose();

  // 6. Verificación: la reserva queda con `asistio === true`.
  const trasMarca = await apiAlumno.get('/api/v1/reservas');
  const marcada = ((await trasMarca.json()) || []).find((r) => r.id === nueva.id);
  expect(marcada.asistio).toBe(true);

  // 7. Limpieza: cancelar la reserva creada para no acumular datos en corridas
  //    repetidas (restaura el cupo, y el crédito si la clase es a >6h). Va por el
  //    contexto SIN cookies: el mismo DELETE con la cookie del navegador exigiría
  //    el header CSRF y quedaba en 403, dejando la reserva viva para la próxima.
  const limpieza = await apiAlumno.delete(`/api/v1/reservas/${nueva.id}`);
  expect(limpieza.ok(), 'cancelar la reserva de la prueba').toBeTruthy();
  await apiAlumno.dispose();
});

// Regresión Bloque 3: en el teléfono "Agendar Reserva" tiene que mostrar la
// grilla MÓVIL (selector de día + tarjetas + Reservar), la misma del Inicio, y
// NO la tabla de escritorio apretada. No reserva nada: sólo verifica qué UI se
// monta a 390px, así que no ensucia los datos.
test('agendar reserva en mobile muestra las tarjetas y no la tabla', async ({ page }) => {
  // Viewport de teléfono (iPhone 12/13): dispara el switch `md:hidden` (<768px).
  await page.setViewportSize({ width: 390, height: 844 });

  await login(page, creds().alumno);
  await expect(page).toHaveURL(/\/alumno\/dashboard/);

  // La pestaña del bug, abierta por URL directa.
  await page.goto('/alumno/agendar-reserva');
  await expect(page).toHaveURL(/\/alumno\/agendar-reserva/);

  // 1. Se ve la grilla móvil compartida: selector de día + al menos una tarjeta.
  const grillaMobile = page.getByTestId('ub-clases-mobile');
  await expect(grillaMobile).toBeVisible({ timeout: 45_000 });
  await expect(grillaMobile.getByRole('tablist', { name: 'Elige el día' })).toBeVisible();
  await expect(grillaMobile.getByTestId('ub-clase').first()).toBeVisible();

  // 2. Cada tarjeta ofrece su botón Reservar (o Lleno si no quedan cupos).
  await expect(
    grillaMobile.getByRole('button', { name: /Reservar|Lleno/ }).first()
  ).toBeVisible();

  // 3. La versión de escritorio queda en el DOM bajo `hidden md:block`: su tabla
  //    y su título no pueden verse en el teléfono.
  await expect(page.locator('table:visible')).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: /CLASES DISPONIBLES — PRÓXIMOS 7 DÍAS/ })
  ).toBeHidden();
});

