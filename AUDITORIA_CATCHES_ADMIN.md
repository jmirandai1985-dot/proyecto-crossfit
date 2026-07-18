# AUDITORÍA DE CATCHES SILENCIOSOS — Panel Admin

## Dashboard.jsx (src/pages/admin/Dashboard.jsx)

### Línea 24: `catch { setStats(null); }`
- **Ubicación:** `cargarStats()`
- **Tipo:** Silencioso total (sin log, sin mensaje al usuario)
- **Impacto:** Si falla GET /reportes/, el Dashboard carga sin stats (tarjetas no se muestran). El usuario no sabe por qué.
- **Veredicto:** 🟡 **Aceptable** — Es un feature secundario (stats son decorativas). Pero idealmente debería loguear el error en consola.

### Línea 35-38: `catch { setSolicitudes([]); setStats(null); }`
- **Ubicación:** `cargarSolicitudes()`
- **Tipo:** Silencioso total
- **Impacto:** Si falla la carga de solicitudes O reportes, el Dashboard se queda vacío sin feedback. Esto OCULTA errores reales como el endpoint /reportes/ inexistente (que resultó sí existir).
- **Veredicto:** 🔴 **Peligroso** — Oculta errores de red, 500, 404. Debería al menos `console.error`.

### Línea 76-79: `catch (err) { setMsg('❌ Error al descargar voucher'); }`
- **Ubicación:** `handleDescargarVoucher()`
- **Tipo:** Con mensaje al usuario
- **Veredicto:** ✅ **Correcto** — Muestra error al usuario. Aunque el catch nunca se ejecuta porque usa `window.location.href` que no lanza excepción.

## Resumen
| Archivo | Línea | Tipo | Gravedad | 
|---------|-------|------|----------|
| Dashboard.jsx | 24 | catch {} vacío | 🟡 Media |
| Dashboard.jsx | 35 | catch {} vacío | 🔴 Alta |
| Dashboard.jsx | 76 | catch con msg | ✅ Correcto |

**Total catches silenciosos peligrosos: 1** (línea 35 — oculta errores de red/server)
**Total catches aceptables: 1** (línea 24 — stats son decorativas)
**Total correctos: 1** (línea 76 — muestra error al usuario)