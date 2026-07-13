# Auditoría del Panel del Coach

**Fecha:** 2026-07-13
**Propósito:** Revisar a fondo los endpoints del panel del coach sin modificar nada, documentando patrones riesgosos e inconsistencias frontend/backend.

---

## 1. `horarios.py` — Gestión de Horarios Base

### Endpoints:
- `POST /` — Crear horario base
- `GET /` — Listar horarios base (filtros: `dia_semana`, `activo`)
- `GET /{id}` — Obtener horario por ID
- `PUT /{id}` — Actualizar horario
- `DELETE /{id}` — Soft delete (marca `activo=False`)
- `POST /generar-clases-dia` — Generar clases desde horarios base para una fecha

### Patrones riesgosos:
- **Ninguno.** Código limpio, sin `.add_columns()`, sin N+1, sin desempaquetado de tuplas.
- Las validaciones de `tenant_id` son consistentes en todos los endpoints.

### Observaciones:
- El endpoint `POST /generar-clases-dia` usa query params `tenant_id` y `fecha` (no body JSON). Correcto.
- El `DELETE` es soft-delete (solo marca `activo=False`), no elimina registros.

### Inconsistencias frontend:
- `GenerarClases.jsx` llama a `POST /api/v1/horarios/generar-clases-dia?tenant_id=...&fecha=...`. La respuesta espera un diccionario con `creadas`, `omitidas`, `total_horarios`, `message`. El backend devuelve exactamente eso. ✅ **Consistente.**

---

## 2. `movimientos.py` — Gestión de Movimientos

### Endpoints:
- `POST /` — Crear movimiento
- `GET /{id}` — Obtener movimiento por ID
- `GET /` — Listar movimientos (filtro: `activo`)
- `PUT /{id}` — Actualizar movimiento
- `DELETE /{id}` — Soft delete (`activo=False`)

### Patrones riesgosos:
- **Ninguno.** Uso estándar de SQLAlchemy, sin `.add_columns()`, sin N+1.

### Observaciones:
- Faltan validaciones de nombre duplicado en `POST /` — si el frontend manda dos veces el mismo nombre, se crearían dos movimientos iguales.
- El campo `categoria` no tiene validación de valores permitidos (debería ser: fuerza, gimnastico, cardio, metabolico).
- Falta validación de `tenant_id` en `GET /{id}` — no usa `tenant_id`, cualquier tenant puede ver movimientos de otro si conoce el ID.

### Inconsistencias frontend:
- `Pizarra.jsx` usa `api.get('/api/v1/movimientos?tenant_id=...')` y espera `{ id, nombre, ...}`. 
  El backend devuelve `MovimientoResponse` (sin `categoria` en el listado simple). 
  Pero el frontend solo usa `id` y `nombre`, así que no hay break. ✅
- **⚠️ Potencial:** El `POST` de movimientos desde Pizarra.jsx (cuando el coach escribe "otro") envía `{ tenant_id, nombre, descripcion, activo }`. El endpoint `POST /api/v1/movimientos` espera un `MovimientoCreate` que incluye `tenant_id`, `nombre`, `descripcion`, `activo`. Coinciden. ✅

---

## 3. `disciplinas.py` — Gestión de Disciplinas

### Endpoints:
- `POST /` — Crear disciplina
- `GET /` — Listar disciplinas (filtro: `activo`)
- `GET /{id}` — Obtener disciplina por ID
- `PUT /{id}` — Actualizar disciplina
- `DELETE /{id}` — Soft delete (`activo=False`)

### Patrones riesgosos:
- **Ninguno.** Código limpio.

### Observaciones:
- El endpoint `GET /{id}` y `PUT /{id}` y `DELETE /{id}` **NO validan `tenant_id`** en el path. 
  - `GET /{disciplina_id}` busca solo por ID sin verificar tenant. Esto es **IDOR**: un coach del tenant A podría ver disciplinas del tenant B si adivina el ID.
  - `PUT /{disciplina_id}` tampoco verifica tenant.
  - `DELETE /{disciplina_id}` idem.
- Validación de duplicado por nombre en POST: ✅ correcto.

### Inconsistencias frontend:
- El frontend no tiene una página dedicada a disciplinas del coach. No hay consumo directo desde Pizarra.jsx ni GenerarClases.jsx.

---

## 4. `clases.py` — Gestión de Clases

### Endpoints:
- `GET /` — Listar clases (con auto-generación automática si faltan clases en los próximos 7 días)
- `GET /{id}` — Obtener clase por ID
- `POST /` — Crear clase manual
- `PUT /{id}` — Actualizar clase
- `DELETE /{id}` — Eliminar clase

### Patrones riesgosos:
- **⚠️ Auto-generación en capa de presentación:** El endpoint `GET /` tiene lógica de negocio (generar clases desde horarios base) que debería estar en un scheduler o endpoint separado. Esto significa que cada vez que el frontend pide clases (incluso en el dashboard del alumno), se ejecuta una lógica de generación. 
- **⚠️ SQL Raw:** Usa `text()` para consultas con COUNT(*) en vez de ORM. Si bien no es inyectable porque usa parámetros, rompe la consistencia del código.
- **⚠️ Falta de tenant_id en POST /:** El `POST /` recibe `tenant_id: int = Query(1)` con default hardcodeado a 1. Si alguien no envía `tenant_id`, se asigna al tenant 1 automáticamente.
- **⚠️ Falta de tenant_id en PUT /:** Similar, usa default `Query(1)`.
- **⚠️ Falta de validación en DELETE /:** No verifica si la clase tiene reservas activas antes de eliminar. Podría dejar reservas huérfanas.
- **⚠️ Auto-generación en GET / con `except Exception as e`:** Captura genérica que oculta errores.

