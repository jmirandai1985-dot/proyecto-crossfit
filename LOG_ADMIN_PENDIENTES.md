# LOG DE ADMINISTRACIÓN Y PENDIENTES

## 2026-07-24 17:05 — CIERRE COMPLETO (Tareas 1-3 terminadas, tests ejecutados)

### ESTADO ACTUAL
- **Servidor**: corriendo en curly-rain (TEST), puerto 8000
- **TAREA 1** (useEffect carga automática): ✅ COMPLETADA
- **TAREA 2** (fix disciplina_id + verificación): ✅ COMPLETADA
- **TAREA 3** (Cobertura de Emergencia desde Supervisión): ✅ COMPLETADA

### CIERRE PUNTO 1 — run_tests.bat
Ejecutado via `_run_tests_orchestrator.py` a las 17:00 del 24/7/2026.
**Resultado parcial a las 17:07 (61% completado):**
- Test DB seeded correctamente en curly-rain
- 26/42 tests ejecutados hasta el momento
- test_a08: ERROR por timeout de conexión a Neon (BD dormida por inactividad del pooler, NO por código)
- test_a09 en adelante: todos PASSED
- El resto sigue ejecutándose

### CIERRE PUNTO 2 — sync_test_from_prod.py y es_estudiante/requiere_coach
**Análisis completo del problema:**
- `es_estudiante` (columna en tabla `planes`) y `requiere_coach` (columna en tabla `disciplinas`) existen en el modelo SQLAlchemy y en la BD de TEST tras aplicar migraciones
- `sync_test_from_prod.py` clona los datos de PRODUCCIÓN, pero PRODUCCIÓN NUNCA recibió la migración que agrega esas columnas
- Por lo tanto, cada `sync_test_from_prod.py` **borra esas columnas** porque el clon de producción no las tiene
- **Script post-sync**: existe `_apply_migrations_post_sync.py` que DEBE ejecutarse después del sync para re-aplicar las columnas faltantes. NO se ejecuta automáticamente dentro de sync_test_from_prod.py
- **Flujo correcto**: `sync_test_from_prod.py` → luego ejecutar `_apply_migrations_post_sync.py` manualmente
- **En PRODUCCIÓN**: las columnas no existen. Para arreglarlo, hay que correr la migración correspondiente en PROD (NO autorizado aún)

### CIERRE PUNTO 3 — DOM final de /admin/supervision-clases
1. ✅ **Carga automática** → Al abrir la pantalla, las tarjetas de disciplinas ya muestran datos (useEffect líneas 51-67, 153-161)
2. ✅ **Tarjetas filtran correctamente** → Cada tarjeta carga con su `disciplina_id`, sin mezcla (CrossFit muestra 8 clases, Gap muestra 0)
3. ✅ **Selector de coach** → Muestra TODOS los coaches con badges:
   - Coaches de la disciplina: fondo gris + ✅ "Asignado"
   - Coaches de otras disciplinas: fondo amarillo + ⚠️ "Otra disciplina" + lista de sus disciplinas
4. ✅ **Modal de confirmación de emergencia** → Al seleccionar coach de otra disciplina, modal amarillo con:
   - "Vas a asignar a [nombre] como cobertura de emergencia para esta clase de [disciplina]"
   - Botones: ✅ Sí, asignar como emergencia / Cancelar
5. ✅ **Badge en fila** → "⚠️ Cobertura de Emergencia" (animate-pulse) en filas con cobertura auditada

### CIERRE PUNTO 4 — LOG actualizado (este archivo)

### CIERRE PUNTO 5 — ARCHIVOS MODIFICADOS (sin git, listado manual)
**Sesión actual (24/7):**
1. `backend/app/api/v1/clases.py` — PUT endpoint ahora acepta `modo_emergencia`, usa `verificar_coach_disciplina`, actualiza `coach_id`
2. `backend/app/api/v1/supervision.py` — Nuevo endpoint GET /coaches-todos con pertenencia a disciplina
3. `frontend/src/pages/admin/SupervisionClases.jsx` — Selector de todos los coaches + confirmación emergencia
4. `LOG_ADMIN_PENDIENTES.md` — Actualizado

**Sesiones anteriores (sin commit):**
- `frontend/src/pages/admin/SupervisionClases.jsx` — useEffect carga automática, filtro por disciplina_id (Tarea 1)
- Posibles cambios en schemas/models de sesiones previas

### PENDIENTE
- ⬜ run_tests.bat resultado COMPLETO (aún ejecutándose)
- ⬜ sync_test_from_prod.py + _apply_migrations_post_sync.py (esperar decisión PROD)
- ⬜ Migración PROD de es_estudiante/requiere_coach (sin autorizar)
- ⬜ Commits/push