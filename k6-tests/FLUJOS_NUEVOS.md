# Flujos nuevos G1–G8 (k6)

Ocho escenarios que cubren caminos que el arnés A–D/F1/F2 **no** tocaba, elegidos en
la auditoría de `REPORTE_SESION_MANTENIMIENTO.md` (§6). Todos reutilizan el
`load_config.json` y `tokens.json` existentes: no hay un segundo arnés.

| Archivo | Flujo | Endpoints ejercitados | Auth |
|---|---|---|---|
| `scenario_g1_checkin_qr.js` | Check-in escaneando el QR fijo del box | `POST /api/v1/asistencia/qr/{tenant_public_id}/check-in` | alumno (`tokens.json`) |
| `scenario_g2_wods_masivo.js` | Coach carga la semana de WODs | `POST /api/v1/wods/batch-create` + `POST /api/v1/wods/` | admin |
| `scenario_g3_bazar_entrega.js` | Entrega por código en el mesón y rechazo con devolución de stock | `POST /api/v1/pedidos/entregar`, `POST /api/v1/pedidos/{id}/rechazar` | admin/coach |
| `scenario_g4_referidos_embudo.js` | Embudo de referidos lado alumno | `GET /referidos/mi-codigo`, `GET /referidos/mi-invitacion`, `POST /referidos/invitaciones`, `POST /referidos/validar-codigo` | alumno |
| `scenario_g5_panel_admin.js` | Lecturas del panel/BI (sólo GET) | `GET /kpis/{diario,mensual,cohortes,churn,financiero}`, `/admin/pendientes/resumen`, `/pedidos?estado=pendiente`, `/historial-rm?alumno_id=` | admin |
| `scenario_g6_bazar_voucher_admin.js` | Admin aprueba el voucher (carrera: N VUs, 1 gana) y rechaza otro con devolución de stock | `PUT /api/v1/pedidos/{id}/estado?nuevo_estado=validado`, `POST /api/v1/pedidos/{id}/rechazar` | admin |
| `scenario_g7_coach_asistencia.js` | Coach abre su clase de hoy y confirma la asistencia de toda la clase | `GET /api/v1/asistencia/clases-hoy`, `GET .../clases/{id}/alumnos`, `POST .../clases/{id}/confirmar` | coach |
| `scenario_g8_activar_alumno.js` | Cola de activación: aprobar en carrera, activar dos veces y rechazar | `PUT /api/v1/solicitudes/{id}/aprobar`, `PUT /api/v1/alumnos/{id}/{activar,rechazar}` | admin |
| `scenario_g9_pago_mercadopago.js` | Checkout recurrente en carrera + webhook firmado reenviado (idempotencia) | `POST /api/v1/pagos/suscripcion`, `POST /api/v1/pagos/webhook/mercadopago` | alumno / nadie (firma HMAC) |
| `scenario_g10_alumno_nuevo_e2e.js` | Alta pública end-to-end: correo de credenciales + plan "Prueba" de 7 días | `POST /api/v1/alumnos/registro/alumno-nuevo` | público |
| `scenario_g11_referidos_conversion.js` | Referidos con conversión real: % del invitado, créditos FIFO del invitador y escalera de tramos | `POST /registro/alumno-nuevo`, `POST /referidos/validar-codigo`, `POST /solicitudes/solicitar`, `PUT /solicitudes/{id}/aprobar`, `GET /referidos/mi-progreso` | público + alumno + admin |
| `scenario_g12_reactivacion.js` | Reactivación: candidato del padrón → oferta → alta → promoción aplicada → "recuperado" | `POST /api/v1/alumnos/registro/alumno-nuevo` (verificación en BD) | público |
| `scenario_g13_mis_wods.js` | Ciclo de WODs con concurrencia: coach crea/publica/asigna + N alumnos leen pendientes y registran resultado | `POST/PUT /wods/`, `POST /wods/clases/{id}/asignar-wod/{wod}`, `GET /alumnos/me/wods-pendientes`, `POST /alumnos/me/wods/{wod}/resultado` | coach + alumno |
| `scenario_g14_activacion_e2e.js` | Activación end-to-end: activar → correo → login temporal (sin cookie) → cambio de clave → login real (con cookie) → solicitud de plan | `PUT /alumnos/{id}/activar`, `POST /auth/login`, `POST /auth/cambiar-password-inicial`, `POST /solicitudes/solicitar` | admin + alumno |


`lib/config_flujos.js` es el único módulo compartido nuevo: lee el **mismo**
`load_config.json` y expone `BASE_URL`, `ADMIN_TOKEN`, `COACH_TOKEN`,
`headersAdmin()`, `headersCoach()`, `headersAlumno()`, `fechaConOffset()` y los
contadores de VUs `N_G1..N_G8`.
No modifica `lib/config.js`, así que los escenarios viejos siguen igual.

## 1. Requisitos previos (los mismos de siempre)

```
k6-tests/
├── load_config.json   ← base_url, tenant_id, admin_token  (+ las claves del §2)
└── tokens.json        ← [{"alumno_id": 1, "token": "..."}, ...]  (hasta 500 filas)
```

⚠️ **Estado actual (2026-10-26):** `load_config.json` y `tokens.json` **los genera
`_seed_load_test.py`** contra el tenant de TEST (`maipu`). Ninguno de los dos se
versiona: `tokens.json` lleva JWT vivos y `load_config.json` ids reales de la BD.

```powershell
python k6-tests\_seed_load_test.py --alumnos 20   # ~90 s, idempotente
k6 run k6-tests\scenario_g1_checkin_qr.js
python k6-tests\_verificar_escenarios.py g1       # ¿quedó bien en la BD?
```

## 2. Claves nuevas en `load_config.json`

Se agregan al JSON existente; `config_flujos.js` las lee con default `null`, así
que no rompen nada si faltan (el escenario que las necesita falla con un mensaje
explícito en vez de mandar `undefined` a la API):

```json
{
  "base_url": "http://localhost:8000",
  "tenant_id": 1,
  "admin_token": "eyJ...",
  "coach_token": "eyJ...",

  "tenant_public_id": "3f2b8c1e-9a44-4d7e-8b1f-1c2d3e4f5a6b",
  "pedido_codigo": "UB-7K3M",
  "pedido_pendiente_id": 4821,
  "alumno_para_wods": 137,

  "pedido_voucher_aprobar_id": 4822,
  "pedido_voucher_rechazar_id": 4823,

  "clase_g7_id": 9001,
  "reservas_g7": [51001, 51002, 51003],

  "solicitud_carrera_id": 284,
  "alumno_activar_id": 787,
  "alumno_rechazo_activacion": 786,
  "coach_id": 765,

  "n_g1": 20,
  "n_g2": 10,
  "n_g3": 8,
  "n_g4": 5,
  "n_g5": 6,
  "n_g6": 8,
  "n_g7": 5,
  "n_g8": 8
}
```

`n_g5` es 6 y no 30 a propósito: el pool del backend es `pool_size=10 +
max_overflow=5` con `pool_timeout=10`, así que 30 VUs pidiendo `/kpis/churn`
(que tarda ~6-9 s) agotan el pool y devuelven 500 por *checkout timeout*, no por
un bug del panel. Con 6 VUs el panel se sostiene sin 5xx (medido).

