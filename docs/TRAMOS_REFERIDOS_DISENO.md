# Diseño — Tramos del invitador (Parte C)

> **Estado: IMPLEMENTADO en TEST (2026-10-28).** Migración `064_tramos_referido_ciclo`
> aplicada en `crimson-tooth`; motor, job diario, APIs y pantallas listos.
> Las 5 decisiones de negocio quedaron cerradas (ver §9). **Nada se desplegó ni se
> disparó en PROD**: el motor de PROD sigue en `promociones` hasta que el admin cargue
> su escalera y cambie el flag.
> Fecha del diseño: 2026-10-28.

## 0. Regla de negocio (no renegociable)

1. El **invitado** gana su % en la primera compra, sin condiciones.
   **Ya funciona y este diseño no lo toca** (`referidos_service.confirmar_compra`).
2. El **invitador** se evalúa **al cierre de SU ciclo de facturación** (los días
   de su plan, típicamente 30, no el mes calendario y no acumulado entre ciclos).
3. El premio sale de una **tabla de tramos configurable**: cantidad de referidos
   alcanzados en el ciclo → premio (% de descuento, días gratis, mes gratis).
   Ejemplo ilustrativo: 1→15 %, 2→30 %, 3→mes gratis. **Nada hardcodeado.**
4. La cantidad de tramos y sus valores los define el admin en una pantalla.

## 1. Qué existe hoy (leído del código, no supuesto)

| Pieza | Estado |
| --- | --- |
| `configuracion_referidos` (1 fila por tenant) | `porcentaje_descuento_invitado`, `porcentaje_descuento_invitador`, `activo` — `backend/app/models/referidos.py:259` |
| `promociones_referidos` | `umbral_referidos_convertidos`, `periodo` (`mensual`), `tipo_premio`, `valor_premio`, `activo` — `referidos.py:337` (migración 053) |
| `promociones_referidos_detectadas` | snapshot del premio + `periodo_cumplido` `'YYYY-MM'` + `estado` (`pendiente_confirmacion`/`confirmado`/`rechazado`) — `referidos.py:375` |
| Detección | job diario **23:55 CLT** `detectar_promociones_referidos` — `backend/app/services/scheduler.py:199`, servicio `promociones_referidos_service.py:175` |
| Confirmación admin | `POST /referidos/promociones-detectadas/{id}/confirmar` — `backend/app/api/v1/referidos.py:725`; aplica premio en `promociones_referidos_service.py:392` |
| Cola unificada | pestaña **Premios** de `/admin/pendientes` (`PendientesPromocionesReferidos.jsx`) |
| Crédito del invitador | `creditos_referido` (`porcentaje`, `estado`, `promocion_detectada_id`), se consume en la próxima compra (`referidos_service.py:517`) |
| Pantalla de tramos | `GestionPromocionesReferidos.jsx` (Marketing → Referidos), con publicación en el carrusel (`ModalPublicarPromocion.jsx`, `POST /promociones/{id}/publicar`) |

O sea: **el 80 % de la infraestructura ya está**, incluida la confirmación del
admin, el snapshot del premio, la notificación y la publicación en el carrusel.
Lo que falta es el **motor de evaluación**, y tiene dos desvíos fuertes:

### Desvío 1 — cuenta por mes calendario, no por ciclo del alumno

`detectar_promociones` usa `periodo_de(momento)` → `'YYYY-MM'` y
`rango_periodo()` (día 1 al día 1 del mes siguiente). Un alumno que compró el 12
de septiembre cierra su ciclo el 12 de octubre: sus referidos del 1–12 de octubre
caen en dos "períodos" distintos y los del 13–31 caen en el ciclo siguiente. La
regla del punto 2 se rompe.

### Desvío 2 — los tramos NO son excluyentes

La consulta agrupa por `(promocion, alumno)` con `HAVING count >= umbral`, así
que un alumno con 3 referidos en el mes genera **una fila por cada tramo
alcanzado** (1, 2 y 3). Si el admin confirma las tres, se llevan **los tres
premios** en vez del tramo más alto. En una escalera 1→15 %, 2→30 %, 3→mes
gratis eso es un regalo acumulado, no un tramo.

