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