| Clave | Para qué | De dónde sale |
|---|---|---|
| `tenant_public_id` | QR fijo del box en G1 | `SELECT public_id FROM tenants WHERE id = <tenant_id>;` (UUID v4, no el `id` ni el `subdomain`) |
| `pedido_codigo` | código de retiro que se "escanea" en el mesón (G3) | pedido en `validado`: `SELECT codigo_retiro FROM pedidos WHERE tenant_id=<tenant_id> AND estado='validado' AND codigo_retiro IS NOT NULL LIMIT 1;` — formato obligatorio `UB-` + 4 símbolos del alfabeto sin ambigüedades (`CHECK ck_pedidos_codigo_retiro_formato`, migración 044) |
| `pedido_pendiente_id` | pedido a rechazar, para verificar la devolución de stock (G3) | `SELECT id FROM pedidos WHERE tenant_id=<tenant_id> AND estado='pendiente' ORDER BY id DESC LIMIT 1;` |
| `alumno_para_wods` | alumno con historial de RM para la lectura de G5 | `SELECT alumno_id FROM historial_rm WHERE tenant_id=<tenant_id> GROUP BY alumno_id ORDER BY count(*) DESC LIMIT 1;` |
| `pedido_voucher_aprobar_id` | pedido `pendiente` que G6 valida (queda `validado` + código) | `SELECT id FROM pedidos WHERE tenant_id=<tenant_id> AND estado='pendiente' ORDER BY id LIMIT 1;` |
| `pedido_voucher_rechazar_id` | pedido `pendiente` que G6 rechaza (devuelve stock) | el siguiente `pendiente` — **distinto** del anterior |
| `clase_g7_id` | clase de HOY que el coach confirma | `SELECT id FROM clases WHERE tenant_id=<tenant_id> AND coach_id=<coach_id> AND fecha=CURRENT_DATE;` |
| `reservas_g7` | reservas vigentes de esa clase | `SELECT array_agg(id) FROM reservas WHERE clase_id=<clase_g7_id> AND estado<>'cancelada';` |
| `solicitud_carrera_id` | solicitud `pending` que G8 aprueba con N VUs a la vez. Tiene que ser de un alumno `pendiente_activacion` (las de los alumnos activos las aprueban los escenarios C/E) | `SELECT s.id FROM solicitudes_planes s JOIN usuarios u ON u.id = s.alumno_id WHERE s.tenant_id=<tenant_id> AND s.estado='pending' AND u.estado='pendiente_activacion' ORDER BY s.id LIMIT 1;` |
| `alumno_activar_id` | alumno `pendiente_activacion` que G8 activa | `SELECT id FROM usuarios WHERE tenant_id=<tenant_id> AND estado='pendiente_activacion' ORDER BY id LIMIT 1;` |
| `alumno_rechazo_activacion` | alumno que G8 rechaza (queda `rechazado`/`activo=false`) | otro `pendiente_activacion` |
| `coach_token` / `coach_id` | JWT y usuario del coach de G7 | lo emite el seed (`coach_token`, `coach_id`) |
| `n_gN` | VUs por escenario (defaults conservadores) | — |

Ninguna clave es secreta salvo `admin_token`, que ya estaba.

## 3. Qué hay que sembrar en cada flujo

### G1 — Check-in por QR (`scenario_g1_checkin_qr.js`)

**Seed:** sólo alumnos con token válido en `tokens.json` (mismo seed del arnés
existente) + el `tenant_public_id`. Nada más: el escenario tolera los 4 estados.

El endpoint responde **siempre 200** con un estado de negocio, así que un
`http_req_failed` en verde no dice nada; el escenario cuenta cada estado:

| Contador | Significado |
|---|---|
| `qr_marcado` | reserva de hoy encontrada y asistencia marcada (camino feliz) |
| `qr_ya_marcado` | el alumno ya había marcado (idempotencia) |
| `qr_sin_reserva` | escaneó sin reserva para hoy: **esperado** si el alumno no reservó |
| `qr_ambiguo` | más de una reserva candidata: hay que mirar los datos |
| `qr_429` | rate limit `30/minute` por IP (ver abajo) |
| `qr_otros` | 0 (sin conexión), 403 (el QR es de otro box) o 404 (`public_id` mal sembrado): **umbral `count==0`** |
| `qr_5xx` | **umbral: `count==0`** |

⚠️ Con `n_g1: 20` y todos los VUs en el mismo minuto, ya se roza el límite de
30/min por IP; con 40+ aparecen `429` legítimos. Para medir la API (y no el
limitador) hay que correr en ≤25 VUs o repartir con `startTime`/`stages`.

### G2 — WOD masivo (`scenario_g2_wods_masivo.js`)

Dos escenarios en el mismo script:

- `semana` → `POST /wods/batch-create` con **5 WODs en una transacción atómica**
  (body `{"wods": [WodCreate, ...]}`, confirmado en `schemas/wod.py`:
  `WodBatchCreateRequest.wods: List[WodCreate]`).
- `simple` → `POST /wods/` con un WOD suelto, para comparar latencia.

**Seed:** ninguno. Se usa el `ADMIN_TOKEN` porque `get_current_coach` deja pasar
al admin sin `disciplina_id` (un coach real necesitaría `?disciplina_id=`).
Cada VU escribe en un **bloque de fechas propio** (`400 + VU*10`) para no chocar
entre VUs ni con datos reales, y todos los WODs nacen en `estado: 'draft'`.

**Umbrales:** `wods_5xx count==0`, `wods_otros count==0` y
`wods_batch_ms p(95)<6000` (línea base medida: 4,3-4,7 s con 10 VUs en TEST).
Si `batch-create` responde 400, casi siempre es una fecha repetida dentro del
mismo body (el endpoint valida duplicados), no un problema de carga.

### G3 — Bazar: entrega por código + rechazo (`scenario_g3_bazar_entrega.js`)

**Seed obligatorio:**

1. `pedido_codigo` → un pedido en `estado='validado'` con `codigo_retiro` no nulo.
   Al terminar la corrida ese pedido queda **entregado** (irreversible): el
   escenario es de un solo uso por pedido.
2. `pedido_pendiente_id` → un pedido en `estado='pendiente'` con stock disponible
   en su producto. Al terminar queda **rechazado** y el stock vuelve.

El seed **descuenta el stock de los pedidos que inserta** (`UPDATE productos SET
stock = stock - SUM(cantidad)`), igual que hace `POST /pedidos` al crear; si no,
el rechazo "devuelve" una unidad que nunca se descontó y el stock del producto
queda inflado en +1 por corrida. Con eso vale el invariante que revisa el
verificador:

```
stock + SUM(cantidad de pedidos 'pendiente'/'validado')
      == stock_inicial - SUM(cantidad de pedidos 'entregado')
```

