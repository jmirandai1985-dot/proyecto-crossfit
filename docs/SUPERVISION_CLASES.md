# Supervisión de Clases — modelo de datos y convenciones (backend)

Documento de referencia del módulo **Supervisión** (admin) y de la **asignación de
coaches** (panel del coach). Se escribe antes de tocar código (Tanda 1 / bloque B0)
para dejar por escrito dos cosas que ya causaron bugs y confusión:

1. hay **dos tablas "de horarios"** en la base y sólo una está viva;
2. la convención de `dia_semana` **no** es la de PostgreSQL.

> Estado de este documento: Tanda 1 en curso. Escrito en **B0**; actualizado en **B1**
> (grilla por rango + DOW) y **B2** (asignación de coach: `clases.asignacion_origen` +
> `horarios_coach` + tomar/soltar). Faltan B3 (asignación de emergencia del admin con
> aviso al coach) y B6 (liberación al dar de baja un coach / cambiar la disciplina).

---

## 1. `horarios` (REAL) vs `horarios_base` (ZOMBIE)

| Tabla | Estado | Quién la usa |
|---|---|---|
| **`horarios`** | ✅ VIVA | Todo el código: `horarios.py`, `supervision.py`, `clases.py`, `services/generar_clases.py`, `services/scheduler.py`, seeds |
| `horarios_base` | 🧟 LEGADO (0 filas) | Nadie: no hay modelo ni endpoint que la lea o escriba |

El modelo se llama `HorarioBase` pero **su tabla es `horarios`**:

```python
# backend/app/models/horario_base.py
class HorarioBase(Base):
    __tablename__ = "horarios"        # ← la clase se llama "Base" por historia; la tabla NO
    dia_semana = Column(Integer, nullable=False)  # 0=Lunes, 6=Domingo
```

Evidencia de que `horarios_base` es legado (no "otra fuente de verdad"):

- `sql/schema_clean.sql` (documento **desactualizado**: define 8 de ~24 tablas) la crea y
  además declara `clases.horario_base_id REFERENCES horarios_base(id)`.
- `backend/corregir_fk_clases.py` existe exactamente para mover esa FK a `horarios`.
- `backend/recrear_tabla_clases.py` (script viejo) la referencia en su DDL.
- `backend/scripts/crear_usuarios_demo.py` la lista como **tabla LEGADO** (con una FK
  `coach_id` que hay que contemplar al borrar usuarios de demo).
- `MIGRACION_PROD_NEON.md` la lista con **0 filas** en PROD.
- ⚠️ `COMPARACION_MODELOS_VS_SCHEMA.md` dice `HorarioBase → horarios_base ✅ Coincide`:
  **es un error de ese documento viejo** (el modelo mapea a `horarios`). Este archivo manda.

**Regla:** nada nuevo se construye sobre `horarios_base`. Supervisión y el panel del coach
leen `horarios` (plantilla recurrente) y `clases` (instancias generadas).

## 2. Convención `dia_semana`: 0 = LUNES … 6 = DOMINGO

- `horarios.dia_semana` (SMALLINT) y las comparaciones en Python usan
  **`date.weekday()`**: 0=Lunes … 6=Domingo (`generar_clases.py`, `horarios_base.py`).
- ⚠️ **PostgreSQL va al revés**: `EXTRACT(DOW FROM fecha)` devuelve 0=Domingo … 6=Sábado.
  Si se expone crudo al frontend, la grilla queda corrida un día (era el bug de "DOW").
- Conversión canónica, centralizada en `app/utils/semana.py`:

  ```sql
  ((EXTRACT(DOW FROM <columna>)::int + 6) % 7)   -- 0 = Lunes … 6 = Domingo
  ```

  `SQL_DOW_LUNES_CERO` (constante) arma esa expresión para cualquier columna y
  `dow_pg_a_lunes_cero(dow)` hace lo mismo en Python puro (para tests).
- **Los domingos no hay clases**: `generar_clases_para_fecha` corta si `weekday() == 6` y
  `generar_clases_para_rango` saltea los domingos. La grilla de Supervisión es **lunes a
  sábado** (6 columnas).

## 3. Generación de clases (28 días hacia adelante)

`backend/app/services/generar_clases.py`:

- `DIAS_ANTICIPACION = 28` (4 semanas), valor único compartido por todos los disparadores.
- `generar_clases_para_fecha(db, tenant_id, fecha)` crea **una `Clase` por cada `horarios`
  activo** del `dia_semana` de esa fecha, copiando `disciplina_id`, `hora_inicio`,
  `hora_fin` y `cupo_maximo` (que además se guarda como `cupo_original`, el techo de
  "+10 cupos"). Es idempotente por `(tenant_id, horario_base_id, fecha)`.
