# Notificaciones del panel (la campana) — quién avisa a quién

Documento de referencia de la **campana del panel** (`frontend/src/components/CampanaNotificaciones.jsx`)
y de su tabla: `notificaciones` (la que lee `GET /api/v1/notificaciones`).

Existe porque la campana del **admin nunca se encendía** mientras la del alumno sí: se
auditaron todos los flujos de la app y el resultado (bug + arreglo + lo que queda) queda
por escrito acá. Escrito en la tanda de notificaciones (B6).

> Regla que resume el bug: **un aviso sólo existe si alguien escribe la fila**.
> Que el usuario tenga la campana montada no basta.

---

## 1. Modelo y reglas

| Pieza | Dónde | Qué hace |
|---|---|---|
| Tabla | `notificaciones` | `alumno_id` = **id de usuario del DESTINATARIO** (alumno, coach o admin). **No tiene `tenant_id`**: el box se respeta eligiendo destinatarios. |
| Helper | `app/services/notificaciones_panel.py` | `notificar_usuario` / `notificar_alumno` / `notificar_admins_del_tenant`. Un solo lugar para leer/escribir el aviso. |
| API | `app/api/v1/notificaciones.py` | `GET /api/v1/notificaciones` (lista del usuario del JWT, `?solo_no_leidas=true`), `PUT /{id}/leer`, `PUT /leer-todas`. **No** acepta `alumno_id`: lo saca del token. |
| UI | `CampanaNotificaciones.jsx` (montada en `Layout.jsx` para alumno, coach y admin) | Contador de no leídas + panel. `ETIQUETAS_TIPO`, `DESTINOS_TIPO` y `ROLES_POR_TIPO` traducen `tipo` → texto, pantalla y rol. |

Dos reglas del helper, y una consecuencia que hay que conocer:

1. **BEST-EFFORT**: si el INSERT falla, se loguea un `warning` y el flujo de negocio sigue
   (una compra no puede caerse porque no se pudo escribir un aviso).
2. **`commit`**: con `commit=False` el aviso viaja en la transacción del llamador
   (`flush`); con `commit=True` (por defecto) el helper cierra la suya.
3. ⚠️ Consecuencia de (1): **un `tipo` o un destinatario mal escrito no rompe nada: pierde el
   aviso en silencio.** Por eso `tipo` es `String(20)` y hay test de longitud
   (`tests/test_notificaciones_panel.py::test_los_tipos_entran_en_la_columna`).

No confundir con `notificaciones_enviadas`: esa es el **log de correos** de la pantalla
`/admin/notificaciones` (`api/v1/notificaciones_enviadas.py`), otro canal y otra tabla.

---

## 2. Matriz: evento → aviso → destinatario → tipo → pantalla

| Evento | Quién escribe el aviso | Destinatario | `tipo` | Destino en la UI |
|---|---|---|---|---|
| Pedido nuevo en el Bazar | `api/v1/pedidos.py:180` | admins **activos** del box | `pedido_nuevo` | `/admin/pedidos` |
| Pedido validado / entregado | `api/v1/pedidos.py:439` | alumno dueño | `pedido_validado` / `pedido_entregado` | `/alumno/mis-pedidos` |
| Solicitud de plan con voucher | `api/v1/solicitudes_planes.py:189` (`POST /solicitudes/solicitar`) | admins **activos** del box | `plan_solicitado` | `/admin/dashboard` |
| Plan aprobado / rechazado | `api/v1/solicitudes_planes.py:378` / `:552` | alumno dueño | `aprobado` / `rechazado` | `/alumno/solicitar-plan` |
| Alta de alumno (autoservicio) | `api/v1/alumnos.py:249` (`POST /alumnos/registro/alumno-nuevo`) | admins **activos** del box | `alumno_nuevo` | `/admin/alumnos-pendientes` |
| Cobertura de emergencia (un coach cubre una clase ajena) | `core/dependencies.py:252` (`_notificar_emergencia`) | admins **activos** del box | `emergencia` | `/admin/supervision-clases` |
| Clase asignada / reasignada / liberada | `api/v1/supervision.py:775,782,844` | coach | `clase_asignada` / `clase_reasignada` / `clase_liberada` | `/coach/gestion-clases` |

`plan_solicitado`, `alumno_nuevo` y `emergencia` (los tres avisos **al admin**) son los que
arregló esta tanda, junto con el refresco del contador (sección 3).

---

## 3. El bug: por qué la campana del admin no encendía

Dos causas independientes, las dos necesarias para el síntoma "sólo la campana del alumno
se enciende":

**(a) Nadie escribía un aviso dirigido al admin en los caminos reales.** El helper
`notificar_admins_del_tenant` ya existía y sólo lo usaban el Bazar y la emergencia, y el
Bazar no se había ejercitado en TEST. En la base: 5 filas en `notificaciones`, **todas**
con destinatario alumno; ninguna fila de ningún flujo de admin. Los dos flujos que sí
importan para el admin —una **solicitud de plan con voucher** y un **alta de alumno**— no
avisaban a nadie en el panel (el alta sólo mandaba correo, que con `EMAIL_MODO=noop` en
TEST no llega a ningún lado).