### Otros detalles a resolver en la implementación

- `mes_gratis`/`dias_gratis` **exigen suscripción vigente**: si el alumno no
  tiene plan activo al confirmar, el endpoint devuelve 409 y el premio queda
  trabado (`promociones_referidos_service.py:421`). Para tramos hace falta una
  cola de "premio pendiente de aplicar".
- Cada compra crea una fila **nueva** en `suscripciones`
  (`backend/app/api/v1/suscripciones.py:116`), con su `fecha_inicio` y
  `fecha_expiracion`. Eso es una ventaja: **el ciclo ya está en los datos**, no
  hay que inventarlo ni suponer 30 días.
- Compras anticipadas dejan ciclos solapados; una conversión no puede contarse
  dos veces.

## 2. Modelo de datos propuesto

### 2.1 Tabla nueva `tramos_referido` (la escalera)

```sql
CREATE TABLE tramos_referido (
    id            serial PRIMARY KEY,
    tenant_id     integer NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    umbral_referidos integer NOT NULL,                    -- 1, 2, 3…
    tipo_premio   tipo_premio_referido NOT NULL,          -- enum ya existente (053)
    valor_premio  numeric(10,2),                          -- NULL en mes_gratis
    activo        boolean NOT NULL DEFAULT true,
    creado_en     timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_tramos_referido_umbral CHECK (umbral_referidos > 0),
    CONSTRAINT uq_tramos_referido_tenant_umbral UNIQUE (tenant_id, umbral_referidos)
);
CREATE INDEX ix_tramos_referido_tenant ON tramos_referido (tenant_id, activo);
```

Reglas de valor (validadas en Pydantic **y** con `CHECK`, como ya hace
`PromocionReferidosCreate`):

| `tipo_premio` | `valor_premio` |
| --- | --- |
| `mes_gratis` | `NULL` (30 días, `DIAS_PREMIO_MES_GRATIS`) |
| `dias_gratis` | entero > 0 |
| `descuento_extra` | 0 < valor ≤ 100 |

**`UNIQUE (tenant_id, umbral_referidos)` es la pieza clave**: una escalera no
puede tener dos premios en el mismo escalón. El orden lo da el umbral, no una
columna `orden` (evita estados inconsistentes).

### 2.2 Tabla nueva `premios_tramo_ciclo` (lo detectado, por ciclo)

```sql
CREATE TABLE premios_tramo_ciclo (
    id                    serial PRIMARY KEY,
    tenant_id             integer NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id            integer NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tramo_id              integer REFERENCES tramos_referido(id) ON DELETE SET NULL,
    suscripcion_id        integer REFERENCES suscripciones(id) ON DELETE SET NULL,
    ciclo_inicio          date NOT NULL,
    ciclo_fin             date NOT NULL,
    referidos_convertidos integer NOT NULL,
    -- snapshot del premio (mismo criterio que promociones_referidos_detectadas)
    umbral_referidos      integer NOT NULL,
    tipo_premio           tipo_premio_referido NOT NULL,
    valor_premio          numeric(10,2),
    estado                estado_promocion_detectada NOT NULL
                          DEFAULT 'pendiente_confirmacion',
    fecha_deteccion       timestamptz NOT NULL DEFAULT now(),
    fecha_confirmacion    timestamptz,
    confirmado_por_usuario_id integer REFERENCES usuarios(id) ON DELETE SET NULL,
    aplicado_en           timestamptz,
    CONSTRAINT uq_premios_tramo_ciclo_ciclo UNIQUE (usuario_id, suscripcion_id),
    CONSTRAINT ck_premios_tramo_ciclo_ventana CHECK (ciclo_fin > ciclo_inicio)
);
CREATE INDEX ix_premios_tramo_ciclo_estado ON premios_tramo_ciclo (estado);
```

`UNIQUE (usuario_id, suscripcion_id)` **garantiza en la BD** "un premio por
ciclo", que es exactamente la exclusividad que hoy falta. La detección usa
`ON CONFLICT DO NOTHING` (idempotente, igual que la Fase 5).

### 2.3 Una columna nueva en `configuracion_referidos`

