# LOG DE ADMINISTRACIÓN Y PENDIENTES

## 2026-07-28 16:37 — LIMPIEZA MASIVA DE SCRIPTS SUELTOS + MIGRACIONES INTEGRADAS

### LIMPIEZA REALIZADA
**1. Backup CSV movido a lugar seguro:**
- `backup_clases_prod_20260723_144052.csv` → `proyecto-crossfit/backups/` (fuera del código activo)

**2. Migraciones integradas en sync_test_from_prod.py (PASO 1):**
- Las 4 migraciones de `_apply_migrations_post_sync.py` ahora corren automáticamente al final de `sync_test_from_prod.py`
- Un solo comando: `python backend/scripts/sync_test_from_prod.py`
- Verificado con SQL (2026-07-28 16:34):
  - 16 planes: 6 con `es_estudiante=True` (Girly, Aesthetic, Influencer, Brocoli, Diddy Kong, Donkey Kong)
  - 6 disciplinas: crossfit/Gap/Lev. Olimpico/Clase Intensiva=requiere_coach=True, Musculacion/Open Box=False
  - coach_disciplinas table existe (0 rows de PROD)
  - cobertura_emergencia table existe
- `_apply_migrations_post_sync.py` eliminado

**3. 19 scripts descartables eliminados (PASO 2):**
- Scripts de diagnóstico de secuencia (6): `_diag.py`, `_diag_seq.py`, `_quick_diag_seq.py`, `_diag_final.py`, `_diagnostico_secuencias.py`, `_verificar_estado.py`
- Script de fix de secuencia (1): `_fix_seq.py`
- Scripts de duplicados (6): `_diagnostico_duplicados.py`, `_diagnostico_duplicados_prod.py`, `_limpiar_duplicados.py`, `_limpiar_duplicados_prod.py`, `_backup_prod_clases.py`, `_check_dupes.py`
- Scripts de fix puntual (3): `_fix_es_estudiante.py`, `_fix_cobertura.py`, `_apply_migrations_post_sync.py`
- Scripts temporales (3): `check_after_put.py`, `test_fix_vivo.py`, `start_server_final.py`

**4. Archivos útiles permanentes confirmados (PASO 3):**
- `iniciar_servidor.py` — ⚠️ **OBSOLETO como canónico (19/08/2026)**: fuerza `ENVIRONMENT=test` → carga `.env.test` (BD de TEST con credenciales rotadas). Usar `start_server.py` (usa `.env`) o `uvicorn app.main:app`.
- `iniciar_servidor.bat` — entry point, fix sin --reload

### ESTADO ACTUAL (git status)
```
modified:   LOG_ADMIN_PENDIENTES.md
deleted:    backend/check_after_put.py
modified:   backend/iniciar_servidor.bat
modified:   backend/scripts/sync_test_from_prod.py
deleted:    backend/test_fix_vivo.py
untracked:  backend/iniciar_servidor.py
untracked:  backups/
```

### ✅ RUN_TESTS COMPLETO — 2026-07-28 16:49 (212.09s)
```
46 passed, 9 warnings in 212.09s (0:03:32)
ALL TESTS PASSED
```
La limpieza no rompió nada. Los warnings son solo de `datetime.utcnow()` deprecado (pre-existente).

### LO QUE QUEDA PENDIENTE
- ⬜ **TAREA 2**: Auto-insert de ingreso al crear suscripción (modificar endpoint POST suscripciones)
- ⬜ **TAREA 3**: Frontend modal "+ Registrar movimiento" en /admin/reportes
- ⬜ **Verificación visual DOM** /admin/reportes en navegador
- ⬜ **Decidir si comitear esta limpieza** (sin push a origin)

## 2026-07-28 18:44 — TAREA 1: Test E2E End-to-End + TAREA 2: Load Test 100 alumnos

### TAREA 1 — Test de Integración End-to-End (3 roles)
**Archivo:** `backend/tests/test_end_to_end.py`

**8 pasos cubiertos con evidencia (SQL + HTTP):**
1. Admin crea alumno → verifica password_hash en DB (no vacío)
2. Alumno login JWT + elige plan (crea solicitud pending, verifica en SQL)
3. Alumno sube voucher (JPEG simulado vía API upload + SQL update)
4. Admin aprueba solicitud → verifica suscripción activa en DB
5. Alumno agenda clase CrossFit → verifica cupo descontado + crédito -1
6. Coach genera WOD (con JWT) + asigna a clase → verifica wod_id en SQL
7. Alumno consulta WOD de hoy → verifica contenido WOD y crédito
8. Alumno registra RM (80kg → 85kg) + consulta evolución → verifica pesos

**Limpieza:** Alumno dedicado (id=8888) se elimina al inicio y final.

### TAREA 2 — Simulación de Carga (100 alumnos, 1 mes)
**Branch desechable:** `loadtest-crossfit-100` (hijo de production, auto-delete 1 día)
**Script:** `backend/_loadtest_100_alumnos.py` (NO toca TEST ni PRODUCCIÓN)

| Operación | Tiempo |
|---|---|
| Insertar 100 alumnos + suscripciones | 11.59s |
| Generar 208 clases (30 días, 8 horarios) | 12.47s |
| Generar 985 reservas (total) | 127.52s |
| Promedio por reserva | 129.5ms |
| **Consultas (contra branch carga):** | |
| Supervisión (tarjetas disciplina) | 0.121s ✅ |
| Reporte completo alumnos | 0.058s ✅ |
| Ocupación clases (30 días) | 0.119s ✅ |
| Dashboard stats | 0.261s ✅ |