Qué mide: `n_g3` VUs disparan **el mismo código** a la vez. Lo correcto es
1×200 y el resto 409 (`bazar_entregado_200`, `bazar_conflicto_409`). Dos `200`
en el mismo run = el bloqueo de la entrega no funciona. Además
`bazar_429` (límite `LIMIT_CODIGO_RETIRO`, 10/min) y `bazar_404` (código
inexistente en el box: si aparece con el seed correcto, hay fuga de tenant).
El rechazo corre con **1 VU** en `startTime: 5s` para no ensuciar la medición y
espera 200 / 400 (ya rechazado de una corrida previa).

### G4 — Embudo de referidos (`scenario_g4_referidos_embudo.js`)

**Seed:** alumnos con token (`tokens.json`) + **fila en `configuracion_referidos`**
para el tenant. Si falta esa fila (lo que pasa hoy en PROD, ver reporte §4) los
endpoints responden error de configuración y el flujo no mide nada.

Por iteración: `mi-codigo` → `mi-invitacion` → `invitaciones` → `validar-codigo`
con el **código propio** (debe dar 400 y no escribir nada: camino negativo sin
efectos secundarios).

Límites de negocio que se cuentan, no se consideran fallos: `ref_invitacion_429`
(5/día por alumno), `ref_invitacion_400` (mismo correo en 7 días / propio / ya
es usuario), `ref_invitacion_502` (falló el SMTP y la fila se borró).
`ref_sin_codigo` cuenta alumnos históricos sin backfill de código: es un
hallazgo de datos, no un 5xx.

⚠️ **Correr con `EMAIL_MODO=noop`** en el backend. `POST /referidos/invitaciones`
manda correo **sincrónico** y no tiene rate limit por IP: es exactamente el
detonante de los hallazgos F1/F2 del reporte (§1). Con SMTP real, cada `201`
abre una conexión nueva.

### G5 — Panel admin (`scenario_g5_panel_admin.js`)

**Seed:** `ADMIN_TOKEN` + opcional `alumno_para_wods` (si falta, se saltea la
lectura de `historial-rm`). Sólo GET: no escribe nada.

Mide los endpoints caros del panel (`cohortes`, `churn`, `financiero` se calculan
en vivo) con tags por endpoint. Son **líneas base del entorno** (Neon free + 1
worker de uvicorn, 6 VUs), no SLO: se fijan ~1,6-2× por encima de lo medido para
detectar regresiones (un N+1 nuevo, un índice que se cayó) sin romperse por el
jitter de Neon:

| Tag | p95 medido (2026-10-26) | Umbral |
|---|---|---|
| `admin_pendientes` | 1,78 s | `p(95)<4000` |
| `kpis_churn` | 6,80 s (8,95 s en otra corrida) | `p(95)<15000` |
| `kpis_cohortes` | 5,03 s (5,21 s en otra corrida) | `p(95)<8000` |
| `kpis_financiero` | 1,70 s | `p(95)<5000` |
| `pedidos_pendientes` | 1,52 s (3,13 s en otra corrida) | `p(95)<5000` |

El escenario lleva `noConnectionReuse: true`: un `sleep` de 5-13 s entre KPIs deja
que uvicorn cierre el keep-alive y k6 reporta status `0` / `EOF` como si fuera un
fallo de la API (falso negativo).

Ojo con la ruta: **`/admin/registros` no existe**. `registros` (alumnos en
`pendiente_activacion`) es un campo de `GET /admin/pendientes/resumen`, así que
es ese el endpoint que se mide (`admin.py` sólo expone `pendientes/resumen`,
`alumnos-prueba*`, `alumnos-nuevos`, `alumnos-convertidos` y el POST de invitación).

Estados: `panel_sin_datos_404` (sólo para los KPIs materializados: `daily_kpis` /
`monthly_kpis` sin fila = el job todavía no escribió ese día/mes, **no** es un
fallo del panel; en el resto de las rutas un 404 sí es fallo y cae en `panel_otros`),
`panel_429` (rate limit), y `panel_5xx` / `panel_otros` (sin conexión, 401/403,
4xx inesperado) que **deben ser 0**. `panel_otros` es el que evita el falso verde:
sin él, una API caída daba 0 5xx y todo "pasaba".

### G6 — Admin aprueba / rechaza un voucher (`scenario_g6_bazar_voucher_admin.js`)

Es el botón "Aprobar" del panel: el admin valida el comprobante de pago del pedido.
Dos caminos en un archivo:

| Camino | Endpoint | Estados posibles |
|---|---|---|
| Aprobar en carrera | `PUT /api/v1/pedidos/{id}/estado?nuevo_estado=validado` | 1×`200` (gana uno) + (N−1)×`400`; `503` sólo si no hay código de retiro libre |
| Rechazar | `POST /api/v1/pedidos/{id}/rechazar` `{"motivo": "..."}` | `200` (o `400` si ya no estaba `pendiente`) |

⚠️ **`nuevo_estado` es QUERY PARAM, no body** (`pedidos.py:431`: `def actualizar_estado_pedido(pedido_id: int, nuevo_estado: str, ...)`).
Mandarlo en el JSON da `422` (unprocessable). El front lo manda en `params`.

Qué mide: `n_g6` VUs validan **el mismo pedido** a la vez. El endpoint bloquea con
`with_for_update()` y las transiciones son monotónicas
(`pendiente → validado → entregado`), así que lo correcto es **1×200 y el resto
400** — el código de retiro se genera una sola vez. Dos `200` = se validó (y se
codificó) dos veces. Contadores: `g6_aprobado_200` (umbral `count<=1`),
`g6_transicion_400`, `g6_sin_codigo_503`, `g6_5xx`, `g6_otros`.

El rechazo corre con **1 VU** en `startTime: 5s` para no ensuciar la carrera; su
efecto (stock devuelto) lo verifica el §6.

**Seed:** dos pedidos `pendiente` distintos (`pedido_voucher_aprobar_id`,
`pedido_voucher_rechazar_id`) + el stock del producto descontado, como en G3.

### G7 — Pestaña Asistencia del coach (`scenario_g7_coach_asistencia.js`)

El flujo real del coach en el box: abre el día, abre su clase y aprieta
"Confirmar" (marca la clase entera de una vez).

```
GET  /api/v1/asistencia/clases-hoy             → panel del día
GET  /api/v1/asistencia/clases/{id}/alumnos    → reservas + asistió
POST /api/v1/asistencia/clases/{id}/confirmar  → {asistencias:[{reserva_id, asistio}]}
```

⚠️ **El coach NO registra PRs.** `POST /api/v1/historial-rm` responde **403** a un
coach sobre un alumno ajeno (`historial_rm.py:105-109`, decisión de negocio), así
que el "registro de PR del coach" no puede ser el flujo de G7. Su escritura real es
la asistencia.

Reglas del endpoint que explican los contadores:

- **Ventana:** sólo el mismo día calendario en Chile; otro día da `403` → `g7_sin_ventana_403`.
- **Alcance:** el coach sólo marca SUS clases (`_exigir_alcance_coach`) → `g7_clase_ajena_403`.
- **Idempotente:** repetir el mismo body deja `asistio`/`marcada_por` iguales y da `200`
  → los N VUs pueden apretar Confirmar a la vez (`g7_confirmado_200`).
