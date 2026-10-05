# Supervisión de Clases — modelo de datos y convenciones (backend)

Documento de referencia del módulo **Supervisión** (admin) y de la **asignación de
coaches** (panel del coach). Se escribe antes de tocar código (Tanda 1 / bloque B0)
para dejar por escrito dos cosas que ya causaron bugs y confusión:

1. hay **dos tablas "de horarios"** en la base y sólo una está viva;
2. la convención de `dia_semana` **no** es la de PostgreSQL.

> Estado de este documento: B0 de la Tanda 1 (backend). Los bloques siguientes agregan
> secciones al implementarse (B1: grilla por rango; B2: `clases.asignacion_origen` +
> `horarios_coach`; B3: asignación de emergencia del admin; B6: liberación).

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