```sql
ALTER TABLE configuracion_referidos
    ADD COLUMN motor_premios varchar(20) NOT NULL DEFAULT 'promociones';
-- valores: 'promociones' (Fase 5 actual) | 'tramos' (este diseño)
```

Motivo: si conviven los dos motores, un alumno con 3 referidos recibe el premio
de la promoción **y** el del tramo. El flag hace que el job corra **uno solo** y
que la pantalla avise cuál está activo. La migración deja `'promociones'` para
no cambiar el comportamiento de PROD el día del deploy.

### 2.4 Por qué tablas nuevas y no reusar `promociones_referidos`

| Criterio | `promociones_referidos` (reusar) | `tramos_referido` (nuevo) |
| --- | --- | --- |
| "Un premio por ciclo" | no expresable (UNIQUE = promoción+alumno+mes) | `UNIQUE (usuario, suscripción)` |
| Escalera vs. campañas sueltas | mezcla dos conceptos en la misma fila | una tabla = una escalera |
| Publicación en carrusel (`promocion_id`) | ya funciona, se rompe al cambiar semántica | conviven |
| Historial ya congelado | `promociones_referidos_detectadas` intacto | cero migración de datos |
| Riesgo de doble premio | alto | nulo (motor único) |

Alternativa evaluada y descartada: agregar `exclusivo` + `orden` a
`promociones_referidos`. Menos código, pero deja el cálculo por mes calendario
(`periodo_cumplido` es `'YYYY-MM'` con CHECK de formato) y obliga a distinguir
campañas de escalones dentro de la misma tabla en cada consulta.

### 2.5 Migración propuesta

`backend/alembic/versions/064_tramos_referido_ciclo.py`
(`revision = "064_tramos_referido_ciclo"`,
`down_revision = "063_notificaciones_soft_delete"`):

1. `CREATE TABLE tramos_referido` + índice + checks.
2. `CREATE TABLE premios_tramo_ciclo` + índice + checks.
3. `ALTER TABLE configuracion_referidos ADD COLUMN motor_premios ... DEFAULT 'promociones'`.
4. **Sin backfill automático.** Opcional (script aparte, fuera de la migración):
   `scripts/importar_promociones_a_tramos.py`, que copia las
   `promociones_referidos` activas → `tramos_referido` y deja el flag en
   `'tramos'`. Se corre recién cuando el admin apruebe su escalera.
5. `downgrade()`: borra las dos tablas y la columna. Los premios ya otorgados
   quedan como `creditos_referido` / extensiones de suscripción (no se tocan).


## 3. Evaluación al cierre del ciclo

### 3.1 El ciclo sale de `suscripciones`, no de una constante

Cada compra crea una fila nueva (`suscripciones.py:116`) con `fecha_inicio` y
`fecha_expiracion = inicio + plan.duracion_dias` (días de Chile,
`fin_de_plan_chile`). Entonces:

```
ciclo del alumno = (suscripcion.fecha_inicio, suscripcion.fecha_expiracion)
```

- No se hardcodean 30 días: si un plan dura 15 o 45, el ciclo es ese.
- No se usa el mes calendario.
- Un alumno sin suscripción nunca compró plan: **no tiene ciclo de facturación
  y no se evalúa** (el invitado que aún no compra sigue con su descuento normal).
  Queda registrado en el log del job, no en la cola.

### 3.2 Ventana efectiva (compras anticipadas)

Si el alumno compra antes de que venza su plan, hay dos ciclos solapados y una
conversión podría contarse dos veces. Regla:

```
ventana = [ciclo.inicio, min(ciclo.fin, inicio_de_la_siguiente_suscripcion))
```

La conversión cuenta en el **primer** ciclo cuya ventana la contiene. Además,
para auditar, la detección guarda `referidos_convertidos` (snapshot) y el
`ciclo_inicio`/`ciclo_fin` usados.

### 3.3 Cuándo corre

Job nuevo `job_evaluar_tramos_referidos`, **todos los días 00:20 CLT**
(el cierre de mes es 00:05 y la generación de clases 00:05: no se pisan),
con `lock_de_job("evaluar_tramos_referidos")` — el mismo patrón de
`scheduler_lock` que usan los otros 9 jobs, para que dos instancias en deploy
no dupliquen premios.