- Escribe `reservas.asistio`, `asistencia_marcada_por`, `asistencia_marcada_at` y
  `asistencia_via='batch'`.

⚠️ **Por eso G7 usa una clase PROPIA (`clase_g7_id`) y no la del QR (G1).**
`confirmar` reescribe `asistencia_via='batch'`; si se reusara la clase de G1, el
verificador de G1 (`vía='qr_alumno'`) fallaría después de correr G7. El seed la
siembra como §3b.

`noConnectionReuse: true` aunque los `sleep` son de 1 s: el escenario mezcla GET y
POST sobre la misma conexión y un hueco del keep-alive se reportaría como status `0`.

### G8 — Cola de activación del admin (`scenario_g8_activar_alumno.js`)

Tres caminos que el admin hace desde la cola de registros:

| Exec | Endpoint | Qué se espera |
|---|---|---|
| `aprobarEnCarrera` | `PUT /api/v1/solicitudes/{id}/aprobar` | 1×`200` + (N−1)×`400` "ya fue procesada" |
| `activarAlumno` | `PUT /api/v1/alumnos/{id}/activar` | 1ª llamada `200`, 2ª `409` (guarda de estado) |
| `rechazarAlumno` | `PUT /api/v1/alumnos/{id}/rechazar` | `200` |

⚠️ **La ruta es `/api/v1/solicitudes/{id}/aprobar`, no `/solicitudes-planes/...`.** El
router del archivo `solicitudes_planes.py` se monta con prefijo `/api/v1/solicitudes`
(`main.py:310-311`); el nombre del módulo no es la URL. Es la misma que usan los
escenarios C y E.

**La carrera es el punto del escenario.** `aprobar` hace
`UPDATE solicitudes_planes SET estado='approved', aprobado_por=... WHERE id=:id AND estado='pending'`
y sólo sigue el que obtiene `rowcount=1` (`solicitudes_planes.py:346-364`). Si ese
filtro se cayera, dos admins aprobarían la misma solicitud → **dos
suscripciones**, doble notificación y el alumno con dos planes activos. Los
contadores (`g8_aprobado_200<=1`, `g8_ya_procesada_400`) lo detectan en el HTTP y
el verificador lo confirma en la BD (1 sola suscripción, 1 sola notificación).

`activar` sí tiene guarda (`alumnos.py:409`: `estado != 'pendiente_activacion'` →
`409`) y es el endpoint **más lento** de la cola: genera password provisional,
hashea y manda el correo en línea (por eso `sleep(1)` entre las dos llamadas).

⚠️ **Hallazgo abierto (no corregido en este pase): `PUT /alumnos/{id}/rechazar` no
tiene guarda de estado** (`alumnos.py:513-529`): hace `usuario.estado='rechazado'` y
`usuario.activo=False` sin mirar el estado previo, así que **un admin puede desactivar
a un alumno activo** (o a uno ya rechazado) con un solo clic. La auditoría sí se
escribe (`detalle={"estado": "rechazado"}`), pero el cambio no está protegido. G8 sólo
verifica el camino feliz (`200`, `estado='rechazado'`, `activo=False`) y deja el bug
documentado; arreglarlo es un cambio de backend aparte (mismo patrón que `activar`).

**Seed:** `solicitud_carrera_id` (solicitud `pending` de un tercer alumno
`pendiente_activacion` — no la de los alumnos activos que aprueban C/E),
`alumno_activar_id` y `alumno_rechazo_activacion` (`pendiente_activacion`, cada uno
con su solicitud `pending` para que la cola del panel se vea real).

## 4. Convención común: `*_otros` (anti falso verde)

Los ocho escenarios reservan **dos contadores obligatorios** con umbral
`count==0`, además de los contadores de negocio:

- `*_5xx` → errores de servidor.
- `*_otros` (`qr_otros`, `wods_otros`, `bazar_otros`, `ref_otros`, `panel_otros`,
  `g6_otros`, `g7_otros`, `g8_otros`) → cualquier cosa que el flujo **no**
  contempla: status `0` (sin conexión), 401/403 por token vencido, 404 de ruta
  rota o un 4xx/2xx inesperado. En G6/G7/G8 esto es clave: sus códigos "buenos"
  incluyen `400` (otro VU ya procesó) y `409`, así que un `401` o un `422` se
  perdería entre los 4xx esperados si no fuera por `*_otros`.

Sin `*_otros`, una corrida contra una API caída o con el `admin_token` vencido
terminaba en verde: los `check()` no hacen fallar el run por sí solos y los
`Counter` de 5xx quedaban en 0. Está verificado: con la API en un puerto muerto,
los 5 escenarios salen con **exit 99** y `*_otros > 0`.

## 5. Cómo correrlos

```powershell
cd C:\...\proyecto-crossfit\k6-tests

# Individual (usa los n_gN del load_config.json)
k6 run scenario_g5_panel_admin.js
k6 run scenario_g2_wods_masivo.js
k6 run scenario_g6_bazar_voucher_admin.js
k6 run scenario_g7_coach_asistencia.js     # necesita clase_g7_id (seed nuevo)
k6 run scenario_g8_activar_alumno.js       # necesita solicitud_carrera_id (seed nuevo)
```

Los VUs **no** se pasan por `-vus`/`-iterations`: esa bandera de CLI reemplaza
los `scenarios` completos de k6 ("cli level configuration overrode scenarios
configuration entirely") y los `exec` con nombre (`semana`, `simple`,
`entregarCodigo`, `rechazarPendiente`) **dejan de ejecutarse**. Para cambiar la
carga, se edita `n_gN` en `load_config.json`.

Criterio de lectura rápido:

- `exit 0` y `*_5xx == 0` → sin errores de servidor.
- `exit 99` → algún umbral cruzado (`panel_otros`, duración p95, etc.).
- Los contadores de negocio (`qr_*`, `bazar_*`, `ref_*`, `panel_*`) dicen **qué**
  camino tomó el flujo; un `429` alto no es un bug, es el rate limit haciendo su
  trabajo (bajar `n_gN` si se quiere medir la API).

## 6. Verificación de datos en la BD (post-corrida)

Los `check()` de k6 miran el **HTTP**; no ven si la transacción quedó a medias.
`_verificar_escenarios.py` lee la BD después de cada escenario y confirma el
estado de negocio (sólo TEST: aborta si `is_test_db_url()` es falso):

```powershell
python k6-tests\_verificar_escenarios.py g3       # un escenario
python k6-tests\_verificar_escenarios.py todos    # G1..G8 en serie
```

