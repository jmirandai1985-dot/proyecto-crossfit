// Test aislado del banner de estado del plan (Inicio del alumno).
//   Ejecutar:  node scripts/test-banner-plan.mjs   (npm run test:banner)
//
// Sin navegador ni framework: valida el copy específico del banner (días y/o
// créditos restantes + fecha de activación del plan en cola) y el flag
// `asegurado` que decide el candado vs el botón "Renovar", más los bordes
// (sin plan, ilimitado, singular, 0).
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

// ── CON plan_en_cola: informativo + candado (asegurado) ─────────────────────
{
    const b = textoBannerPlan(mem({ plan_en_cola: true, dias_restantes: 5, clases_disponibles: 10 }));
    eq(b.titulo, 'Te quedan 10 clases y 5 días.', 'en cola: título con días y créditos');
    eq(b.detalle, 'Tu próximo plan ya está pagado y se activa al día siguiente.', 'en cola sin fecha_vencimiento: fallback "al día siguiente"');
    eq(b.asegurado, true, 'en cola: candado (asegurado)');
}
{
    const b = textoBannerPlan(mem({ plan_en_cola: true, dias_restantes: 10, clases_disponibles: 3 }));
    eq(b.titulo, 'Te quedan 3 clases y 10 días.', 'en cola (clases): título con días y créditos');
    eq(b.asegurado, true, 'en cola (clases): candado (asegurado)');
}

// ── Fecha de activación derivada del vencimiento (+1 día) ───────────────────
{
    const b = textoBannerPlan(mem({ plan_en_cola: true, dias_restantes: 5, clases_disponibles: 10, fecha_vencimiento: '2025-05-12' }));
    eq(b.detalle, 'Tu próximo plan ya está pagado y se activa el 13 de mayo.', 'en cola + fecha: activación el día siguiente al vencimiento');
}

// ── SIN plan_en_cola: nudge + botón Renovar (sin candado) ───────────────────
{
    const b = textoBannerPlan(mem({ plan_en_cola: false, dias_restantes: 5, clases_disponibles: 10 }));
    eq(b.detalle, 'Renueva ahora para no quedarte sin clases.', 'sin cola: nudge de renovar');
    eq(b.asegurado, false, 'sin cola: botón Renovar (no candado)');
}
{
    const b = textoBannerPlan(mem({ plan_en_cola: false, dias_restantes: 10, clases_disponibles: 3 }));
    eq(b.detalle, 'Renueva ahora para no quedarte sin clases.', 'sin cola (clases): nudge de renovar');
    eq(b.asegurado, false, 'sin cola (clases): botón Renovar (no candado)');
}

// ── Ilimitado: siempre vence por fecha (nunca habla de clases) ─────────────
{
    const b = textoBannerPlan(mem({ es_ilimitado: true, dias_restantes: 10, clases_disponibles: null }));
    eq(b.titulo, 'Tu plan vence en 10 días.', 'ilimitado: siempre por fecha (aunque clases sea NULL/0)');
    ok(!b.titulo.includes('clases'), 'ilimitado: nunca habla de quedarse sin clases');
}

// ── Bordes de redacción (singular / 0) ──────────────────────────────────────
eq(textoBannerPlan(mem({ dias_restantes: 1, clases_disponibles: 10 })).titulo,
    'Te quedan 10 clases y 1 día.', 'singular: "1 día"');
eq(textoBannerPlan(mem({ dias_restantes: 0, clases_disponibles: 10 })).titulo,
    'Te quedan 10 clases y vence hoy.', '0 días: "vence hoy"');
eq(textoBannerPlan(mem({ dias_restantes: 10, clases_disponibles: 1 })).titulo,
    'Te quedan 1 clase y 10 días.', 'singular: "1 clase"');
eq(textoBannerPlan(mem({ dias_restantes: 10, clases_disponibles: 0 })).titulo,
    'Te quedan 0 clases y 10 días.', '0 clases: créditos agotados');

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