Cada corrida busca los ciclos **cerrados y todavía no evaluados**:

```sql
-- ciclos que vencieron en los últimos N días (N configurable, 7 por defecto:
-- cubre un deploy caído) y que no tienen premio ni evaluación previa
SELECT s.*
FROM suscripciones s
JOIN usuarios u ON u.id = s.usuario_id AND u.rol = 'alumno' AND u.estado = 'activo'
LEFT JOIN premios_tramo_ciclo p
       ON p.usuario_id = s.usuario_id AND p.suscripcion_id = s.id
WHERE s.tenant_id = :tenant
  AND s.fecha_expiracion <= now()
  AND s.fecha_expiracion >  now() - interval '7 days'
  AND p.id IS NULL
```

Para cada ciclo:

1. Contar `referidos_aplicados` con `estado='convertido'` del invitador,
   `fecha_conversion >= ciclo.inicio` y `< min(ciclo.fin, siguiente_inicio)`.
2. Buscar **el tramo más alto alcanzado**:
   `SELECT * FROM tramos_referido WHERE tenant_id=:t AND activo ORDER BY umbral_referidos DESC`
   → el primero con `umbral <= convertidos`. **Uno solo** (exclusividad).
3. Insertar en `premios_tramo_ciclo` con snapshot + `ON CONFLICT DO NOTHING`.
4. Notificar al admin (campana in-app + correo), reusando
   `_mensaje_notificacion` / `_notificar_detecciones` de
   `promociones_referidos_service.py` (mismo formato, distinto origen).

Si el alumno no alcanzó ningún tramo **no se escribe nada** (no se llena la cola
de filas con 0 referidos).

### 3.4 Confirmación del admin (la cola de Parte B.2)

La fila nace `pendiente_confirmacion` y aparece en la **misma pestaña Premios**
de `/admin/pendientes`. `GET /admin/pendientes/resumen` suma esta tabla además de
`promociones_referidos_detectadas` (un solo contador para el admin).

`POST /referidos/tramos/premios/{id}/confirmar` aplica el premio **congelado**:

- `mes_gratis` / `dias_gratis` → extiende la suscripción vigente
  (`dias_de_extension` + `fin_de_plan_chile`, el mismo código de la Fase 5).
- `descuento_extra` → crea `creditos_referido` con `porcentaje`, consumible en
  la próxima compra (`referidos_service.confirmar_compra`, ya implementado).
- **Cambio respecto de la Fase 5**: si el alumno no tiene plan vigente, el
  premio **no** se rechaza con 409. Queda `confirmado` con `aplicado_en = NULL`
  y un job/acción "aplicar pendientes" lo resuelve cuando el alumno compre.
  Razón: un premio ganado no puede perderse porque el alumno esté entre planes.
- `rechazar` → `estado='rechazado'`, no aplica nada (igual que hoy).

### 3.5 API propuesta

| Método | Ruta | Quién |
| --- | --- | --- |
| `GET` | `/referidos/tramos` | admin (escalera completa, ordenada por umbral) |
| `POST` | `/referidos/tramos` | admin (crea escalón; 409 si el umbral ya existe) |
| `PUT` | `/referidos/tramos/{id}` | admin (edita; los premios ya detectados conservan snapshot) |
| `DELETE` | `/referidos/tramos/{id}` | admin (409 si ya generó premios: se apaga) |
| `GET` | `/referidos/tramos/premios` | admin (cola, con filtro por estado) |
| `POST` | `/referidos/tramos/premios/{id}/confirmar` | admin |
| `POST` | `/referidos/tramos/premios/{id}/rechazar` | admin |
| `GET` | `/referidos/mi-progreso` | alumno: referidos del ciclo en curso + tramo alcanzado + cuánto falta |

`GET /referidos/mi-progreso` es lo que hace entendible el programa en
`/alumno/invita-y-gana` ("llevas 2 de 3 referidos en tu ciclo, cierra el 12/11").
No expone datos de otros alumnos.


## 4. Pantalla del admin: "Tramos del invitador"

**Dónde**: Marketing → Referidos, como **tercera pestaña** junto a
"Configuración", "Promociones" (Fase 5) y "Tarjeta del carrusel". Componente
nuevo `frontend/src/components/GestionTramosReferidos.jsx`, mismo lenguaje
visual que `GestionPromocionesReferidos.jsx` (tabla + modal de alta/edición).

