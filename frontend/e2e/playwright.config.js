import { defineConfig } from '@playwright/test';

// ─── Arnés E2E del frontend ─────────────────────────────────────────────
// Corre contra el stack completo de TEST ya levantado (ver README.md):
//   docker compose up -d    → backend :8001, frontend nginx :80, BD Neon TEST
//
// Navegador: usa Chrome del sistema por defecto (`channel`) para NO depender
// de la descarga del chromium bundled (que en esta red suele cortarse). Si
// prefieres el bundled: `npx playwright install chromium` y deja
// E2E_BROWSER_CHANNEL vacío (o 'chromium').
//
// Variables de entorno (opcionales salvo E2E_PASSWORD):
//   E2E_BASE_URL        → http://localhost
//   E2E_BROWSER_CHANNEL → chrome
//   E2E_PASSWORD        → TEST_SEED_PASSWORD de backend/.env.test (obligatoria)
//   E2E_ALUMNO_EMAIL    → carga_k6_alumno0001@load.test
//   E2E_COACH_EMAIL     → carga_k6_coach@load.test
//   E2E_ADMIN_EMAIL     → carga_k6_admin@load.test

const baseURL = process.env.E2E_BASE_URL || 'http://localhost';
const channel = process.env.E2E_BROWSER_CHANNEL || 'chrome';

export default defineConfig({
  testDir: './tests',
  // El backend de TEST (Neon) es lento en frío: se dejan márgenes amplios para
  // que los tests no fallen por timeouts de red.
  timeout: 300_000,
  expect: { timeout: 30_000 },
  // Los tests comparten sesión/estado (reservas), así que se corren en serie.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
  ],
  use: {
    baseURL,
    channel,
    headless: true,
    viewport: { width: 1280, height: 800 },
    // UA realista: el sandbox de Mercado Pago responde 403 al UA por defecto de
    // Playwright (`HeadlessChrome/...`). Con un UA de Chrome normal el checkout
    // carga (verificado contra sandbox.mercadopago.cl). Se puede sobrescribir.
    userAgent: process.env.E2E_USER_AGENT
      || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        + '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    locale: 'es-CL',
    extraHTTPHeaders: { 'Accept-Language': 'es-CL,es;q=0.9,en;q=0.8' },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  outputDir: 'test-results',
});
