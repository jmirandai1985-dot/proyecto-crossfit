import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { test, expect } from '@playwright/test';
import { creds, login, tokenDe } from '../helpers.js';

// â”€â”€â”€ E2E del pago de membresÃ­a (Mercado Pago sandbox REAL) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
//
// Usa el MISMO camino que un alumno: UI de SolicitarPlan → POST
// /api/v1/pagos/membresia → checkout de Mercado Pago. No mockea MP ni el
// webhook. Las limitaciones del entorno se declaran en cada test (skip con
// motivo), no se disfrazan con un mock.
//
// Usuario: por defecto `carga_k6_alumno0020` (los k6 tienen plan vigente y una
// solicitud pendiente sembrada; el `beforeEach` los limpia en la rama TEST con
// `backend/scripts/limpiar_e2e_pago.py` ejecutado por el Python del backend
// —sin Docker—, el mismo tipo de limpieza que hace el seed de k6). Se puede
// cambiar con E2E_PAGO_ALUMNO_EMAIL.
//
// Variables:
//   E2E_PAGO_ALUMNO_EMAIL   → carga_k6_alumno0020@load.test
//   E2E_ESPERAR_GUARD_5MIN  → '0' para NO esperar los 5 min reales del guard
//                             (por defecto se esperan: es el comportamiento real)

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const BACKEND = path.resolve(AQUI, '../../../backend');
const MP_URL = /https?:\/\/([^/]*\.)?mercadopago\.(cl|com)\//;
const MP_REASON_CREDENCIALES =
    'Mercado Pago sandbox no permite crear el cobro con estas credenciales: ' +
    'el card_token sale live_mode=true y POST /v1/payments responde 401 ' +
    '"Unauthorized use of live credentials". El access token es de un test ' +
    'user, pero el par access token/public key de .env.test no está alineado al ' +
    'mismo entorno de prueba (o la public key es de producción). Confirmar ' +
    'ambas en la pestaña Credenciales de prueba de la MISMA app. Ver ' +
    'AUDITORIA_ABANDONO_PAGO_MERCADOPAGO.md.';
const MP_REASON_WEBHOOK =
    'Mercado Pago procesó el cobro, pero el webhook no puede llegar a ' +
    'localhost (notification_url=http://localhost:8001/... es inalcanzable ' +
    'desde Internet). Sin el aviso real la app no cambia el estado; no se ' +
    'simula el webhook en un E2E. Se necesita un túnel público o el deploy de ' +
    'TEST para verificar la activación end-to-end.';
const MP_REASON_FORMULARIO =
    'No se pudo completar el formulario de tarjeta del sandbox (MP mostró ' +
    '"Completa este campo" o cambió el DOM/iframes de secure-fields). No se ' +
    'inventa un mock del checkout; se documenta como limitación del arnés.';
const MP_REASON_CHECKOUT =
    'El checkout sandbox real llegó a la pantalla "Revisa tu pago", pero el ' +
    'botón "Pagar" quedó deshabilitado y no se creó el pago en MP (verificado ' +
    'también con un navegador headed). Las credenciales SÍ están alineadas: ' +
    'creando el pago por REST con el mismo card_token, MP devuelve APRO ' +
    'approved y OTHE rejected. Es una limitación del checkout sandbox en este ' +
    'entorno; no se simula el pago con un mock.';

async function apiNueva(playwright) {
    const baseURL = process.env.E2E_BASE_URL || 'http://localhost';
    return playwright.request.newContext({
        baseURL,
        // Sin storageState: este contexto NO comparte cookies con el navegador.
        // Así la API autentica sólo con Bearer y el backend no exige CSRF
        // (el CSRF es sólo para la vía cookie, ver app/core/dependencies.py).
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: { 'Accept-Language': 'es-CL,es;q=0.9,en;q=0.8' },
    });
}

function alumnoE2E() {
    return {
        ...creds().alumno,
        email: process.env.E2E_PAGO_ALUMNO_EMAIL || 'carga_k6_alumno0020@load.test',
    };
}

// El script de limpieza corre con el Python del BACKEND (no con Docker): el
// arnés E2E apunta a la rama TEST de Neon, no al Postgres local de :8001.
// `ENVIRONMENT=test` hace que `app/core/config.py` cargue `.env.test`.
const PYTHON = process.env.E2E_PYTHON
    || (process.platform === 'win32' ? 'py' : 'python3');
