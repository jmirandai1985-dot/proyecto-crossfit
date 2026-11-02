// Test aislado del banner de estado del plan (Inicio del alumno).
//   Ejecutar:  node scripts/test-banner-plan.mjs   (npm run test:banner)
//
// Sin navegador ni framework: valida la regla de "qué vence primero" (fecha vs
// clases) y el copy de las 4 combinaciones (plan_en_cola × vence-primero), más
// los bordes (sin plan, ilimitado, singular, 0).
import { textoBannerPlan } from '../src/utils/bannerPlan.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${JSON.stringify(esperado)} · obtenido: ${JSON.stringify(obtenido)})`);
    }
};
const ok = (cond, msg) => eq(Boolean(cond), true, msg);

const mem = (extra) => ({ activa: true, es_ilimitado: false, dias_restantes: 10, clases_disponibles: 5, plan_en_cola: false, ...extra });

// ── Sin plan activo: no hay banner ──────────────────────────────────────────
eq(textoBannerPlan({ activa: false }), null, 'sin plan activo -> null (no se dibuja)');
eq(textoBannerPlan(null), null, 'membresia nula -> null');

// ── CON plan_en_cola: informativo, sin botón ───────────────────────────────
{
    const b = textoBannerPlan(mem({ plan_en_cola: true, dias_restantes: 5, clases_disponibles: 10 }));
    eq(b.titulo, 'Tu plan vence en 5 días.', 'en cola + vence por fecha: título de días');
    eq(b.detalle, 'Cuando venza, tu próximo plan —ya pagado— se activa automáticamente al día siguiente.', 'en cola + fecha: detalle de activación al vencer');
    eq(b.mostrarRenovar, false, 'en cola: sin botón Renovar');
}
{
    const b = textoBannerPlan(mem({ plan_en_cola: true, dias_restantes: 10, clases_disponibles: 3 }));
    eq(b.titulo, 'Te quedan 3 clases.', 'en cola + vence por clases: título de clases');
    eq(b.detalle, 'Cuando se acaben, tu próximo plan —ya pagado— se activa automáticamente al día siguiente.', 'en cola + clases: detalle de activación al agotarse');
    eq(b.mostrarRenovar, false, 'en cola (clases): sin botón Renovar');
}

// ── SIN plan_en_cola: nudge + botón Renovar ─────────────────────────────────
{
    const b = textoBannerPlan(mem({ plan_en_cola: false, dias_restantes: 5, clases_disponibles: 10 }));
    eq(b.titulo, 'Tu plan vence en 5 días.', 'sin cola + vence por fecha: título de días');
    eq(b.detalle, 'Renueva ahora para no quedarte sin clases.', 'sin cola + fecha: nudge de renovar');
    eq(b.mostrarRenovar, true, 'sin cola: con botón Renovar');
}
{
    const b = textoBannerPlan(mem({ plan_en_cola: false, dias_restantes: 10, clases_disponibles: 3 }));
    eq(b.titulo, 'Te quedan 3 clases.', 'sin cola + vence por clases: título de clases');
    eq(b.detalle, 'Renueva ahora para no quedarte sin clases.', 'sin cola + clases: nudge de renovar');
    eq(b.mostrarRenovar, true, 'sin cola (clases): con botón Renovar');
}

// ── Ilimitado: siempre vence por fecha (nunca se queda sin clases) ─────────
{
    const b = textoBannerPlan(mem({ es_ilimitado: true, dias_restantes: 10, clases_disponibles: null }));
    eq(b.titulo, 'Tu plan vence en 10 días.', 'ilimitado: siempre por fecha (aunque clases sea NULL/0)');
    ok(!b.titulo.includes('clases'), 'ilimitado: nunca habla de quedarse sin clases');
}

// ── Bordes de redacción (singular / 0) ──────────────────────────────────────
eq(textoBannerPlan(mem({ dias_restantes: 1, clases_disponibles: 10 })).titulo,
    'Tu plan vence en 1 día.', 'singular: "1 día"');
eq(textoBannerPlan(mem({ dias_restantes: 0, clases_disponibles: 10 })).titulo,
    'Tu plan vence hoy.', '0 días: "vence hoy"');
eq(textoBannerPlan(mem({ dias_restantes: 10, clases_disponibles: 1 })).titulo,
    'Te queda 1 clase.', 'singular: "1 clase"');
eq(textoBannerPlan(mem({ dias_restantes: 10, clases_disponibles: 0 })).titulo,
    'Te quedan 0 clases.', '0 clases: plural "0 clases" (vence por clases)');

// ── El texto visible SIEMPRE dice "clases", nunca "créditos" ───────────────
{
    const casos = [
        mem({ plan_en_cola: true, dias_restantes: 5, clases_disponibles: 10 }),
        mem({ plan_en_cola: true, dias_restantes: 10, clases_disponibles: 3 }),
        mem({ plan_en_cola: false, dias_restantes: 5, clases_disponibles: 10 }),
        mem({ plan_en_cola: false, dias_restantes: 10, clases_disponibles: 3 }),
        mem({ es_ilimitado: true, dias_restantes: 10, clases_disponibles: null }),
    ];
    for (const c of casos) {
        const b = textoBannerPlan(c);
        ok(!b.titulo.includes('crédito') && !b.titulo.includes('credito'),
            `título sin "crédito(s)": "${b.titulo}"`);
        ok(!b.detalle.includes('crédito') && !b.detalle.includes('credito'),
            `detalle sin "crédito(s)": "${b.detalle}"`);
    }
}

console.log(`\n${fallos === 0 ? 'Todos los chequeos pasaron.' : `${fallos} chequeo(s) FALLARON.`}`);
process.exit(fallos === 0 ? 0 : 1);
