# COMPARACIÓN: Modelos SQLAlchemy vs Schema SQL

> Generado el: 10/07/2026
> Fuente: `backend/app/models/` vs `sql/schema.sql`

---

## Diferencia entre `schema.sql` y `schema_clean.sql` (Paso 4)

| Característica | `schema.sql` | `schema_clean.sql` |
|---|---|---|
| `CREATE TABLE` | Sin `IF NOT EXISTS` | Con `IF NOT EXISTS` |
| Formato de comentarios | Saltos de línea dentro de sentencias SQL | Comentarios compactos antes de cada sentencia |
| Notas de diseño | Sí, extensas al final (política de cancelación, aforo, Open Box, generación de clases) | No incluye notas de diseño |
| Legibilidad | Comentarios mezclados con código SQL (difícil de leer) | Comentarios claros antes de cada bloque |
| Tablas definidas | 8 (tenants, usuarios, planes, suscripciones, disciplinas, horarios_base, clases, reservas) | 8 (mismas) |
| Vigente para usar | ❌ Formato desordenado con comentarios en medio de sentencias | ✅ Versión limpia y ejecutable |

**Recomendación:** Usar `schema_clean.sql` como esquema vigente. `schema.sql` es una versión preliminar más verbosa.

---

## Comparación: Modelos SQLAlchemy vs Tablas en Schema SQL

### Modelos que SÍ tienen tabla en `schema.sql` (coinciden)

| Modelo (archivo) | `__tablename__` / Tabla en BD | Estado |
|---|---|---|
| `Tenant` → `tenants.py` | `tenants` | ✅ Coincide |
| `Usuario` → `usuario.py` | `usuarios` | ✅ Coincide |
| `Plan` → `plan.py` | `planes` | ✅ Coincide |
| `Suscripcion` → `suscripcion.py` | `suscripciones` | ✅ Coincide |
| `Disciplina` → `disciplina.py` | `disciplinas` | ✅ Coincide |
| `HorarioBase` → `horario_base.py` | `horarios_base` | ✅ Coincide |
| `Clase` → `clase.py` | `clases` | ✅ Coincide |
| `Reserva` → `reserva.py` | `reservas` | ✅ Coincide |

*(8 de 20 modelos coinciden con el schema SQL)*

---

### Modelos que NO tienen tabla en `schema.sql` (sin schema)

| # | Modelo (archivo) | `__tablename__` | ¿Usado en producción? |
|---|---|---|---|
| 1 | `Asistencia` → `asistencia.py` | `asistencias` | ✅ Sí (fidelización) |
| 2 | `Auditoria` → `auditoria.py` | `auditoria` | ✅ Sí (endpoint auditoria) |
| 3 | `CoachDisciplina` → `coach_disciplina.py` | `coach_disciplinas` | ✅ Sí (endpoint coach_disciplinas) |
| 4 | `HistorialRM` → `historial_rm.py` | `historial_rm` | ✅ Sí (endpoint historial_rm) |
| 5 | `Movimiento` → `movimiento.py` | `movimientos` | ✅ Sí (catálogo de movimientos) |
| 6 | `Notificacion` → `notificacion.py` | `notificaciones` | ✅ Sí (endpoint notificaciones) |
| 7 | `Pedido` → `pedido.py` | `pedidos` | ✅ Sí (bazar) |
| 8 | `Producto` → `producto.py` | `productos` | ✅ Sí (bazar) |
| 9 | `RetencionAlumno` → `retencion.py` | `retencion_alumnos` | ✅ Sí (endpoint retención) |
| 10 | `SolicitudPlan` → `solicitud_plan.py` | `solicitudes_planes` | ✅ Sí (endpoint solicitudes) |
| 11 | `Wod` → `wod.py` | `wods` | ✅ Sí (endpoint wods) |
| 12 | `WodMovimiento` → `wod_movimiento.py` | `wods_movimientos` | ✅ Sí (WODs) |

*(12 modelos NO tienen su tabla definida en `schema.sql` ni en `schema_clean.sql`)*

---

### Resumen

| Métrica | Valor |
|---------|-------|
| Total modelos SQLAlchemy | **20** |
| Tablas definidas en schema SQL | **8** |
| Modelos con tabla en schema | **8** (40%) |
| Modelos SIN tabla en schema | **12** (60%) |

**Conclusión:** El archivo `sql/schema.sql` (y `schema_clean.sql`) están **incompletos**. Faltan 12 tablas que son usadas activamente por los endpoints pero no tienen su definición DDL en los archivos de schema. Estas tablas deben existir en la base de datos (probablemente creadas por SQLAlchemy con `Base.metadata.create_all()` o migraciones manuales), pero no están documentadas en los archivos SQL del proyecto.

Las tablas faltantes son:
1. `asistencias`
2. `auditoria`
3. `coach_disciplinas`
4. `historial_rm`
5. `movimientos`
6. `notificaciones`
7. `pedidos`
8. `productos`
9. `retencion_alumnos`
10. `solicitudes_planes`
11. `wods`
12. `wods_movimientos`

Se recomienda generar las sentencias `CREATE TABLE` para estas tablas a partir de los modelos SQLAlchemy y agregarlas a `schema_clean.sql`.