| Escenario | Qué verifica |
|---|---|
| G1 | la clase del QR es de hoy y tiene N reservas; las marcadas quedaron con `asistencia_via='qr_alumno'`, `asistencia_marcada_at` y `asistencia_marcada_por = alumno_id` |
| G2 | hay ≥ `5*N_G2 + N_G2` WODs `'K6 %'`, todos en `draft`, con `titulo == 'K6 '||fecha` y `calentamiento`/`wod_principal` cargados; el bloque de 5 fechas del VU 1 está completo (atomicidad) |
| G3 | el pedido del código quedó `entregado` con `entregado_por = admin`, el otro `rechazado`, y el invariante de stock (arriba) se cumple |
| G4 | 1 código de referido por alumno, activo y con formato; cada invitación ligada a `codigo_referido_id`; **0** filas nuevas en `referidos_aplicados` (validar el código propio no escribe) |
| G5 | nada: es sólo lectura, se valida con los counters/thresholds de k6 |
| G6 | el pedido aprobado quedó `validado` **con** `codigo_retiro`, el otro `rechazado`, el invariante de stock del §G3 se sigue cumpliendo (el rechazo devolvió la unidad), el producto sigue con 4 pedidos y se informa cuántos tienen código (> 2 = validación duplicada) |
| G7 | la clase G7 es de **hoy** (Chile) y del `coach_id` del token; sus N reservas quedaron `asistio=true`, `asistencia_via='batch'`, `asistencia_marcada_por=coach` y `marcada_at` seteado; y la clase del QR **no** tiene ninguna marca `'batch'` (G1 sigue siendo válido) |
| G8 | la solicitud quedó `approved` con `aprobado_por=admin` y **1 sola** suscripción nueva + **1 sola** notificación `'aprobado'` (doble proceso = 2); el alumno activado quedó `estado='activo'`, `activo=true`, `cambiar_password_al_login=true` y con 1 fila de auditoría; el rechazado quedó `estado='rechazado'`, `activo=false` |

Salida: `[ok]`/`[FALLO]` por chequeo + `RESULTADO: N ok · M fallos`; exit 1 si algo
falló (encadenable en un `.ps1`), 2 si la BD no es TEST.

## 7. Limpieza después de una corrida

G2 y G4 dejan filas propias, identificables por prefijo:

```sql
-- WODs creados por los escenarios (y sus vínculos a clases)
DELETE FROM wods WHERE titulo LIKE 'K6 %';
-- Invitaciones del embudo (correo único por corrida). OJO: la columna es
-- `correo_prospecto`, no `correo`.
DELETE FROM invitaciones WHERE correo_prospecto LIKE 'k6-g4-%@example.com';
```

G1 deja asistencias marcadas hoy para los alumnos de `tokens.json` (son datos
plausibles; si molestan, borrar por `fecha = CURRENT_DATE` + esos `alumno_id`).

G3 es de **un solo uso**: no crea pedidos, consume el `pedido_codigo` (queda
`entregado`) y rechaza el `pedido_pendiente_id`. Para repetirlo, volver a correr
`_seed_load_test.py` (regenera producto, pedidos y `load_config.json`; cuesta ~90 s).

G6 es de **un solo uso** por la misma razón: deja `pedido_voucher_aprobar_id` en
`validado` (con código) y `pedido_voucher_rechazar_id` en `rechazado`. Volver a
correrlo **sin resembrar** no falla (los umbrales son `count<=1`), pero ya no mide
la carrera: el segundo run ve `400`/`400`. Para medir de nuevo, reseed.

G7 **sí es repetible** sin reseed: `confirmar` es idempotente y reescribe los
mismos valores (misma clase, mismo coach, mismas reservas). Lo único que cambia es
`asistencia_marcada_at`. Deja asistencias marcadas hoy en `clase_g7_id`; si
molestan, `UPDATE reservas SET asistio=false, asistencia_marcada_por=NULL,
asistencia_marcada_at=NULL, asistencia_via=NULL WHERE clase_id = <clase_g7_id>;`.

G8 es de **un solo uso** para sus tres caminos: la solicitud queda `approved` (con
su suscripción y notificación), el alumno queda `activo` y el otro `rechazado`. El
segundo run sólo ve `400`/`409` (que los thresholds toleran) y el verificador
sigue pasando, pero la carrera ya no existe. Reseed para volver a medirla.

## 8. Validación hecha sobre estos scripts

Se validó sintaxis/carga **y** comportamiento real contra la API de TEST (tenant
`maipu`, `--alumnos 20`, `EMAIL_MODO=noop`, 2026-10-26):

| Escenario | Resultado k6 | Verificador de BD |
|---|---|---|
| G1 | `exit 0` · 60/60 checks · `qr_5xx=0`, `qr_otros=0`, `qr_marcado=20` | 9 ok |
| G2 | `exit 0` · 50/50 · `wods_5xx=0`, `wods_otros=0`, 10 batch + 10 simple `200`, `wods_batch_ms` p95 4,33 s | 5 ok |
| G3 | `exit 0` · 19/19 · `bazar_5xx=0`, `bazar_otros=0`, `entregado_200=1`, `conflicto_409=7`, `rechazado_200=1` | 8 ok |
| G4 | `exit 0` · 25/25 · `ref_5xx=0`, `ref_otros=0`, `codigo_200=5`, `invitacion_201=5`, `validar_propio_400=5` | 8 ok |
| G5 | `exit 0` · 576/576 · `panel_5xx=0`, `panel_otros=0`, `panel_sin_datos_404=24`, 5/5 thresholds | (sólo lectura) |
| G6 | `exit 0` · 35/35 · `g6_5xx=0`, `g6_otros=0`, `g6_aprobado_200=1`, `g6_transicion_400=7`, `g6_rechazado_200=1` | 8 ok |
| G7 | `exit 0` · 108/108 · 4/4 thresholds `count==0`, `g7_confirmado_200=12`, `g7_5xx=0`, `g7_otros=0` | 10 ok |
| G8 | `exit 0` · 25/25 · `g8_5xx=0`, `g8_otros=0`, `g8_aprobado_200=1`, `g8_ya_procesada_400=7`, `g8_activado_200=1`, `g8_conflicto_409=1`, `g8_rechazado_200=1` | 12 ok |

Total verificador: **60 ok · 0 fallos**. Lo que costó llegar ahí:

- `http_req_failed` marca en rojo los 409/400 **esperados** de G3 y G4: el número
  que importa son los `*_5xx`/`*_otros`, no ese porcentaje.
- 30 VUs en G5 → 500 por *checkout timeout* del pool (no bug del panel). El mismo
  `/kpis/churn` y `/kpis/cohortes` llamados en proceso devuelven 200.
- `noConnectionReuse: true` en G4/G5: sin él, los `sleep` > 5 s dejan que uvicorn
  cierre el keep-alive y k6 reporta status `0`/`EOF` (falso negativo).
- El seed no descontaba el stock de los pedidos que inserta → el rechazo de G3
  inflaba el stock (+1 por corrida). Corregido; el verificador lo detectó.

### G6–G8: estado de la validación

**Validados contra la API de TEST** (mismo tenant/seed que los otros cinco,
2026-10-26): los tres `exit 0`, 60/60 chequeos de k6 y **30 ok · 0 fallos** en el
verificador (8 + 10 + 12). Números en la tabla de arriba.

Cómo se completó el `load_config.json` que había quedado viejo (el seed de esta BD
era anterior a §3b/§3d), sin volver a sembrar todo:

- `alumno_activar_id` / `alumno_rechazo_activacion`: los dos primeros
  `pendiente_activacion` (787 y 786) — 786 ya estaba en el JSON.
- `solicitud_carrera_id`: la solicitud `pending` de un **tercer**
  `pendiente_activacion` (788 → solicitud 266), porque las de los alumnos activos
  ya las aprueban los escenarios C/E.
- `clase_g7_id` / `reservas_g7`: se sembró la clase de §3b a mano para hoy
  (`clase_id=7555`, coach 765, 20 reservas `confirmada`, `asistio=false`) copiando
  el `horario_base` de la clase del QR; el seed nuevo ya la crea solo.

Dos cosas que sólo se ven corriendo:

- **G7 tarda ~70 s** (`panel_coach` hace churn en background durante 40 s). Si lo
  corres desde un wrapper con timeout de 30 s, el escenario se corta a mitad de
  camino y el verificador va a encontrar reservas sin marcar: dale ≥ 2 min.
- **Verificar antes de reseed**: G6 y G8 son de una sola pasada por seed
  (`g6_aprobado_200=1` y `g8_aprobado_200=1` sólo la primera vez). Si corres el
  verificador dos veces pasa igual; si corres el **escenario** dos veces, el
  segundo run da `0` ganadores y el verificador sigue en verde porque el estado
  final ya es el correcto.

Chequeos previos a la corrida (siguen siendo la primera barrera):

| Chequeo | Resultado |
|---|---|
| `k6 inspect` de los 3 | OK · `n_g6=8` VUs + 1 rechazo, `n_g7=5` VUs `constant-vus`, `n_g8=8` + 2 + 1 |
| `python -m py_compile` del seed y del verificador | OK |
| Rutas contra la app (`@router.*` + prefijos de `main.py`) | las 8 verificadas; **corregido** `/solicitudes-planes/{id}/aprobar` → `/solicitudes/{id}/aprobar` (el router de `solicitudes_planes.py` se monta en `/api/v1/solicitudes`) |
| Forma de las respuestas | `PUT estado` y `POST rechazar` devuelven `PedidoResponse` (`estado`, `codigo_retiro`); `confirmar` devuelve `{status, confirmados, via:'coach'}` y `reservas.asistencia_via='batch'`; `activar` devuelve `password_provisional`; `rechazar` devuelve `{ok:true}` (el estado nuevo lo confirma el verificador) |
| `load_config.json` incompleto | no rompe: el escenario corta con `Falta <clave> en load_config.json (ver FLUJOS_NUEVOS.md)` y el verificador reporta la clave faltante |

Riesgos conocidos al correrlos (esperados, no bugs):

- G6 sin reseed: `g6_aprobado_200` puede ser `0` y el run `200`→`400`. El umbral
  es `count<=1`, así que no rompe.
- G7 fuera de la ventana del día (p. ej. corrida a las 23:59 y verificación
  00:01): `403` → `g7_sin_ventana_403 > 0` y exit 99. Es correcto: la clase tiene
  que ser del día.
- G8: `activar` manda correo **sincrónico**; con SMTP real cada `200` abre una
  conexión (`EMAIL_MODO=noop` en TEST, igual que G4).

Validación previa (antes de existir seed/tokens) y lo que destapó:

| Chequeo | Resultado |
|---|---|
| `node --check` (copias `.mjs` en `%TEMP%`) | 6/6 archivos OK |
| `k6 inspect` de los 5 | OK con `tokens.json` presente (antes G1/G4 fallaban por `lib/tokens.js:3`) |
| `k6 run` contra `http://127.0.0.1:9` (puerto muerto) | 5/5 `exit 99` con `*_otros > 0` y 0 excepciones JS (el objetivo: fallar ruidosamente, no dar verde) |

Esa corrida contra un puerto muerto destapó tres cosas ya corregidas:

1. `vus: N_G1` con `tokens[__VU-1]` explotaba con `TypeError: Cannot read
   property 'token' of undefined` si `tokens.json` tenía menos filas que VUs
   (ahora `vus: Math.min(N_Gn, tokens.length)` + error explícito).
2. Los escenarios daban verde con la API caída o el token vencido (los `check()`
   no fallan el run por sí solos). Ahora los 5 tienen `*_otros: count==0`.
3. `GET /api/v1/admin/registros` **no existe** (se verificó contra
   `admin.py`: sólo hay `pendientes/resumen`, `alumnos-prueba*`, `alumnos-nuevos`,
   `alumnos-convertidos` y el POST de invitación). Se reemplazó por
   `/api/v1/admin/pendientes/resumen`, que es el que cuenta `registros`, y se
   separó "404 = sin datos" (sólo KPIs materializados) de "404 = ruta rota".

## 9. Reglas de seguridad del arnés

- **Sólo TEST.** Nada de estos escenarios está pensado para PROD: G2 escribe
  WODs, G3/G6 entregan, rechazan y **validan** pedidos reales con su stock, G4 y G8
  disparan correos y G8 activa/desactiva usuarios reales (el alumno activado recibe
  password provisional y puede entrar).
- G4 con `EMAIL_MODO=noop` (o un SMTP de pruebas): evita quemar reputación de
  dominio y reproduce igual el camino de código (F1/F2 del reporte §1). Vale igual
  para G8 (`activar` manda el correo de bienvenida en línea).
- G7 escribe asistencias del día en la clase `clase_g7_id` **y** dispara el recálculo
  de churn de cada alumno marcado (background task): en un tenant con gente real,
  eso mueve datos de negocio.
- Nunca versionar `tokens.json` ni `load_config.json` con tokens reales
  (`coach_token` es un JWT vivo del coach, igual que `admin_token`).
- G3 y G6 tocan stock: correr sobre un tenant de pruebas con productos de prueba.

Referencias: `REPORTE_SESION_MANTENIMIENTO.md` §6 (por qué estos 8 flujos,
endpoints y códigos verificados) y §2 (TD-2: falta el seed y los verificadores).


## 10. Flujos G9–G14 (ampliación del 2026-11-13)

Seis escenarios más, con el **mismo patrón** que G1–G8: `lib/config_flujos.js`,
`load_config.json` generado por `_seed_load_test.py`, verificación post-test en
`_verificar_escenarios.py` y thresholds basados en LÍNEA BASE medida (no en un
SLO inventado). La suite completa queda en **20 escenarios** (A–D, E, F1, F2,
G1–G14); los 14 anteriores no se modificaron.

| Escenario | Sub-escenarios | Lo que mide de nuevo |
|---|---|---|
| `scenario_g9_pago_mercadopago.js` | `intencion` (N VUs sobre el MISMO alumno/plan) + `webhook` (1 VU × 3 reintentos) | idempotencia del alta recurrente y del webhook firmado |
| `scenario_g10_alumno_nuevo_e2e.js` | 1 | alta pública completa: 201 + correo registrado + Prueba 7 días |
| `scenario_g11_referidos_conversion.js` | `invitados` (3 VUs) + `compra_invitador` (1 VU, t+30 s) | conversión real, % individual, créditos FIFO y escalera |
| `scenario_g12_reactivacion.js` | `recuperacion` (N) + `promocion_vencida` (1) | promoción aplicada automáticamente al volver |
| `scenario_g13_mis_wods.js` | `coach` (1) + `alumnos` (N) | ciclo del WOD de punta a punta sin pisar resultados |
| `scenario_g14_activacion_e2e.js` | 1 | cookie de sesión: 1er login SIN, 2º login CON |