Contenido:

1. **Escalera** ordenada por `umbral_referidos`: `1 referido → 15 %`,
   `2 → 30 %`, `3 → 1 mes gratis`. Alta, edición y apagado por fila.
2. **Validaciones en el cliente y en el backend**: umbral entero > 0 y no
   repetido; `descuento_extra` 0–100; `dias_gratis` entero > 0; `mes_gratis` sin
   valor. Aviso si la escalera tiene un salto raro (ej. el tramo 2 premia menos
   que el 1).
3. **Vista previa de la escalera** tal como la lee el alumno en Invita y Gana.
4. **Publicar en el carrusel** (ver 5): botón con el MISMO flujo de confirmación
   de `ModalPublicarPromocion.jsx` — nunca publica solo.
5. **Selector de motor** (`motor_premios`): "Promociones por umbral (actual)" vs
   "Tramos por ciclo (nuevo)", con advertencia explícita de que al cambiar de
   motor los premios ya detectados conservan su snapshot.

Pantalla del alumno (`/alumno/invita-y-gana`): bloque "Tu ciclo" con
`GET /referidos/mi-progreso` — ciclo actual, referidos convertidos, tramo
alcanzado y el siguiente escalón. Sin datos personales de terceros.

## 5. Relación con la Parte A.3 (carrusel)

Ya está implementado el patrón correcto: la tarjeta del carrusel **no** enlaza a
un producto del Bazar, sino a `/alumno/invita-y-gana`, vía
`AvisoMarketing.tipo='promocion'` + `promocion_id` (migración 056) y
`CarruselMarketing.jsx:279`. Para los tramos se reusa igual:

- Se publica **la escalera**, no un escalón: título/texto libres + flyer, y el
  destino sigue siendo `/alumno/invita-y-gana`.
- Pieza mínima: `POST /referidos/tramos/publicar` con el mismo
  `PublicarPromocionRequest` y una columna `tramo_publicado` (o reusar
  `promocion_id` apuntando al tramo más alto) — **decisión abierta 4**.
- Requisito de la Parte A.3 ("campo de destino para avisos sin `producto_id`")
  ya está cubierto por `tipo`; si más adelante se quieren destinos arbitrarios
  (ej. `/alumno/bazar?categoria=x`), conviene un `destino_url` validado contra
  una whitelist de rutas internas. **No** se implementa en este tramo.

## 6. Plan de pruebas (cuando se implemente)

Unitarias (sin BD, patrón `test_promociones_referidos_unit.py`):

- `tramo_alcanzado(convertidos, tramos)` → **el más alto**, no la lista de todos.
- Validaciones de valor por `tipo_premio` (reusar `dias_de_extension`).
- Ventana efectiva con ciclos solapados (conversión contada una sola vez).
- Snapshots: editar/apagar un tramo no cambia un premio ya detectado.

Integración (BD TEST + servidor en `:8000` **apuntando a TEST**, ver §8):

- Ciclo cerrado con 3 referidos y escalera 1/2/3 → **una** fila, del tramo 3.
- Dos corridas del job → la segunda no duplica (`ON CONFLICT DO NOTHING`).
- Confirmar `mes_gratis` → `fecha_expiracion + 30 días`, una sola vez.
- Confirmar `descuento_extra` → `creditos_referido` pendiente y descuento real
  en la siguiente compra (`confirmar_compra`).
- Confirmar sin plan vigente → `confirmado` + `aplicado_en NULL`, sin 409.
- La cola de `/admin/pendientes` cuenta el premio del tramo.
- Aislamiento por tenant: un tramo de otro box no se evalúa ni se confirma.

Estas últimas van con datos propios y limpieza al final (patrón de
`test_referidos_integracion.py`), porque tocan **dinero**.

## 7. Rollout propuesto

1. Migración 064 (schema + flag en `'promociones'`, sin cambio funcional).
2. Backend del motor de tramos + tests unitarios (flag apagado → nada cambia).
3. Pantalla de tramos + APIs admin.
4. Prueba en TEST: crear escalera, simular un ciclo cerrado, confirmar premio.
5. Cambio de flag a `'tramos'` en PROD **después** de que el admin cargue la
   escalera; apagar (no borrar) las promociones por umbral viejas.
