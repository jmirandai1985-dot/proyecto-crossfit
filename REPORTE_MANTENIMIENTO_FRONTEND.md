# Reporte mantenimiento frontend

Fecha: 2026-11-03 · Rama: `main` (working tree, sin commit ni push)

## a) Higiene de dependencias

- `npm update` (sólo patch/minor, **sin saltos de major**): 61 paquetes actualizados, 1 agregado.
- `npm audit`: **0 vulnerabilidades** (antes había 11: `vite@8.1.0` con varias altas —CVE de
  `launch-editor`/middleware— y `source-map-js`; `vite` quedó en `8.3.5`).
- `npm run build`: **OK** (vite 8.3.5, 2699 módulos).
- `npm run lint`: **0 errores** (78 warnings preexistentes de react-hooks).
- Tests `.mjs` del frontend: **47/51 pasan**. Las 4 fallas son preexistentes y ajenas a este
  cambio (ver apartado final).

## b) Íconos: lucide-react vs @fortawesome

Diagnóstico de uso en `src/`:

| Librería | Archivos que la importan | Estado |
|---|---|---|
| `lucide-react` | 16 (30 íconos distintos) | **En uso** |
| `@fortawesome/*` | 0 | Muerta (sin ningún import) |

- `@fortawesome/fontawesome-svg-core`, `@fortawesome/free-solid-svg-icons` y
  `@fortawesome/react-fontawesome` no se importaban en ningún archivo, así que **ya estaban
  fuera del bundle por tree-shaking** (0 bytes en `dist/`).
- Ahorro real al eliminarlas: **no es de bundle** (ya no pesaban), sino de dependencias
  muertas — menos superficie de `npm audit`, instalación más corta y `package.json` limpio.
- **Decisión:** quedarse con una sola librería (`lucide-react`). Se eliminaron los 3 paquetes
  `@fortawesome/*` + 1 transitivo (`npm uninstall`). No hay migración pendiente porque FA no
  se usaba.

## c) Observabilidad del bundle

- Se agregó `rollup-plugin-visualizer` a `frontend/vite.config.js`.
- Cada `npm run build` genera **`frontend/dist/stats.html`** (treemap con tamaño gzip por
  chunk/módulo) para poder frenar regresiones de tamaño.
- Tradeoff: el cálculo del reporte suma ~30 s al build; se dejó `brotliSize: false` para no
  pagar el costo de comprimir con brotli (el tamaño gzip alcanza para el objetivo).

## Tests `.mjs` con falla preexistente (NO relacionadas con este cambio)

Estas 4 fallas asertan sobre contenido de archivos de `src/` que **no se tocaron** en este
mantenimiento (sólo se modificaron `package.json`, `vite.config.js`, `.gitignore` y se
agregó `e2e/`):

- `test-boton-volver.mjs` → `App.jsx` tiene 13 rutas de alumno (el test espera 12) y
  `PagoResultado.jsx` no usa `BotonVolver`.
- `test-coach-sin-api.mjs` → `AlumnoFichaCoach.jsx` tiene una carga manual residual (`cargar`).
- `test-marketing.mjs` → carrusel (puntos de posición / tarjeta 82% / centrado).
- `test-notificaciones-panel.mjs` → la campana no debe hacer `DELETE`.