**Diagnóstico:** Todas las consultas <0.3s, no hay problemas de índices.
⚠️ Generación de datos lenta por inserts individuales (no batch). Mejorable con `executemany()`.

### ✅ RUN_TESTS COMPLETO (con E2E) — 2026-07-28 ~18:45
```
55 passed (incluyendo 8 tests E2E nuevos), 9 warnings
ALL TESTS PASSED
```

### LO QUE QUEDA PENDIENTE
- ⬜ **Verificar visual DOM** /admin/reportes en navegador
- ⬜ **Decidir si comitear** (sin push a origin)
- ⬜ Eliminar `_loadtest_100_alumnos.py` tras revisión (script temporal)

### SIN COMMIT — esperando decisión del usuario

---

## 2026-09-28 — /admin/alumnos: paginación sobre TODO el padrón, verificada en TEST (415 alumnos del seed)

### Hallazgo de auditoría revisado
"`/admin/alumnos` trunca a 100 sin avisar". Estado REAL al abrir la tarea:

- El endpoint **ya** tenía paginación (`limit`/`skip` + header `X-Total-Count`) y
  `buscar` server-side desde el commit `0043232` (23/09), y la pantalla **ya** usaba
  ambos (25 por página, pie "Mostrando A-B de N", `data-testid="rango-alumnos"`,
  `expose_headers` en CORS). Lo del commit `17f0145` (aviso "Mostrando 100 de N") quedó
  obsoleto con ese cambio.
- Lo que faltaba de verdad: **(a)** tests del contrato, **(b)** el pie quedaba
  desincronizado al eliminar (filtro local en vez de refetch), **(c)** sin clamp si la
  página pedida quedaba fuera de rango, **(d)** `skip` negativo devolvía **500** de
  Postgres (`OFFSET must not be negative`), **(e)** `buscar="   "` armaba `%%`.

### Consumidores del endpoint (verificados antes de tocar nada)
`frontend/src/pages/admin/Alumnos.jsx` (paginado), `Coaches.jsx` y `ModalClase.jsx`
(`?rol=coach` sin paginar), `backend/paso1.py`, `backend/test_nivel.py`,
`tests/test_panel_admin.py::test_a10_listar_usuarios_serializable`.
Todos dependen de: (1) la respuesta es una **lista**, (2) `limit` default **100**, (3)
`rol`/`activo`/`estado` siguen filtrando. El contrato no cambió.

### Cambios
- `backend/app/api/v1/usuarios.py`: `skip` con `ge=0` (422 en vez de 500); `buscar`
  vacío o solo espacios se ignora; docstring con el contrato completo.
- `frontend/src/pages/admin/Alumnos.jsx`: clamp al último tramo válido si la página
  pedida ya no existe; refetch tras eliminar; selector "Por página" (25/50/100).
- `backend/tests/test_usuarios_paginacion.py` (**NUEVO**, 13 tests, solo GET).

### Medición en TEST (branch `ep-jolly-butterfly-b6ty2z89`, datos del seed: 415 alumnos)
API (`GET /api/v1/usuarios/`):
```
página 1 (limit=25&skip=0)  -> 25 filas · X-Total-Count=415 -> 17 páginas
                               pie: 'Mostrando 1-25 de 415 alumnos' · 'Página 1 de 17'
página 2 (skip=25)          -> 'Mostrando 26-50 de 415 alumnos' (el total no cambia)
última página (skip=400)    -> 15 filas -> 'Mostrando 401-415 de 415'
skip=440 (fuera de rango)   -> HTTP 200 · [] · X-Total-Count=415
skip=-1                     -> HTTP 422 (antes: 500 de Postgres)
buscar=demo.prod.anual.300@example.com  (vive en la página 17, id=1438)
                            -> HTTP 200 · 1 resultado · está en la lista: True
buscar=<fragmento en minúsculas> -> 15 resultados, objetivo presente (ILIKE)
buscar=zzz-no-existe-zzz    -> 0 -> pie 'Sin resultados'
CORS (Origin 5173)          -> access-control-expose-headers: X-Total-Count
?rol=coach (sin paginar)    -> lista · 3 filas · default limit=100 (compatibilidad)
```
UI real (Edge headless + CDP, `frontend/scripts/click-test.mjs`, `TEST_URL=/admin/alumnos`):
```
render inicial        -> 'Mostrando 1-25 de 415 alumnos'            (0 errores de consola)
click "Siguiente"     -> 'Mostrando 26-50 de 415 alumnos'
tipear el correo del alumno de la página 17 -> 'Mostrando 1-1 de 1 (búsqueda)' + fila visible
"Por página" = 50     -> 'Mostrando 1-50 de 415 alumnos'
```

### Tests
```
py -3.12 -m pytest tests/test_seed_anual_prod.py tests/test_mantenimiento_cloud.py tests/test_usuarios_paginacion.py -q
172 passed, 4 warnings in 93.33s        (159 previos + 13 nuevos)
```
⚠️ **NO** se corrió `run_tests.bat` / `_run_tests_orchestrator.py`: `run_setup_test_db.py`
hace `DROP SCHEMA public CASCADE` y borraría el seed de la demo en TEST. El API se levantó
a mano (`ENVIRONMENT=test`, `uvicorn app.main:app --port 8000`, verificado con
`/debug/db-url` → `is_safe: true`) y solo se corrieron tests de lectura.