6. `mi-progreso` en Invita y Gana + publicación en el carrusel.

## 8. Aviso de entorno (bloqueante para implementar)

- `backend/.env` (el que levanta el uvicorn de `:8000`) apunta a
  **`ep-winter-star-akwis51j` = PROD**.
- `backend/.env.test` apunta a `ep-crimson-tooth-akhx7q2s` (TEST oficial,
  `config.py:223`).
- `ep-lingering-fog-arywdnbg` (el TEST que pide el encargo) está en
  `ENDPOINTS_RETIRADOS` (`config.py:243`): ya no es TEST oficial.
- Antes de correr tests de integración o migraciones hay que decidir a qué rama
  se apunta y arrancar el servidor con esa rama. **No se corrió nada de eso.**

## 9. Decisiones de negocio — CERRADAS (2026-10-28)

1. **Motor único**: `configuracion_referidos.motor_premios` (`'promociones'` |
   `'tramos'`). Sólo uno evalúa por box: el job de promociones filtra los boxes en
   `'tramos'` (`promociones_referidos_service.detectar_promociones`) y el de tramos
   sólo mira los que están en `'tramos'`. Al encender `'tramos'`, la detección por
   mes calendario deja de pagar sin borrar historial.
2. **Alumno sin ciclo**: no se evalúa. `evaluar_ciclos` recorre sólo ciclos
   cerrados de suscripciones de alumnos activos; sin suscripción no hay ciclo.
3. **Premio sin plan vigente**: queda `confirmado` con `aplicado_en = NULL` (NO es
   409) y el job diario lo aplica cuando el alumno vuelve a tener un plan
   (`aplicar_pendientes`).
4. **Publicación**: la tarjeta anuncia la escalera COMPLETA. El backend arma el pie
   con los escalones activos al publicar (`_texto_con_escalera`) y republicar
   actualiza esa misma tarjeta (`avisos_marketing.escalera_tramos`).
5. **No acumulable** (cambia la propuesta original de este documento): el premio
   del tramo es UN descuento y **no se suma** al crédito individual del referido.
   Son conceptos separados y cada uno se consume en una compra distinta
   (`referidos_service._credito_pendiente` toma UN crédito por compra), así que
   dos premios del 15 % **no** se convierten en uno del 30 %.

## 10. Implementación (2026-10-28)

| Pieza | Archivo |
| --- | --- |
| Migración (tablas, `motor_premios`, 3.er origen del crédito, tarjeta) | `backend/alembic/versions/064_tramos_referido_ciclo.py` |
| Modelos (`TramoReferido`, `PremioTramoCiclo`, `MotorPremios`) | `backend/app/models/referidos.py` |
| Motor: evaluación por ciclo, confirmación, pendientes, progreso | `backend/app/services/tramos_referidos_service.py` |
| Flag del motor en el motor de promociones (exclusividad) | `backend/app/services/promociones_referidos_service.py` |
| Job diario 00:20 CLT + aplicación de pendientes | `backend/app/services/scheduler.py` (`job_evaluar_tramos_referidos`) |
| APIs admin + `mi-progreso` + publicar escalera | `backend/app/api/v1/referidos.py` |
| Esquemas Pydantic | `backend/app/schemas/referidos.py` |
| Contador de Pendientes (misma pestaña Premios) | `backend/app/api/v1/admin.py` |
| Pantalla "Tramos del invitador" | `frontend/src/components/GestionTramosReferidos.jsx` |
| Cola de premios de tramo | `frontend/src/components/PendientesPromocionesReferidos.jsx` |
| "Tu ciclo" del alumno | `frontend/src/pages/alumno/InvitaYGana.jsx` |
| Hooks de React Query | `frontend/src/hooks/queries.js` |

Pruebas: `backend/tests/test_tramos_referidos_unit.py` (29) y
`backend/tests/test_tramos_referidos_integracion.py` (9, box de prueba propio que
se crea y se borra en TEST). Resultado: **29 + 9 en verde** (2026-10-28).


