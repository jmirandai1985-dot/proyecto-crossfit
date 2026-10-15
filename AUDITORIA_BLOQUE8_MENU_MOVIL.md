# Auditoría Bloque 8 — Menú lateral móvil (fuga de foco del drawer)

Fecha: 2026-10-15 · Autor: sesión de auditoría + fix aprobado por Jebbus
Precedente: `AUDITORIA_PANEL_COACH_FASE2.md` (diagnóstico de solo lectura de los 10 bloques).

## Qué se pidió

Arreglar la **fuga de foco con el drawer cerrado**: en `<768px` el sidebar se oculta con
`-translate-x-full` (sigue en el DOM), así que Tab y el lector de pantalla entraban a enlaces y
a "Cerrar Sesión" que no se ven. Decisión del usuario: **no** arreglar el corte de 8 px del
último ítem en 375×568 (pantalla muy chica, impacto mínimo) → queda en backlog.

## Evidencia del hallazgo (antes)

`frontend/src/components/Layout.jsx` tenía el sidebar cerrado **sin ninguna marca de
accesibilidad**: sólo la clase de traslado.

- La medición del harness (que ya existía para el menú) devolvía, con el drawer **cerrado**:
  `sidebar.left: -256`, `right: 0` (fuera de pantalla ✓) pero `ariaHidden: null`,
  `inert: false` y `enArbolDeFoco: true` → el nodo seguía siendo navegable.
- El único corte visual era en 375×568: el último ítem quedaba 8 px bajo el pliegue.

## Qué se cambió (sólo `Layout.jsx`)

| línea | qué |
|---|---|
| 18-21 | estado `esEscritorio` (¿estamos en `>=768px`?) |
| 73-81 | `matchMedia('(min-width: 768px)')` con listener: la bandera dice lo MISMO que las clases `md:*` |
| 83-88 | `const drawerOculto = !esEscritorio && !mobileOpen` (sólo aplica al drawer, nunca a la barra estática) |
| 112-120 | en el contenedor del sidebar: `aria-hidden={drawerOculto ? 'true' : undefined}` (119) e `inert={drawerOculto \|\| undefined}` (120) |

Por qué las dos marcas: `aria-hidden` saca el subárbol del **lector de pantalla** e `inert` saca
el **foco** (teclado). Y por qué el chequeo de `>=768px`: en escritorio la misma `<div>` es la
barra estática y visible; dejarla `inert` mataría el menú para el teclado.

## Verificación (después) — números, no impresiones

El harness ahora mide también el **comportamiento**, no sólo los atributos: hace
`focus()` sobre el primer enlace del sidebar y mira si el foco se movió
(`focoEntraAlSidebar`, `scripts/capturas-bloque2.mjs`).

| corrida | `ariaHidden` | `inert` | `focoEntraAlSidebar` |
|---|---|---|---|
| **cerrado** 375×667 (antes) | `null` | `false` | *(no existía la medición; `enArbolDeFoco: true`)* |
| **cerrado** 375×667 (después) | `"true"` | `true` | **`false`** |
| abierto 375×667 | `null` | `false` | `true` |
| abierto 390×844 / 414×896 / 375×568 | `null` | `false` | `true` |
| escritorio 1280×900 (sin hamburguesa) | `null` | `false` | `true` |

`focoEntraAlSidebar: false` con el drawer cerrado es la prueba dura de que el foco ya no entra;
`true` cuando está abierto (y en escritorio) es la contraprueba de que no quedó muerto.

### Capturas

`mockup/_audit/bloque8-menu-movil/` — **7/7**, 0 errores de consola:

```
01-escritorio-1280 · 02-movil-375-cerrado · 03-movil-375-abierto · 04-movil-390-abierto
05-movil-414-abierto · 06-movil-375x568-abierto · 07-movil-375-tab-asistencia
```

Cómo se reproduce:

```
cd frontend
$env:PANTALLA='menu'; node scripts/capturas-bloque2.mjs          # las 7
$env:PANTALLA='menu'; $env:SOLO='01,02,03'; node scripts/capturas-bloque2.mjs   # sólo algunas
```

## Backlog (decisión del usuario: no tocar)

1. 375×568: el último ítem del menú queda 8 px bajo el pliegue (con scroll dentro de `nav`).
2. El drawer cerrado sigue existiendo en el DOM (trasladado): con `inert` ya no molesta al
   teclado ni al lector, pero un `hidden` real ahorraría pintado — cambio de mayor riesgo, sin
   beneficio medible hoy.

## Tests de lógica re-corridos

`test:menu` (config de menús, 6 chequeos) → `TODO OK`. `test:coach-subtabs`, `test:coach-resumen`,
`test:walkin`, `test:fidelizacion`, `test:alumnos`, `test:franjas` → todos verdes después del cambio.