### 10.1 Claves nuevas en `load_config.json`

Las escribe `_seed_load_test.py` (igual que las de §2). Ninguna rompe a los
escenarios viejos: `lib/config_flujos.js` las expone con default `null`/`[]` y
el escenario que las necesita corta con un mensaje explícito.

| Clave | De dónde sale (SELECT) | Para qué |
|---|---|---|
| `n_g9` … `n_g14` | constantes del seed (`N_G9`…`N_G14`) | VUs/iteraciones de cada escenario |
| `alumno_g9` `{alumno_id, correo, token}` | `SELECT id, correo FROM usuarios WHERE correo = '<comprador de prueba de MP>'` (ver §10.3.10) | el alumno de la carrera de `/pagos/suscripcion` |
| `mp_webhook_secret` | `MERCADOPAGO_WEBHOOK_SECRET` de `backend/.env.test` | firmar el aviso (HMAC) igual que MP |
| `mp_webhook_notificacion_id` | UUID nuevo en cada seed | clave de idempotencia (`pagos_eventos.notificacion_id`) |
| `mp_webhook_payment_id` | `GET https://api.mercadopago.com/v1/payments/search` (SÓLO lectura) con el token TEST | `data.id` del aviso: el backend lo RELEE en MP |
| `mp_webhook_reintentos` | constante (`3`) | cuántas veces se reenvía el MISMO aviso |
| `correos_g10` | generados (`carga_k6_g10_NN@k6load.com`) | un correo único por VU (el seed **no** crea estos usuarios) |
| `invitador_g11` `{alumno_id, correo, codigo, token}` | `usuarios` + `codigos_referido` del invitador A | código que usan los invitados |
| `invitados_g11` `[{alumno_id, correo, token}]` | usuarios `carga_k6_g11inv*` (plan **Prueba**) | convierten el código y compran su primer plan |
| `correos_g11_alta` | generados (`carga_k6_g11_alta_NN@k6load.com`) | altas reales del flujo G10 dentro de G11 |
| `tramo_g11_umbral` | `SELECT umbral_referidos FROM tramos_referido WHERE tenant_id = 1 AND activo` | umbral que se espera alcanzado (3) |
| `candidatos_g12` `[{correo, candidato_id, promocion_id, tipo_beneficio, cantidad}]` | `candidatos_boxmagic` + `promociones_recuperacion` del seed | padrón → oferta `enviada` vigente |
| `candidato_vencido_g12` `{correo, candidato_id, promocion_id}` | idem, con `vence_en < now()` | control negativo: no debe quedar `recuperado` |
| `alumnos_g13` `[{alumno_id, correo, token}]` | usuarios `carga_k6_g13a*` con plan de pago | un alumno por VU |
| `wod_g13_id` / `clase_g13_id` | `wods` (`titulo='K6 G13 WOD'`, publicado) + `clases` de HOY con `wod_id` | WOD pendiente + clase con asistencia |
| `clase_g13_coach_id` | `clases` de HOY vacía | el coach le asigna el WOD que crea por API |
| `hoy_chile` | `date` de Chile al momento del seed | fecha del WOD del coach (no la UTC) |
| `alumnos_g14` `[{alumno_id, correo}]` | usuarios `carga_k6_g14p*` en `pendiente_activacion` | cola de activación propia (sin solicitud) |

`seed.tramos_g11_creados` y `seed.mp_notificacion_id` se guardan en la metadata
para que la limpieza del PRÓXIMO seed borre exactamente lo que creó éste.

### 10.2 Qué siembra el seed (y qué borra)

Además de lo de §1, `_seed_load_test.py` ahora:

- crea 1 alumno para G9, 1 invitador + 3 invitados para G11, 5 alumnos para G13
  y 3 `pendiente_activacion` para G14 (todos `carga_k6_*`, con suscripción
  cuando corresponde);
- crea el WOD `K6 G13 WOD` (publicado, AMRAP 12) + una clase de HOY con
  `asistio=True` para los 5 alumnos + una clase vacía para el coach, y
  `coach_disciplinas` para el coach del seed (sin eso `POST /wods/` da 403);
- crea los candidatos del padrón con sus promociones `enviada` (uno vencido);
- **crea la escalera de tramos 1/2/3 para el tenant de TEST** (`tramos_referido`)
  si esos umbrales faltan — es **dato de prueba**, se documenta acá y se borra
  en la limpieza por los ids guardados en `seed.tramos_g11_creados`;
- elige un pago REAL de la cuenta TEST de MP (lectura) para el `data.id` del
  webhook y genera un `notificacion_id` nuevo;
- limpia TODO lo anterior en cada corrida (usuarios `carga_k6_*`, candidatos,
  promociones, tramos y eventos del seed anterior, WODs `K6 G13*`/`G13 K6*`).

Tres ajustes del seed que **no** cambian los escenarios existentes pero sí sus
datos de prueba (medidos en la corrida completa del 2026-11-13):

- **La clase de G7 lleva 30 alumnos y termina ~5 min antes del seed.** Antes
  tenía los mismos 500 alumnos y el mismo horario que la clase del QR: (a) el
  check-in de TODOS respondía `ambiguo` (dos clases en la ventana) y G1 no
  marcaba a nadie, y (b) `confirmar` hace un UPDATE por reserva y con 500
  reservas × 5 VUs cada request pasaba el timeout de 60 s de k6. Con 30 (una
  clase real) y una ventana que ya cerró, G1 marca 20/20 y G7 confirma 30/30.
  El backend sólo exige el mismo DÍA para marcar, así que G7 sigue siendo válido.
