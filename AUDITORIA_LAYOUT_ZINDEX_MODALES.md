# Auditoría — el `z-10` del Layout atrapaba TODOS los modales debajo del header

Fecha: 2026-10-15 · Autor: sesión de auditoría
**Decisión aprobada por Jebbus (15-oct): arreglarlo ahora, es app-wide.**

## 1. El bug (preexistente, no lo introdujo el Bloque 5)

`frontend/src/components/Layout.jsx`:

| línea | elemento | clase |
|---|---|---|
| 257 | `<header>` | `relative z-30` |
| 327 | wrapper de `{children}` | **`relative z-10`** ← era el problema |

El header y ese wrapper son **hermanos** dentro del `<div className="flex-1 flex flex-col">`.
Un `z-index` distinto de `auto` **crea un contexto de apilamiento**: a partir de ahí, los
`z-index` de los hijos se resuelven CONTRA EL WRAPPER, no contra el header. Resultado: ningún
overlay de ninguna pantalla podía pintar sobre la barra superior, aunque su `z-index` fuera 50,
60 o 70.

Alcance medido sobre el código (grep de `fixed inset-0` en `frontend/src`, 51 overlays):

| z-index del overlay | cantidad |
|---|---|
| `z-50` | 42 |
| `z-[60]` | 5 (`EscanerQR`, `ModalAgregarSinReserva`, `ModalPublicarWod`, `SupervisionClases`, `GestionClases`) |
| `z-[70]` | 2 (`SupervisionClases`) |
| `z-40` (backdrops) | 2 |

Todos quedaban por debajo del header (`z-30`).

### Cómo se veía

1. **El fondo del modal no atenuaba la barra superior** (escritorio y teléfono): el header
   quedaba a pantalla completa, "por encima" del negro al 60 % del overlay.
2. A **375×568** el modal arranca en `top: 28` y el header termina en `y = 65`: los primeros
   **37 px** de la tarjeta quedaban detrás de la barra.
3. Con el **drawer móvil abierto**, el backdrop (`z-40`) tapaba los modales de la página: un
   toque fuera de la tarjeta cerraba el menú y dejaba el modal abierto abajo.

## 2. El arreglo

`Layout.jsx:327-336` — el wrapper pasa a ser `<div className="relative">{children}</div>`
(el comentario en el código explica por qué **no** puede volver a llevar z-index).

Por qué **quitar** el z-index y no subir el wrapper a `z-40`:

| opción | modales sobre el header | contenido normal vs. backdrop del drawer (`z-40`) |
|---|---|---|
| wrapper `z-40` | sí | **mal**: el contenido subiría por encima del backdrop → el negro del menú móvil dejaría de atenuar la página |
| wrapper sin z-index (**aplicado**) | sí | bien: el contenido queda en el nivel `auto` (`< z-30`) y **sólo los hijos con z positivo** suben |

Con el wrapper sin z-index, el orden de pintado queda: siluetas decorativas (`z-0`, van antes en
el DOM) → contenido normal (`auto`) → header (`z-30`) → backdrop del drawer (`z-40`) → modales /
drawer (`z-50`). Un empate en `z-50` (drawer vs modal) lo resuelve el orden del DOM: la columna
de contenido va DESPUÉS del `aside`, así que el modal gana — que es lo correcto (un modal se
queda con la pantalla).

## 3. Medición antes/después (misma pantalla, mismo harness)

`frontend/scripts/capturas-bloque2.mjs` → `MEDIR_FICHA` (`:352-393`) ahora mide
`capa_tapa_header` **en el DOM**, no en el pixel: toma el punto medio del header y comprueba que
`document.elementFromPoint()` devuelva algo que NO sea el header.

```
cd frontend
$env:PANTALLA='perfil-alumnos'; node scripts/capturas-bloque2.mjs
```

| toma | viewport | header | `capa_tapa_header` ANTES | DESPUÉS |
|---|---|---|---|---|
| 02-movil-ficha-con-rms | 390×844 | 0 → 65 | **false** | **true** |
| 03-movil-375x568-ficha-con-rms | 375×568 | 0 → 65 | **false** | **true** |
| 04-escritorio-ficha-con-rms | 1280×900 | 0 → 61 (x 256→1280) | **false** | **true** |
| 05-movil-ficha-sin-rms | 390×844 | 0 → 65 | **false** | **true** |

Salidas completas: `%TEMP%\bloque5\run2-categoria.txt` (antes) y `%TEMP%\bloque5\run3-zindex.txt`
(después). En las mismas corridas, `card`, `cerrar`, `cerrar_clickeable` y `rms_en_la_lista` dan
**clavados iguales**: el arreglo no movió nada de la ficha, sólo el orden de pintado.

## 4. Lo que NO se revirtió (a propósito)

- **El portal del dashboard admin móvil** (`InicioMobileAdmin.jsx` → `createPortal` a `<body>`,
  `.ub-admin.ub-capa { z-index: 50 }`): ya está probado en prod y es lo que permite anclar la
  pantalla justo debajo del header (`--ub-capa-top`). Ahora convive con el arreglo.
- **Las siluetas decorativas** (`fixed z-0`) siguen por debajo del contenido: el wrapper es
  `relative` y viene después en el DOM, así que gana el desempate dentro del mismo nivel.

## 5. Guardas (para que no vuelva)

`backend/tests/test_admin_movil_overlays.py` (aislado, sin red ni base):

- `test_a1`: el header sigue en `relative z-30`, el wrapper **no** lleva
  `className="relative z-10"` (falla con el mensaje del bug) y el orden header → wrapper se
  mantiene.
- `test_a2`: los overlays de 5 pantallas (`AlumnoFichaCoach`, `ModalAgregarSinReserva`,
  `EscanerQR`, `GestionClases`, `SupervisionClases`) tienen `z > 30` en la misma línea del
  `fixed inset-0`: es la garantía que queda sin el contexto de apilado.

```
cd backend && py -3.12 -m pytest tests/test_admin_movil_overlays.py -q --noconftest   # 8 passed
```

## 6. Regresión verificada

| chequeo | resultado |
|---|---|
| `test_admin_movil_overlays` (8) + `test_rm_categoria_contrato` (5) | **13 passed** |
| Pantalla `menu` del harness (Bloque 8, 7 capturas, drawer cerrado/abierto en 4 anchos) | **7/7 · 0 errores de consola · RESULTADO: OK** |
| `test:menu`, `test:coach-subtabs`, `test:alumnos` | TODO OK |
| `oxlint src scripts` | 0 errores (28 warnings preexistentes) |

Tras el arreglo, las mediciones del menú móvil (`mockup/_audit/bloque8-menu-movil/`) siguen
idénticas a las del Bloque 8: `sidebar.right <= 0` con el drawer cerrado y el foco entrando al
drawer (`focoEntraAlSidebar: true`) sólo con el drawer abierto.
