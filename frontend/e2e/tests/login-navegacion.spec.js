import { test, expect } from '@playwright/test';
import { creds, login } from '../helpers.js';

test.describe('Login + navegación básica por rol', () => {
  test('alumno aterriza en su dashboard y navega a Mis reservas', async ({ page }) => {
    await login(page, creds().alumno);

    // Aterriza en el dashboard correcto según rol.
    await expect(page).toHaveURL(/\/alumno\/dashboard/);
    const linkReservas = page.locator('nav').getByRole('link', { name: 'Mis Reservas' });
    await expect(linkReservas).toBeVisible();

    // Navegación básica: el link de Mis reservas responde y muestra su pantalla.
    await linkReservas.click();
    await expect(page).toHaveURL(/\/alumno\/mis-reservas/);
    await expect(page.getByRole('heading', { name: /Mis Reservas/ })).toBeVisible();

    // Volver a Inicio.
    await page.locator('nav').getByRole('link', { name: 'Inicio' }).click();
    await expect(page).toHaveURL(/\/alumno\/dashboard/);
  });

  test('coach aterriza en su dashboard y responde la sub-pestaña Clases', async ({ page }) => {
    await login(page, creds().coach);

    await expect(page).toHaveURL(/\/coach\/dashboard/);
    const tabClases = page.locator('nav').getByRole('link', { name: /Clases/ });
    await expect(tabClases).toBeVisible();

    await tabClases.click();
    await expect(page).toHaveURL(/\?tab=clases/);
  });

  test('admin aterriza en su dashboard y navega a Alumnos y Pendientes', async ({ page }) => {
    await login(page, creds().admin);

    await expect(page).toHaveURL(/\/admin\/dashboard/);

    await page.locator('nav').getByRole('link', { name: 'Alumnos' }).click();
    await expect(page).toHaveURL(/\/admin\/alumnos/);

    await page.locator('nav').getByRole('link', { name: 'Pendientes' }).click();
    await expect(page).toHaveURL(/\/admin\/pendientes/);
  });
});