- Tres disparadores, todos usando el mismo servicio:
  1. **startup** (`app/main.py`, lifespan): rango `[hoy, hoy+28]`;
  2. **scheduler** diario 00:05 CLT (`app/services/scheduler.py`);
  3. **`POST /api/v1/horarios/generar-clases-dia`** (admin, botón explícito).
  `GET /api/v1/clases?generar=true` es **opt-in** (default `false`: un GET no debe escribir).

## 4. Cómo se resuelve hoy el coach de una clase

- La fuente de verdad es **`clases.coach_id`** (`usuarios.id`, `ON DELETE SET NULL`).
- **Fallback sólo visual**: `GET /api/v1/clases/` completa `coach_nombre` con el **único
  coach activo de la disciplina** cuando `coach_id IS NULL` (`clases.py`, bloque "Fix
  N+1"). No escribe nada: la clase sigue sin coach en la BD.
- **⚠️ Cobertura de emergencia**: `clases.py` (y `supervision.py`) calculan
  `cobertura_emergencia` con un `EXISTS` sobre la tabla `cobertura_emergencia` por
  `clase_id`; cada fila la registra `core/dependencies.verificar_coach_disciplina`
  cuando un coach opera una disciplina que no tiene asignada.
- **`asignacion_origen`** (B2, §6) dice además *cómo* llegó ese coach: `'coach'` (✅ la
  tomó el coach) o `'admin'` (🟦 la asignó el admin).

## 5. Endpoints del módulo (mapa)

**Supervisión** (admin, `/api/v1/supervision`):

| Endpoint | Para qué |
|---|---|
| `GET /grilla?desde=&hasta=&disciplina_id=` | **B1** · grilla por rango (lunes-sábado): `dias`, `plantillas` (tabla `horarios`), `celdas` (clases reales) y `resumen` de cobertura. Máx. 62 días; `desde > hasta` → 400 |
| `GET /grid-semanal?fecha=` | semana fija (lunes-domingo) de la semana de `fecha`; ya devuelve `dia_semana` 0=Lunes (era el bug de DOW) |
| `GET /horarios-base?disciplina_id=` | plantillas de una disciplina + coach de la última clase generada |
| `GET /coaches-todos?disciplina_id=` | coaches activos del box marcando si pertenecen a la disciplina |
| `GET /cupos-disciplinas`, `PATCH /cupo-disciplina` | cupos por disciplina (afecta clases futuras) |
| `GET /proxima-clase-reservas?horario_base_id=` | próxima clase de un horario + reservas (self-service) |

La grilla **oculta** disciplinas inactivas, sin horarios activos y las que **no**
requieren coach (`requiere_coach=false`, p. ej. Open Box/Musculación self-service).

## 6. Asignación de coach (B2) — tomar / soltar

### Las cuatro marcas (B5 las pinta)

| Marca | `marca` | De dónde sale |
|---|---|---|
| ✅ tomada por el coach | `coach` | `clases.coach_id` + `asignacion_origen='coach'` |
| 🟦 asignada por el admin | `admin` | `clases.coach_id` + `asignacion_origen='admin'` |
| ⚠️ cobertura de emergencia | `emergencia` | existe fila en `cobertura_emergencia` para la clase (gana siempre) |
| 🔴 sin coach | `sin_coach` | `clases.coach_id IS NULL` |

Regla única y compartida: `services/asignaciones_clases.marca_cobertura` (el backend la
manda lista en `GET /clases` y en la grilla; el frontend no la recalcula).

### Columnas nuevas en `clases` (migración **042**)

`asignacion_origen` (`'coach'` | `'admin'` | NULL), `asignada_por` (FK usuarios,
SET NULL) y `asignada_en` (TIMESTAMPTZ). La clase sigue **sin** `tenant_id`-less:
nada cambia en el aislamiento por box.

### `horarios_coach` (migración **043**)

Una fila por asignación de horario recurrente, con **vigencia** (`vigente_desde` /
`vigente_hasta`; NULL = sigue vigente) y el índice **único parcial**
`uq_horarios_coach_vigente` sobre (`horario_id`) `WHERE vigente_hasta IS NULL`:
la BD garantiza **un solo coach vigente por horario**.

### Flujos

| Acción | Endpoint | Qué hace |
|---|---|---|
| Tomar una clase puntual | `POST /clases/{id}/tomar?alcance=clase` | `coach_id` + marca ✅ de ESA clase |
| Tomar el horario recurrente | `POST /clases/{id}/tomar?alcance=horario` | lo anterior **+** vigencia en `horarios_coach` **+** backfill de las clases futuras del horario |
| Soltar la clase | `POST /clases/{id}/soltar?alcance=clase` | limpia `coach_id` y la marca |
| Soltar el horario | `POST /clases/{id}/soltar?alcance=horario` | cierra la vigencia y libera las clases futuras del horario |
| Clases **nuevas** | `services/generar_clases.py` | cada clase generada hereda al coach **vigente** de su horario (1 query por día) |

Guardas (todas devuelven **409** con el nombre de quien la tiene):

- tomar/soltar una clase de **otro** coach → 409 (soltar ajeno para un coach → 403);
- tomar un **horario** donde alguna clase futura es de otro coach → 409 con nombre y fecha;
- vigencia **vigente** de otro coach en ese horario → 409;
- clase **pasada** (`fecha < hoy` en Chile) → 409;
- `alcance` que no sea `clase`/`horario` → 400.

El admin puede usar los mismos endpoints (queda registrado como 🟦 `admin`); para
la asignación de emergencia tiene su propio camino (B3).

## 7. Asignación de emergencia del admin (B3) — con aviso al coach

| Acción | Endpoint | Qué hace |
|---|---|---|
| Asignar coach a una clase | `POST /supervision/clases/{id}/asignar` (body: `coach_id`, `motivo?`, `forzar_emergencia?`) | marca 🟦 `admin` + **aviso al coach** en su campana. Si el coach **no dicta** esa disciplina: con `forzar_emergencia=true` (default) se registra la ⚠️ cobertura de emergencia (y el aviso a los admins del flujo existente); con `false` → 409 |
| Quitar el coach de una clase | `DELETE /supervision/clases/{id}/asignar` | 🔴 sin coach + aviso al coach que la tenía |

Sólo la clase puntual: **no** toca el horario recurrente (para eso, el coach usa
`POST /clases/{id}/tomar?alcance=horario` y el admin reasigna con el endpoint de arriba).

Avisos: tabla `notificaciones` (la de la campana, **sin correo**), emitidos con
`services/notificaciones_panel.notificar_usuario`:

| `tipo` | Destinatario | Cuándo |
|---|---|---|
| `clase_asignada` | coach nuevo | El admin le asignó la clase |
| `clase_reasignada` | coach anterior | La clase era suya y se la pasaron a otro |
| `clase_liberada` | coach saliente | El admin le quitó la clase |

Guardas: 404 si el coach no es del box; 409 si no tiene rol `coach`, no está activo, la
clase ya es suya, está cancelada o es pasada. Las dos acciones quedan en `auditoria`
(`asignar_coach_admin`, `quitar_coach_admin`).

## 8. Liberación automática (B6)

Un coach que ya no puede dictar no queda a cargo de nada:

| Disparador | Endpoint | Qué se libera |
|---|---|---|
| Coach dado de baja (soft delete) | `DELETE /usuarios/{id}` | Sus vigencias abiertas + sus clases futuras |
| Coach pasa a `estado != 'activo'` o deja de tener rol `coach` | `PUT /usuarios/{id}` | Idem, en la MISMA transacción del cambio |
| Se cambia la **disciplina** de una plantilla | `PUT /horarios/{id}` con `disciplina_id` | La vigencia de ESE horario + las clases futuras de ESE horario |

- `services/asignaciones_clases.hay_que_liberar_coach` decide si toca liberar (función
  pura, con tests) y `liberar_coach` ejecuta.
- `cerrar_vigencia` pone `vigente_hasta = hoy - 1 día` sin violar el CHECK
  (`vigente_hasta >= vigente_desde`): si la vigencia arrancó hoy, cierra hoy mismo.
- Se limpian `coach_id`, `asignacion_origen`, `asignada_por` y `asignada_en` de las clases
  con `fecha >= hoy` (hora de Chile) que eran suyas. **Las clases pasadas no se tocan**
  (historia del box).
- Al cambiar la disciplina de una plantilla **no** se reescribe la disciplina de las
  clases ya generadas (puede haber alumnos reservados): la disciplina nueva aplica a lo
  que se genere de ahora en adelante; esas clases quedan 🔴 sin coach.
- Todo queda en `auditoria`: `coach_liberado` en el detalle del usuario y
  `cambiar_disciplina_horario` en el horario.