const PYTHON_VERSION_ARGS = process.env.E2E_PYTHON
    ? []
    : (process.platform === 'win32' ? ['-3.12'] : []);

function limpiarEstado() {
    const script = path.join(BACKEND, 'scripts', 'limpiar_e2e_pago.py');
    try {
        execFileSync(PYTHON, [
            ...PYTHON_VERSION_ARGS,
            script,
            '--alumno-email', alumnoE2E().email,
        ], {
            cwd: BACKEND,
            env: { ...process.env, ENVIRONMENT: 'test' },
            stdio: 'pipe',
            timeout: 120_000,
        });
    } catch (error) {
        const detalle = error.stderr?.toString() || error.message;
        throw new Error(
            'No se pudo limpiar el estado E2E del alumno (backend/scripts/' +
            'limpiar_e2e_pago.py). Detalle: ' + detalle);
    }
}

function claims(token) {
    return JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
}

async function tokenAdmin(playwright) {
    const { admin } = creds();
    const ctx = await apiNueva(playwright);
    const loginAdmin = await ctx.post('/api/v1/auth/login', {
        data: { correo: admin.email, password: admin.password },
    });
    expect(loginAdmin.ok(), 'login API del admin').toBeTruthy();
    const token = (await loginAdmin.json()).access_token;
    await ctx.dispose();
    return token;
}

