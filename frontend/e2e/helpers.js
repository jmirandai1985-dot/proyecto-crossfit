// Credenciales y helpers compartidos de los tests E2E.
//
// La CONTRASEÑA no se versiona (misma política que la Auditoría 4.1 del backend):
// sale de E2E_PASSWORD, que debe valer lo mismo que `TEST_SEED_PASSWORD`
// (backend/.env.test). Los correos son de los usuarios de carga k6 ya sembrados
// en la rama TEST de Neon; se pueden sobrescribir con las variables de entorno.

export function creds() {
  const password = process.env.E2E_PASSWORD;
  if (!password) {
    throw new Error(
      'Falta E2E_PASSWORD. Setea la clave de los usuarios de TEST ' +
      '(TEST_SEED_PASSWORD de backend/.env.test) antes de correr los tests.'
    );
  }
  return {
    alumno: {
      email: process.env.E2E_ALUMNO_EMAIL || 'carga_k6_alumno0001@load.test',
      password,
    },
    coach: {
      email: process.env.E2E_COACH_EMAIL || 'carga_k6_coach@load.test',
      password,
    },
    admin: {
      email: process.env.E2E_ADMIN_EMAIL || 'carga_k6_admin@load.test',
      password,
    },
  };
}

// Loguea con el formulario de /login y dispara la navegación al dashboard.
export async function login(page, { email, password }) {
  await page.goto('/login');
  // Se usan los ids (#correo / #password) en vez de getByLabel porque
  // getByLabel('Contraseña') también matchea el botón "Mostrar contraseña"
  // (su aria-label contiene la misma palabra) → strict mode violation.
  await page.locator('#correo').fill(email);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
}

// Token JWT del usuario logueado (para verificar contra los endpoints reales).
export async function tokenDe(page) {
  return page.evaluate(() => localStorage.getItem('access_token'));
}