**(b) El contador se consultaba UNA sola vez, al montar.** Aunque la fila existiera, la
campana no la veía hasta navegar a otra pantalla o recargar: no había polling ni refresco
al volver el foco.

---

## 4. El arreglo (esta tanda)

**Backend** (`feat(notificaciones)`) — los tres avisos al admin, todos por el helper
(best-effort, mismos filtros):

* `solicitudes_planes.py` — al crear la solicitud: `plan_solicitado` con el nombre del
  alumno, el plan y el `#id` de la solicitud (lo que el admin necesita para ubicar el
  voucher en `GET /solicitudes/pendientes`, que es lo único que sigue viviendo sólo en el
  Dashboard).
* `alumnos.py` — al crear el alumno: `alumno_nuevo` con nombre y correo. El correo al admin
  se mantiene; el aviso in-app es el que **no depende** del SMTP.
* `core/dependencies.py` — la emergencia deja de armar la fila a mano y usa
  `notificar_admins_del_tenant` (mismo destinatario para el aviso y para el correo, y ahora
  también **`estado='activo'`**: un admin dado de baja seguía recibiendo la alerta).

**Frontend** (`feat(campana)`):

* **Refresco del contador**: cada **45 s** (igual que la grilla de Supervisión) y al volver
  el foco a la ventana, **pausado mientras el panel está abierto** (el panel se refresca al
  abrirlo, así que el timer no pisa la lista que el usuario está leyendo).
* **Etiquetas y destinos nuevos** en `CampanaNotificaciones.jsx`: `plan_solicitado`,
  `alumno_nuevo` y `emergencia` (antes ni tenían etiqueta), y `aprobado` / `rechazado`
  ganaron destino (`/alumno/solicitar-plan`): se veían en la campana pero la fila **no
  navegaba**.

---

## 5. Cómo verificar

**Manual (TEST, con el stack levantado):**

```sql
-- ¿los flujos escriben para el admin? (tenant 1 y el resto de los boxes)
SELECT n.id, n.alumno_id, n.tipo, n.mensaje, n.leida, n.created_at
FROM notificaciones n ORDER BY n.id DESC LIMIT 20;

-- admins ACTIVOS que deberían recibir el aviso
SELECT id, nombre, correo FROM usuarios
WHERE tenant_id = 1 AND rol::text = 'administrador' AND estado = 'activo';
```

1. Con un alumno demo: comprar en el Bazar y subir un voucher de plan
   (`POST /api/v1/solicitudes/solicitar`).
2. Con el token de un admin: `GET /api/v1/notificaciones` debe traer las filas
   `pedido_nuevo` y `plan_solicitado` (una por admin activo, no una por box).
3. En el panel del admin: la campana debe encender **en ≤ 45 s** (o al volver a la
   ventana), sin recargar.

**Tests:**

```bash
# Aislados (sin API ni BD; es la validación que corre local):
cd backend && py -3.12 -m pytest tests/test_notificaciones_panel.py -q --noconftest

# Integración (necesita la API de TEST en localhost:8000):
py -3.12 -m pytest tests/test_pedidos_notificaciones.py -q
py -3.12 -m pytest tests/test_notificaciones_admin_flujos.py -q
```

Los dos de integración crean datos REALES y los borran al terminar. Los aislados cubren,
sin BD, el helper y el **contrato** de los flujos (que llamen al helper y que los tipos
entren en la columna): son los que evitan que el bug vuelva.


---

## 6. Pendientes conocidos (fuera de esta tanda)

Eventos que hoy **no** dejan aviso en la campana (sólo correo, o nada). Se listan para que
no vuelvan a aparecer como "la campana no funciona":

| Evento | Canal actual | Qué falta |
|---|---|---|
| Stock bajo tras una compra | correo al admin (`send_alerta_stock_bajo`, `api/v1/pedidos.py:204-223`) | aviso in-app (mismo evento que ya avisa por correo) |
| Renovación de plan al activarse | correo (`send_confirmacion_renovacion_plan`, `api/v1/alumnos.py:416-418`) | aviso in-app al alumno |
| Reenvío manual desde `/admin/notificaciones` | `notificaciones_enviadas.py` (log de correos) | — (es otro canal, por diseño) |
| Cualquier evento de un box **sin admins activos** | — | el helper devuelve 0 y no avisa a nadie: revisar al crear un box |

Y dos cosas de infraestructura que afectan a los avisos:

* **Aviso silencioso**: como el helper es best-effort, un fallo de la BD (por ejemplo una
  conexión stale del pooler de Neon, `SSL SYSCALL error: EOF detected`) deja sólo un
  `warning` en `app.log` y el aviso no existe. Si la campana "pierde" avisos sueltos,
  mirar primero `app/logs/app.log` y la configuración del pool (`app/db/database.py`).
* **`crear_usuarios_demo.py --borrar`** borra las notificaciones de los usuarios demo
  (`backend/scripts/crear_usuarios_demo.py`): si la campana queda vacía después de correrlo,
  es eso y no la app.

