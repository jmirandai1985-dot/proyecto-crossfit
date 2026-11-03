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
test('alumno reserva clase, la ve en Mis reservas y se le marca asistencia', async ({ page, request }) => {
  const { alumno, admin } = creds();

  // 1. Login del alumno por UI.
  await login(page, alumno);
  await expect(page).toHaveURL(/\/alumno\/dashboard/);

  // Token del alumno para verificar contra los endpoints reales (mismo origen).
  const token = await tokenDe(page);
  const auth = { Authorization: `Bearer ${token}` };

  // Reservas ANTES (para detectar la nueva sin depender de datos previos).
  const antesRes = await request.get('/api/v1/reservas', { headers: auth });
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
    const res = await request.get('/api/v1/reservas', { headers: auth });
    const data = await res.json();
    const lista = Array.isArray(data) ? data : [];
    nueva = lista.find((r) => !idsAntes.has(r.id));
    return Boolean(nueva);
  }, { timeout: 20_000, message: 'la reserva nueva debería reflejarse en GET /reservas' }).toBe(true);

  // La reserva quedó confirmada (el estado crudo es 'confirmada'; `estado_visible`
  // puede ser 'reservada' o 'falto' según si la clase de hoy ya pasó, así que no se
  // aserta un valor fijo).
  expect(nueva.estado).toBe('confirmada');

  // 4. Confirmar que aparece en "Mis reservas" (UI). Se usa el encabezado de la
  //    tarjeta (h3 "🏋️ <disciplina>") y no getByText, porque el chip del filtro de
  //    disciplinas también contiene el nombre y puede estar oculto.
  await page.locator('nav').getByRole('link', { name: 'Mis Reservas' }).click();
  await expect(page).toHaveURL(/\/alumno\/mis-reservas/);
  await expect(
    page.getByRole('heading', { name: nueva.disciplina_nombre || 'Clase' }).first()
  ).toBeVisible();

  // 5. Marcar asistencia con el endpoint de check-in del panel (staff/admin,
  //    determinístico: el admin no tiene la restricción de "mismo día" del coach).
  const adminLogin = await request.post('/api/v1/auth/login', {
    data: { correo: admin.email, password: admin.password },
  });
  expect(adminLogin.ok(), 'login del admin para marcar asistencia').toBeTruthy();
  const adminToken = (await adminLogin.json()).access_token;

  const marca = await request.put(`/api/v1/reservas/${nueva.id}/asistencia`, {
    headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
    data: { asistio: true },
  });
  expect(marca.ok(), 'marcar asistencia de la reserva').toBeTruthy();
  expect((await marca.json()).asistio).toBe(true);

  // 6. Verificación: la reserva queda con `asistio === true`.
  const trasMarca = await request.get('/api/v1/reservas', { headers: auth });
  const marcada = ((await trasMarca.json()) || []).find((r) => r.id === nueva.id);
  expect(marcada.asistio).toBe(true);

  // 7. Limpieza best-effort: cancelar la reserva creada para no acumular datos en
  //    corridas repetidas (restaura el cupo/crédito). No falla el test si no corre.
  try {
    await request.delete(`/api/v1/reservas/${nueva.id}`, { headers: auth });
  } catch {
    // best-effort: la corrida siguiente puede chocar con "ya reservada"; ver README.
  }
});