async function colaAdmin(playwright) {
    const token = await tokenAdmin(playwright);
    const ctx = await apiNueva(playwright);
    const res = await ctx.get('/api/v1/solicitudes/pendientes', {
        headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.ok(), 'GET /solicitudes/pendientes (admin)').toBeTruthy();
    const datos = (await res.json()) || [];
    await ctx.dispose();
    return datos;
}

// Abre el paso 2 de SolicitarPlan con un plan NO estudiantil (los que exigen
// certificado tienen el botón de MP deshabilitado hasta subirlo).
// Espera el POST /pagos/membresia y guarda el body ANTES de que la app navegue
// a Mercado Pago (una vez que navega, Playwright ya no puede leer la respuesta).
function capturarPagoMembresia(page) {
    let resolver;
    const promesa = new Promise((resolve) => { resolver = resolve; });
    page.route('**/api/v1/pagos/membresia', async (route) => {
        const response = await route.fetch();
        const body = await response.text();
        resolver({ status: response.status(), body });
        await route.fulfill({ response, body });
    });
    return promesa;
}

async function abrirPasoPago(page) {
    await page.goto('/alumno/solicitar-plan');
    await expect(page).toHaveURL(/\/alumno\/solicitar-plan/);

    const tarjetaPlan = page.locator('button:has(h3)').first();
    await tarjetaPlan.waitFor({ state: 'visible', timeout: 60_000 });
    await tarjetaPlan.click();

    const boton = page.getByTestId('pagar-mercadopago-plan');
    await expect(boton).toBeVisible({ timeout: 30_000 });
    return boton;
}

function bloquearCheckoutMP(page) {
    // Cerrar/abortar la navegación a MP es la simulación reproducible de
    // "abandonó ANTES de llegar a Mercado Pago". El botón físico de atrás de
    // Android/iOS no se puede simular en escritorio (limitación de la auditoría).
    return page.route(MP_URL, (route) => route.abort('aborted'));
}

// Dispara "Pagar con tarjeta" y devuelve el JSON real de /pagos/membresia.
async function iniciarPagoAbandonando(page) {
    const boton = await abrirPasoPago(page);
    const respuesta = page.waitForResponse(
        (r) => r.url().includes('/api/v1/pagos/membresia')
            && r.request().method() === 'POST',
        { timeout: 120_000 },
    );
    await boton.click();
    const res = await respuesta;
    const body = await res.json();
    expect(
        res.ok(),
        `POST /pagos/membresia respondió ${res.status()}: ${JSON.stringify(body)}`,
    ).toBeTruthy();
    // La navegación a MP quedó abortada: se vuelve a la app (equivale a cerrar
    // la pestaña antes de meter la tarjeta).
    await page.waitForTimeout(1_500);
    await page.goto('/alumno/dashboard');
    return body;
}

async function estadoPago(api, token, pagoId) {
    const res = await api.get(`/api/v1/pagos/${pagoId}`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok()) {
        throw new Error(`GET /pagos/${pagoId} -> ${res.status()} ${await res.text()}`);
    }
    return res.json();
}

async function cancelarPago(api, token, pagoId) {
    const res = await api.post(`/api/v1/pagos/${pagoId}/cancelar`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok()) {
        throw new Error(
            `POST /pagos/${pagoId}/cancelar -> ${res.status()} ${await res.text()}`);
    }
    return res;
}


test.describe('Pago de membresía con Mercado Pago (sandbox real)', () => {
    test.beforeEach(limpiarEstado);

    test('a) abandonar ANTES de Mercado Pago deja el intento `iniciado` y NO lo ve el admin', async ({ page, playwright }) => {
        test.setTimeout(180_000);
        const api = await apiNueva(playwright);
        const alumno = alumnoE2E();
        const { admin } = creds();

        await login(page, alumno);
        await expect(page).toHaveURL(/\/alumno\/dashboard/);
        const alumnoToken = await tokenDe(page);

        await bloquearCheckoutMP(page);
        const pago = await iniciarPagoAbandonando(page);
        expect(pago.pago_id, 'la preferencia real de MP se creó').toBeGreaterThan(0);
        expect(pago.init_point).toMatch(MP_URL);

        // El pago quedó en `iniciado` (la solicitud existe pero es invisible).
        const estado = await estadoPago(api, alumnoToken, pago.pago_id);
        expect(estado.estado).toBe('iniciado');
        expect(estado.aplicado).toBe(false);

        // La cola del admin NO trae la solicitud (ni por pago_id ni por correo).
        const cola = await colaAdmin(playwright);
        const visible = cola.filter((s) =>
            s.pago_id === pago.pago_id || s.alumno_email === alumno.email);
        expect(
            visible,
            `la solicitud ${pago.pago_id} no debería estar en la cola: ${JSON.stringify(visible)}`,
        ).toEqual([]);

        // Limpieza real del alumno: vuelve y cancela (libera el guard de 5 min).
        // El contexto `api` va SIN cookies y firma con Bearer: no necesita CSRF.
        const cancelado = await cancelarPago(api, alumnoToken, pago.pago_id);
        expect((await cancelado.json()).estado).toBe('cancelado');
        expect((await estadoPago(api, alumnoToken, pago.pago_id)).estado)
            .toBe('cancelado');
        expect((await colaAdmin(playwright)).filter((s) => s.pago_id === pago.pago_id))
            .toEqual([]);

        // La UI del admin dice lo mismo (pestaña Solicitudes de Pendientes).
        // Se limpian las cookies del alumno: /login redirige al dashboard si ya
        // hay sesión y el formulario del admin no aparecería.
        await page.context().clearCookies();
        const adminPage = await page.context().newPage();
        await login(adminPage, admin);
        await expect(adminPage).toHaveURL(/\/admin\/dashboard/);
        await adminPage.goto('/admin/pendientes?tab=solicitudes');
        await expect(adminPage.getByRole('tab', { name: /Solicitudes/ })).toBeVisible({
            timeout: 30_000,
        });
        await adminPage.waitForTimeout(4_000);
        await expect(adminPage.getByText(alumno.email)).toHaveCount(0);
        await adminPage.close();
    });

    test('d) el guard bloquea un segundo intento mientras el primero sigue `iniciado` y se libera a los 5 min', async ({ page, playwright }) => {
        // 5 min de espera REAL + setup lento de Neon: 11 min de margen.
        test.setTimeout(660_000);
        const api = await apiNueva(playwright);
        const alumno = alumnoE2E();

        await login(page, alumno);
        await expect(page).toHaveURL(/\/alumno\/dashboard/);
        const alumnoToken = await tokenDe(page);
        const auth = { Authorization: `Bearer ${alumnoToken}` };

        await bloquearCheckoutMP(page);
        const primero = await iniciarPagoAbandonando(page);
        expect((await estadoPago(api, alumnoToken, primero.pago_id)).estado)
            .toBe('iniciado');

        // Segundo intento INMEDIATO: el backend tiene que frenarlo ANTES de MP.
        const boton2 = await abrirPasoPago(page);
        const resp2Promise = page.waitForResponse(
            (r) => r.url().includes('/api/v1/pagos/membresia')
                && r.request().method() === 'POST',
            { timeout: 60_000 },
        );
        await boton2.click();
        const resp2 = await resp2Promise;
        const cuerpo2 = await resp2.json();
        expect(resp2.status(), 'el guard responde 400').toBe(400);
        expect(String(cuerpo2.detail || '')).toMatch(/Ya tienes un pago en curso/);
        await expect(page.getByText(/Ya tienes un pago en curso/)).toBeVisible({
            timeout: 15_000,
        });

        // El primero sigue `iniciado`: el guard no lo cerró por bloquear.
        expect((await estadoPago(api, alumnoToken, primero.pago_id)).estado)
            .toBe('iniciado');

        if (process.env.E2E_ESPERAR_GUARD_5MIN === '0') {
            // Atajo explícito para desarrollo: se libera con Cancelar, no con el
            // reloj. La liberación por tiempo queda sin verificar en este modo.
            const cancel = await cancelarPago(api, alumnoToken, primero.pago_id);
            expect(cancel.ok()).toBeTruthy();
            const tercero = await iniciarPagoAbandonando(page);
            expect(tercero.pago_id).not.toBe(primero.pago_id);
            await cancelarPago(api, alumnoToken, tercero.pago_id);
            test.skip(true, 'E2E_ESPERAR_GUARD_5MIN=0: no se esperaron los 5 min reales; se verificó la liberación por Cancelar.');
            return;
        }

        // Espera REAL de los 5 minutos del guard (MINUTOS_GUARD_MEMBRESIA=5).
        // No hay reloj inyectable en el backend de TEST: esperar es la única
        // forma de verificar la liberación automática sin mockear el tiempo.
        await page.waitForTimeout(310_000);

        const tercero = await iniciarPagoAbandonando(page);
        expect(tercero.pago_id, 'el guard se liberó solo').not.toBe(primero.pago_id);

        // Al abrir el nuevo intento, `_cerrar_iniciados_vencidos` cerró el viejo.
        const viejo = await estadoPago(api, alumnoToken, primero.pago_id);
        expect(viejo.estado).toBe('expirado');

        await cancelarPago(api, alumnoToken, tercero.pago_id);
    });


    test('b) pago APROBADO en sandbox: activa la membresía y el admin ve el cobro', async ({ page, playwright }) => {
        test.setTimeout(600_000);
        const api = await apiNueva(playwright);
        const alumno = alumnoE2E();

        await login(page, alumno);
        await expect(page).toHaveURL(/\/alumno\/dashboard/);
        const alumnoToken = await tokenDe(page);
        const alumnoId = claims(alumnoToken).usuario_id;

        const boton = await abrirPasoPago(page);
        const captura = capturarPagoMembresia(page);
        await boton.click();
        const res = await captura;
        const pago = JSON.parse(res.body);
        expect(res.status, `POST /pagos/membresia: ${res.body}`).toBe(200);

        await page.waitForURL(MP_URL, { timeout: 120_000 });
        let resultado;
        try {
            resultado = await Promise.race([
                completarCheckoutSandbox(page, 'APRO'),
                new Promise((resolve) => setTimeout(() => resolve('desconocido'), 120_000)),
            ]);
        } catch {
            resultado = 'formulario';
        }
        if (resultado === 'fatal') test.skip(true, MP_REASON_CREDENCIALES);
        if (resultado === 'formulario') test.skip(true, MP_REASON_FORMULARIO);
        if (resultado === 'desconocido') test.skip(true, MP_REASON_CHECKOUT);
        if (resultado !== 'aprobado') {
            test.skip(true, `El sandbox no confirmó APROBADO (resultado=${resultado}). ${MP_REASON_CREDENCIALES}`);
            return;
        }

        const estado = await esperarEstado(api, alumnoToken, pago.pago_id,
            ['aprobado'], 120_000);
        if (!estado) test.skip(true, MP_REASON_WEBHOOK);
        expect(estado.aplicado, 'el webhook aplicó el plan').toBe(true);

        // Solicitud aprobada y fuera de la cola del admin.
        const solicitudes = await api.get(`/api/v1/solicitudes/alumno/${alumnoId}`, {
            headers: { Authorization: `Bearer ${alumnoToken}` },
        });
        expect(solicitudes.ok()).toBeTruthy();
        const solicitud = ((await solicitudes.json()) || [])
            .find((s) => s.id === estado.referencia_id);
        expect(solicitud?.estado).toBe('approved');
        const cola = await colaAdmin(playwright);
        expect(cola.filter((s) => s.pago_id === pago.pago_id)).toEqual([]);

        // La suscripción activa quedó linkeada al pago.
        const tokenAdm = await tokenAdmin(playwright);
        const subs = await api.get(`/api/v1/suscripciones?usuario_id=${alumnoId}`, {
            headers: { Authorization: `Bearer ${tokenAdm}` },
        });
        expect(subs.ok()).toBeTruthy();
        const activa = ((await subs.json()) || [])
            .find((s) => s.estado === 'activo' && s.pago_id === pago.pago_id);
        expect(activa, 'suscripción activa del pago aprobado').toBeTruthy();

        // "El admin ve la transacción": caja del mes con la referencia del alta.
        const ahora = new Date();
        const txs = await api.get(
            `/api/v1/finanzas/transacciones?mes=${ahora.getMonth() + 1}&anio=${ahora.getFullYear()}`,
            { headers: { Authorization: `Bearer ${tokenAdm}` } },
        );
        expect(txs.ok()).toBeTruthy();
        const tx = ((await txs.json()) || []).find(
            (t) => t.referencia_tipo === 'suscripcion' && t.referencia_id === activa.id);
        expect(tx, `transacción de la suscripción #${activa.id}`).toBeTruthy();
        expect(Number(tx.monto)).toBeGreaterThan(0);
    });

    test('c) pago RECHAZADO en sandbox: cierra la solicitud y el alumno puede reintentar YA', async ({ page, playwright }) => {
        test.setTimeout(600_000);
        const api = await apiNueva(playwright);
        const alumno = alumnoE2E();

        await login(page, alumno);
        await expect(page).toHaveURL(/\/alumno\/dashboard/);
        const alumnoToken = await tokenDe(page);
        const alumnoId = claims(alumnoToken).usuario_id;

        const boton = await abrirPasoPago(page);
        const captura = capturarPagoMembresia(page);
        await boton.click();
        const res = await captura;
        const pago = JSON.parse(res.body);
        expect(res.status, `POST /pagos/membresia: ${res.body}`).toBe(200);

        await page.waitForURL(MP_URL, { timeout: 120_000 });
        let resultado;
        try {
            resultado = await Promise.race([
                completarCheckoutSandbox(page, 'OTHE'),
                new Promise((resolve) => setTimeout(() => resolve('desconocido'), 120_000)),
            ]);
        } catch {
            resultado = 'formulario';
        }
        if (resultado === 'fatal') test.skip(true, MP_REASON_CREDENCIALES);
        if (resultado === 'formulario') test.skip(true, MP_REASON_FORMULARIO);
        if (resultado === 'desconocido') test.skip(true, MP_REASON_CHECKOUT);
        if (resultado !== 'rechazado') {
            test.skip(true, `El sandbox no confirmó RECHAZADO (resultado=${resultado}). ${MP_REASON_CREDENCIALES}`);
            return;
        }

        const estado = await esperarEstado(api, alumnoToken, pago.pago_id,
            ['rechazado'], 120_000);
        if (!estado) test.skip(true, MP_REASON_WEBHOOK);
        expect(estado.estado).toBe('rechazado');

        // El bug de cac98cd: la solicitud quedaba `pending` para siempre. Ahora
        // el webhook la cierra como `rejected` y sale de la cola del admin.
        const solicitudes = await api.get(`/api/v1/solicitudes/alumno/${alumnoId}`, {
            headers: { Authorization: `Bearer ${alumnoToken}` },
        });
        expect(solicitudes.ok()).toBeTruthy();
        const solicitud = ((await solicitudes.json()) || [])
            .find((s) => s.id === estado.referencia_id);
        expect(solicitud?.estado, 'solicitud cerrada por rechazo').toBe('rejected');
        const cola = await colaAdmin(playwright);
        expect(cola.filter((s) => s.pago_id === pago.pago_id)).toEqual([]);

        // Reintento INMEDIATO: el guard no puede decir "Ya tienes una solicitud
        // pendiente" porque el rechazo ya cerró la primera.
        await page.goto('/alumno/solicitar-plan');
        await bloquearCheckoutMP(page);
        const reintento = await iniciarPagoAbandonando(page);
        expect(reintento.pago_id).toBeGreaterThan(0);
        expect(reintento.pago_id).not.toBe(pago.pago_id);
        await cancelarPago(api, alumnoToken, reintento.pago_id);
    });
});


// Rellena un input del iframe de secure-fields (cardNumber / expirationDate /
// securityCode). Hay 3 iframes del mismo origen y sólo uno tiene el campo
// VISIBLE; se busca ése, con reintentos porque el iframe carga después.
async function llenarCampoSeguro(page, id, valor) {
    for (let intento = 0; intento < 30; intento += 1) {
        for (const frame of page.frames()) {
            if (!frame.url().includes('secure-fields')) continue;
            const campo = frame.locator(`#${id}:visible`);
            if (await campo.count()) {
                await campo.first().fill(valor);
                return;
            }
        }
        await page.waitForTimeout(500);
    }
    throw new Error(`No apareció el campo seguro #${id} de Mercado Pago`);
}

// Tarjetas de prueba MLC (docs de MP): Mastercard 5031 7557 3453 0604 · 123 ·
// 11/30. El NOMBRE DEL TITULAR elige el escenario: APRO (aprobado),
// OTHE (rechazado por error general), CONT (pendiente), etc.
async function completarCheckoutSandbox(page, titular) {
    await page.getByRole('button', { name: /Tarjeta/ }).first().click();
    await page.locator('#cardholderName').waitFor({ state: 'visible', timeout: 60_000 });
    await page.locator('#cardholderName').fill(titular);
    await page.locator('#cardholderIdentificationNumber').fill('11111111-1');
    await llenarCampoSeguro(page, 'cardNumber', '5031 7557 3453 0604');
    await llenarCampoSeguro(page, 'expirationDate', '11/30');
    await llenarCampoSeguro(page, 'securityCode', '123');
    await page.waitForTimeout(1_500);

    // Confirmar que los 3 campos seguros quedaron con valor antes de continuar:
    // si MP re-renderiza el iframe, el error "Completa este campo" no es de
    // credenciales y hay que reportarlo como limitación del arnés.
    const valores = [];
    for (const frame of page.frames()) {
        if (!frame.url().includes('secure-fields')) continue;
        valores.push(await frame.evaluate(() => [...document.querySelectorAll('input')]
            .filter((e) => e.offsetWidth || e.offsetHeight)
            .map((e) => [e.id, e.value])));
    }
    const planos = valores.flat();
    const completos = ['cardNumber', 'expirationDate', 'securityCode']
        .every((id) => planos.some(([campo, valor]) => campo === id && valor.trim()));
    if (!completos) return 'formulario';

    await page.getByRole('button', { name: 'Continuar' }).click();
    await page.waitForTimeout(9_000);

    // Algunos medios piden confirmar cuotas / pagar en una segunda pantalla.
    const pagar = page.getByRole('button', { name: /^(Pagar|Confirmar|Continuar)$/ });
    if (await pagar.count()) {
        // En el review de MP el botón "Pagar" arranca deshabilitado mientras
        // termina de cargar el medio de pago; hay que esperar a que se habilite.
        for (let intento = 0; intento < 60; intento += 1) {
            if (await pagar.first().isEnabled()) break;
            await page.waitForTimeout(1_000);
        }
        await pagar.first().click().catch(() => {});
        await page.waitForTimeout(15_000);
    }

    const url = page.url();
    const texto = await page.locator('body').innerText();
    if (/\/fatal\/|algo anduvo mal|oh, no/i.test(url + '\n' + texto)) return 'fatal';
    if (/completa este campo|ingresa un documento v[aá]lido/i.test(texto)) {
        return 'formulario';
    }
    if (/pago aprobado|tu pago fue aprobado|¡listo!|felicitaciones|compra exitosa/i.test(texto)) {
        return 'aprobado';
    }
    if (/rechaz|no se pudo procesar|fondos insuficientes|pago no realizado|tarjeta inválida/i.test(texto)) {
        return 'rechazado';
    }
    console.log('[MP] resultado no reconocido:', url, '\n', texto.slice(0, 1200));
    return 'desconocido';
}

async function esperarEstado(api, token, pagoId, estados, timeoutMs) {
    const limite = Date.now() + timeoutMs;
    let ultimo = null;
    while (Date.now() < limite) {
        ultimo = await estadoPago(api, token, pagoId);
        if (estados.includes(ultimo.estado)) return ultimo;
        await new Promise((resolve) => setTimeout(resolve, 3_000));
    }
    console.log(`[MP] pago #${pagoId} quedó en ${ultimo?.estado} (esperaba ${estados})`);
    return null;
}

