import { test, expect } from '@playwright/test';
import { creds, login } from '../helpers.js';

// Regresiones de la UI de planes:
//  1) el input "Monto ($)" de la matrícula tiene que aceptar lo que se tipea
//     (el bug era un onChange a un setter inexistente; un test de texto fuente
//     no lo detecta, por eso este test monta la pantalla real);
//  2) "Todos" tiene que apagar el filtro por género y mostrar planes de ambos.
test.describe('Planes: matrícula y filtro de categorías', () => {
    test('admin puede tipear el monto de la matrícula y el input lo refleja', async ({ page }) => {
        await login(page, creds().admin);
        await expect(page).toHaveURL(/\/admin\/dashboard/);

        await page.goto('/admin/planes');
        const input = page.getByTestId('monto-matricula');
        await expect(input).toBeVisible({ timeout: 60_000 });

        // `pressSequentially` dispara un onChange por tecla, como un humano.
        await input.click();
        await input.press('Control+A');
        await input.pressSequentially('54321');
        await expect(input).toHaveValue('54321');
    });

    test('alumno: "Todos" muestra planes de ambos géneros', async ({ page }) => {
        await login(page, creds().alumno);
        await expect(page).toHaveURL(/\/alumno\/dashboard/);

        await page.goto('/alumno/solicitar-plan');
        const botonMasculinos = page.getByRole('button', { name: /Masculinos/ });
        await expect(botonMasculinos).toBeVisible({ timeout: 60_000 });
        await expect(page.locator('button:has(h3)').first()).toBeVisible();

        // Primero filtramos a masculino: Princesa (femenino) no debe aparecer.
        await botonMasculinos.click();
        await expect(page.getByRole('heading', { name: 'Baby Chimp' })).toBeVisible();
        await expect(page.getByRole('heading', { name: 'Princesa' })).toHaveCount(0);

        // "Todos" ya no cae al sexo del alumno: se ven los dos géneros.
        await page.getByRole('button', { name: 'Todos', exact: true }).click();
        await expect(page.getByRole('heading', { name: 'Princesa' })).toBeVisible();
        await expect(page.getByRole('heading', { name: 'Baby Chimp' })).toBeVisible();
    });
});