- **Los WODs de G13 se titulan `G13 K6 …`, no `K6 G13 …`.** El verificador de
  G2 filtra `titulo LIKE 'K6 %'` y contaba los WODs de G13 como suyos ("1 fuera
  de draft", "1 vacío").
- **Códigos de referido para los 500 alumnos** (antes sólo `N_D` = 20): el
  verificador de G4 exige que cada alumno de `tokens.json` tenga el suyo y con
  `--alumnos 500` daba "20 vs 500". Generarlos uno por uno con
  `asignar_codigo_referido` agrega ~2-3 min al seed.


### 10.3 Decisiones y límites (leer antes de correr)

1. **Correos de las altas (`k6load.com`, no `load.test`).** El alta pública usa
   `EmailStr` y pydantic RECHAZA los dominios reservados (`.test`, `.example`):
   con `@load.test` el endpoint responde 422 antes de llegar al handler. Por eso
   los correos que pasan por la API usan `@k6load.com`, pero conservan el
   prefijo `carga_k6_` para que la limpieza los borre.
2. **IP simulada por VU (`X-Forwarded-For`).** `POST /registro/alumno-nuevo` es
   `5/hour/IP` y `POST /auth/login` `5/minute/IP` (`app/core/rate_limit.py`).
   Todos los VUs de k6 salen de 127.0.0.1, así que sin esto el escenario mediría
   el limitador (a partir del 6º registro todo sería 429). G10–G14 mandan
   `10.<escenario>.0.<VU>`; uvicorn local confía en 127.0.0.1 (`proxy_headers`
   default de 0.27) y cada VU cae en su propio bucket. **Escenario A sigue
   midiendo el límite REAL** (no manda el header).
3. **G11 no puede seguir con el usuario recién creado.** Con `EMAIL_MODO=noop`
   el alta NO devuelve `password_provisional` (el correo se "envía" simulado),
   así que el VU no puede autenticarse como ese alumno. Los pasos de conversión
   los hace el invitado **sembrado** (plan Prueba, sin compra pagada: el estado
   exacto de un alumno recién registrado). G11 igual hace el alta real por API
   (paso 1) y el verificador la comprueba junto con las conversiones.
4. **La escalera premia al CIERRE del ciclo.** `evaluar_ciclos` corre en el job
   diario, no en la compra: con el ciclo de A abierto no hay
   `premios_tramo_ciclo`. El escenario y el verificador comprueban la REGLA
   (`tramos_referidos_service.umbral_mas_alto(3, tramos)` = SÓLO el tramo 3) y
   que el ciclo no haya generado 3 premios; no inventan el premio que el job
   todavía no emitió.
5. **G9a usa un pago REAL de MP como `data.id`.** El webhook relee
   `payment().get(id)`: con un id inventado el evento queda `resultado='error'`
   (pendiente de reconciliación) en vez de cerrar como `desconocido`. La
   consulta es de SÓLO lectura y la hace el seed (fallback:
   `MP_PAYMENT_ID_FALLBACK`).
6. **G9a crea `preapproval`s `pending` en la cuenta TEST de MP** (uno por 200).
   Es el mismo efecto que un doble clic real; se cancelan desde el panel de MP.
   No se cobra nada: el checkout no se abre.
7. **G10–G14 requieren seed fresco.** Borran/crean usuarios con correos y RUT
   fijos; volver a correrlos sin resembrar da 400 (correo/RUT ya usados) en G10/
   G11/G12, 409 en G14 y `g13_pendiente_ausente` en G13. Es el mismo criterio
   que G3/G6/G8.
8. **`hoy_chile`** existe porque `new Date().toISOString()` da la fecha UTC: una
   corrida a las 21:00 de Chile crearía el WOD con la fecha del día siguiente.
9. **G14 limpia el cookie jar** antes de `POST /solicitudes/solicitar`: el 2º
   login deja la cookie httpOnly y `get_current_user` la prefiere sobre el
   Bearer; un POST autenticado por cookie exige `X-CSRF-Token` (double-submit).
   Con el jar limpio se manda el Bearer y no hace falta el CSRF (es el camino
   que el backend mantiene para clientes/tests: `core/dependencies.py`).
10. **G9a necesita DOS cosas del entorno de TEST** (sin ellas el endpoint
    responde 503 fail-closed y no hay carrera que medir):
    - `MERCADOPAGO_BACK_URL_BASE` con **https** en el proceso del backend. MP
      exige `back_url` en `POST /preapproval` y `_url_retorno_suscripcion` la
      omite si no es https (en `.env.test` `FRONTEND_URL` es http://192.168…),
      así que MP devuelve 400 "back_url is required". Para la corrida de
      validación se levantó el backend con
      `MERCADOPAGO_BACK_URL_BASE=https://test.k6load.com`.
    - Un **comprador de prueba** de la cuenta TEST como `payer_email` del
      alumno: MP rechaza un correo cualquiera con "Both payer and collector must
      be real or test users" (y tampoco acepta el correo del propio cobrador).
      El seed usa `MERCADOPAGO_TEST_BUYER_EMAIL` si está definido; si no, crea
      UNO con `POST /users/test_user` (sandbox) y lo guarda en
      `seed.mp_test_user_email` para reusarlo en las corridas siguientes. Por eso
      el alumno de G9 puede no llevar el prefijo `carga_k6_`: la limpieza lo
      borra también por el id anotado en `seed.alumno_g9_id`.
11. **Hallazgo de la primera corrida (documentado, NO corregido acá):**
    `POST /pagos/suscripcion` no es atómico. Con 5 VUs sobre el mismo alumno y
    plan, los 5 devolvieron 200 con `suscripcion_id` DISTINTO (6636…6640) y la
    BD quedó con 5 `suscripciones` **pendientes** y 5 `preapproval` en MP para
    la misma persona/plan: `_previa_reutilizable` filtra por
    `mp_preapproval_id IS NOT NULL` y esa columna se escribe recién DESPUÉS de
    llamar a MP, así que todos leen "no hay previa" (falta un lock o un UNIQUE
    parcial por alumno+plan). El verificador g9 lo marca como FALLO a propósito:
    es exactamente lo que el escenario tenía que medir.


### 10.4 Cómo correr los 6 nuevos

```powershell
python k6-tests\_seed_load_test.py --alumnos 500     # F2 usa 500 VUs
k6 run k6-tests\scenario_g9_pago_mercadopago.js
k6 run k6-tests\scenario_g10_alumno_nuevo_e2e.js
k6 run k6-tests\scenario_g11_referidos_conversion.js
k6 run k6-tests\scenario_g12_reactivacion.js
k6 run k6-tests\scenario_g13_mis_wods.js
k6 run k6-tests\scenario_g14_activacion_e2e.js
python k6-tests\_verificar_escenarios.py g9
# ... g10, g11, g12, g13, g14 (o `todos` al final de la suite)
```

⚠️ Como en §9: **sólo TEST**. G9 crea `preapproval`s en la cuenta sandbox de
MP, G11/G12 crean usuarios y créditos, G14 activa usuarios y cambia contraseñas.
`mp_webhook_secret` y los JWT de `alumno_g9`/`invitados_g11`/`alumnos_g13`
viajan en `load_config.json`: no versionar ese archivo.

### 10.5 Orden recomendado para la corrida completa (20 escenarios)

Correr **primero los G\*** (cada uno seguido de su verificador) y dejar los de
500 VUs (A/B/F1/F2) y el mix (C/D/E) al final. Motivos medidos:

- A/B/F2 saturan el pool de Neon (10+5) y el escenario siguiente empieza a ver
  `status 0` (timeouts de cliente) aunque la API esté sana: así fallaban G1/G7
  en la primera corrida completa.
- C y E aprueban las 20 solicitudes del seed y D/E crean pedidos del bazar: si
  corren antes, los verificadores de G3/G6 ven "pedidos nuevos" que no son suyos
  (esperan exactamente los 4 del seed).

Orden usado el 2026-11-13 (una sola semilla, sin resembrar entre escenarios):
`G1 G2 G3 G4 G5 G6 G7 G8 G9 G10 G11 G12 G13 G14 C D E A B F1 F2`, con
`python k6-tests/_verificar_escenarios.py gX` inmediatamente después de cada GX.




