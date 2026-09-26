# BLINDAJE DEL CORREO EN PRODUCCIÓN (incidente 2026-09-26)

## Qué pasó
En PROD **el 100% de los correos salientes fallaba** (107 filas `fallido` en
`notificaciones_enviadas`, 0 enviados) y el QR del box devolvía 400. Dos causas raíz
independientes, **ambas en variables del dashboard de Render**:

| Variable | Problema | Efecto |
|---|---|---|
| `GMAIL_SMTP_USER` | tenía un espacio/salto de línea pegado | `email_service._enviar` armaba `msg["From"]` con el valor **crudo** ⇒ `Header values may not contain linefeed or carriage return characters` **antes** de conectar con Gmail ⇒ fallaban TODOS los correos |
| `FRONTEND_URL` | no empezaba con `http(s)://` | los ~25 links de correo y el endpoint del QR quedaban inválidos (QR → `400 "front debe ser una URL http(s) válida"`) |

Resend no participa: el proveedor es **Gmail SMTP directo** (`smtp.gmail.com:465`);
`RESEND_API_KEY` ya no se usa.

## Qué se blindó en el código (5 commits)
| Bloque | Cambio |
|---|---|
| **B.1** | `_enviar` sanea el `From` (`_limpiar_header(...)` + `.strip()`) y las credenciales del login SMTP. Si quedan vacías ⇒ error claro *"Configuración SMTP incompleta…"* en vez del error de header. |
| **B.2** | Nuevo **`app/core/urls.py`**: `url_frontend()` / `url_backend()` sanear (sin caracteres de control ni espacios, sin `/` final) y validan. **Los 25 puntos que armaban links** (10 servicios + 8 rutas + CORS + QR) ya no leen la env var cruda. |
| **B.3** | **`GET /health`** publica `config_ok` + `config_problemas`. En `ENVIRONMENT=production` exige URLs `https://` absolutas (rechaza localhost) y credenciales SMTP no vacías/sin espacios. **No aborta el arranque** (se loguea `[config] Problemas…` al iniciar). |
| **B.4** | Los correos sin alumno (`reset_password`, `bienvenida_activacion`) se registran **con `tenant_id`**, así que ya aparecen en `/admin/notificaciones` (antes: `tenant_id NULL` ⇒ invisibles). |
| **B.5** | `backend/tests/test_email_config_prod.py` (8 tests): falla si algún módulo usa `settings.FRONTEND_URL`/`BACKEND_PUBLIC_URL` crudas, si el `From` no se sanea o si el guard no detecta localhost/sin-esquema/espacios en producción. |

## Cómo verificar (día 1)
```powershell
# 1) Estado de la configuración (una línea, sin credenciales)
Invoke-RestMethod https://box-crossfit.onrender.com/health
#    → {"environment":"production","config_ok":true,"config_problemas":[]}

# 2) QR del box (200 = FRONTEND_URL válida)
#    public_id: 5e924e79-3956-480d-aae9-b793836e9bce
Invoke-WebRequest 'https://box-crossfit.onrender.com/api/v1/tenants/5e924e79-3956-480d-aae9-b793836e9bce/qr.svg' -UseBasicParsing

# 3) Correo real (llega a la casilla del admin y queda 'enviado' en la BD)
Invoke-WebRequest 'https://box-crossfit.onrender.com/api/v1/auth/reset-password-request' -Method POST `
  -ContentType 'application/json' -Body '{"correo":"jmirandai1985@gmail.com"}' -UseBasicParsing
```
En la BD: `SELECT estado, tenant_id, destinatario_correo FROM notificaciones_enviadas ORDER BY id DESC LIMIT 5;`

## Estado verificado el 2026-09-26 (post-deploy)
- `GET /health` → `config_ok=false` con **un solo** problema: `GMAIL_SMTP_USER con espacios/saltos al borde`
  (⇒ `FRONTEND_URL` y `BACKEND_PUBLIC_URL` **ya quedaron bien**).
- QR del box → **200** (antes 400).
- Reset real al admin de PROD → fila **129** `reset_password`, `tenant_id=1`, **`enviado`** (antes 105 fallidos),
  y el correo **llegó** con el link correcto:
  `https://box-crossfit.onrender.com/reset-password?token=…` (los correos previos traían `http://localhost:5173/…`).

## Acción pendiente (sólo cosmética, el correo YA funciona)
En Render → servicio backend → Environment: borrar y volver a pegar
`GMAIL_SMTP_USER = urban.training.box.2026@gmail.com` **sin espacios ni saltos**.
Mientras siga con espacios, el blindaje B.1 lo sanea y los correos salen igual; el aviso
queda visible en `/health.config_problemas` para no perderlo de vista.

## Tests
```powershell
docker exec box-crossfit-backend-1 python -m pytest tests/test_email_config_prod.py -q   # 8 passed
docker exec box-crossfit-backend-1 python -m pytest tests/test_email_header_saneo.py -q  # 48 passed
```