### Observaciones:
- El `response_model=List[schemas.ClaseListItem]` en `GET /` no coincide exactamente con la respuesta manual que construye. Faltan campos como `horario_base_id`, `tenant_id`, `created_at`, `updated_at` que el schema `ClaseListItem` no incluye (no están en el modelo del schema). 
- La respuesta del `GET /` excluye `horario_base_id`, `tenant_id`, `created_at`, `updated_at` — pero el schema `ClaseListItem` tampoco los define, así que Pydantic no se queja. ✅ Ok.
- **⚠️ `GET /` usa LEFT JOIN para `coach_nombre` y `disciplina_nombre`** pero en el response dict construye manualmente. Si el JOIN falla y no hay coach, `coach_nombre` será None. Correcto.

### Inconsistencias frontend:
- `Pizarra.jsx` no usa `GET /api/v1/clases` directamente — usa `GET /api/v1/wods` para obtener los WODs. La Pizarra se basa en la grilla de horarios hardcodeada en el frontend (líneas 78-85), no en los horarios del backend. 
  - **⚠️ INCONSISTENCIA MAYOR:** La grilla de horarios en `Pizarra.jsx` (líneas 78-85) está **hardcodeada** con 12 horarios fijos (7:00-22:00) de lunes a viernes y 1 horario sábado (10:00-12:00). Esto no refleja los horarios reales configurados en la BD. Si un coach cambia los horarios en el backend (admin), la Pizarra no se actualiza.
  - El endpoint `GET /api/v1/horarios?tenant_id=...` existe y devuelve los horarios reales, pero **la Pizarra no lo consulta**.

---

## 5. `generar_clases.py` (servicio compartido)

### Endpoints (servicio, no endpoint HTTP):
- `generar_clases_para_fecha(db, tenant_id, fecha)` — Genera clases para una fecha específica
- `generar_clases_para_rango(db, tenant_id, fecha_desde, fecha_hasta)` — Genera clases para un rango

### Patrones riesgosos:
- **Ninguno.** ORM estándar, sin raw SQL, sin N+1 potencial (solo una query por horario base para verificar duplicado, pero hay pocos horarios).

### Observaciones:
- El servicio es reutilizado correctamente por: endpoint HTTP `POST /horarios/generar-clases-dia`, auto-generación en `GET /clases`, y scheduler diario.

---

## 6. `coach_disciplinas.py` — Asignación Coach-Disciplina

### Endpoints:
- `POST /` — Crear asignación coach-disciplina
- `GET /` — Listar asignaciones
- `GET /{id}` — Obtener asignación por ID
- `PUT /{id}` — Actualizar asignación
- `DELETE /{id}` — Soft delete (`activo=False`)

### Patrones riesgosos:
- **⚠️ IDOR:** `GET /{id}`, `PUT /{id}`, `DELETE /{id}` no validan `tenant_id`. Cualquier usuario podría acceder a relaciones de otros tenants.
- **⚠️ `GET /{id}`** usa query sin filtro de tenant. Lo mismo `PUT` y `DELETE`.

### Observaciones:
- El `POST` sí valida `tenant_id` correctamente.
- El `listar_coach_disciplinas` sí filtra por `tenant_id`.

### Inconsistencias frontend:
- No hay componente frontend que consuma `GET /api/v1/coach-disciplinas` directamente. Las relaciones coach-disciplina se usan internamente.

---

## 7. Resumen de Hallazgos

### Patrones riesgosos identificados:

| Archivo | Riesgo | Severidad |
|---------|--------|-----------|
| `clases.py` | Auto-generación en GET (lógica de negocio en capa de presentación) | 🔴 Alta |
| `clases.py` | `tenant_id` hardcodeado a 1 como default en Query params | 🔴 Alta |
| `clases.py` | SQL raw mezclado con ORM | 🟡 Media |
| `clases.py` | DELETE sin verificar reservas activas | 🟡 Media |
| `disciplinas.py` | IDOR en GET/PUT/DELETE (sin validación tenant_id) | 🟠 Media |
| `coach_disciplinas.py` | IDOR en GET/PUT/DELETE (sin validación tenant_id) | 🟠 Media |
| `movimientos.py` | GET/{id} sin validación tenant_id | 🟠 Media |
| `Pizarra.jsx` | Horarios hardcodeados en frontend (no consulta backend) | 🔴 Alta |

### Inconsistencias frontend/backend:

| Componente | Endpoint | Inconsistencia |
|------------|----------|----------------|
| `Pizarra.jsx` | `GET /api/v1/horarios` | No consulta horarios reales, usa HORARIOS_SEMANA hardcodeado |
| `Pizarra.jsx` | `GET /api/v1/clases` | No usa el endpoint de clases para la grilla |
| `Pizarra.jsx` | `POST /api/v1/wods` | Envía `{ ... fases: [] }` o `{ ... movimientos: [] }` — el backend debe aceptar ambos formatos. Verificar. |

### Decisiones de negocio pendientes (no implementar):
- La grilla de horarios de Pizarra debería obtenerse del backend, no estar hardcodeada.
- El DELETE de clases debería requerir confirmación o verificar reservas activas.
- Los tenant_id por query param con default=1 deberían eliminarse en favor de extraer tenant del token JWT.

---

*Documento generado el 2026-07-13 por auditoría automática. Sin modificar ningún archivo de código.*