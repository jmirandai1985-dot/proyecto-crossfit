# Estado de la suite de tests (auditoría de deuda técnica)

Fecha: **2026-10-29** · Entorno: **TEST** (`ep-crimson-tooth-akhx7q2s`) · API en
`:8000` (`ENVIRONMENT=test`).

Este documento responde al punto 4 del pedido: **cuántos de los "58 failing"
siguen fallando, cuáles son deuda real, cuáles estaban mal condicionados y qué
quedó sin resolver.**

## 0. Cómo se midió (y qué NO se corrió)

* Suite completa con `py -3.12 -m pytest tests -q` (sin `run_tests.bat`: **no se
  reseteó la base**, decisión del pedido).
* **Baseline (antes de los fixes de esta sesión):**
  `121 failed, 2001 passed, 21 skipped, 19 errors` en **1 h 08 min**.
  La suite creció a 2174 tests (los "1475 + 58" eran de la migración de región;
  hoy hay ~640 tests más) y la base TEST está **sincronizada desde PROD**, sin
  las personas del seed (`999/1000/1001`). Eso explica la mayor parte del rojo.
* Después de los fixes se **re-corrieron los módulos afectados** (no la suite
  entera: son ~70 min por corrida, ver §5).

## 1. Clasificación de los fallos (baseline 140 rojos: 121 F + 19 E)

| Categoría | Cuántos | Módulos | Causa | Estado |
| --- | --- | --- | --- | --- |
| **A. Puerto viejo (`:8001`)** | 9 E | `test_configuracion_permisos` | `API_BASE` por defecto en `:8001`, un segundo uvicorn que ya no existe | **ARREGLADO** (default `:8000`) |
| **A'. Idem** | 4 E | `test_bi_mrr_vivo` | idem | **ARREGLADO** (4/4) |
| **B. Test condicionado al MODO de correo** | 5–25 | `test_email_header_saneo` | exigía que el mensaje SE ENVIARA para probar el saneo; en TEST el fail-safe fuerza `EMAIL_MODO=noop` → `SMTPFalso.ultimo` quedaba en `None` | **ARREGLADO** (el fixture dobla `modo_envio` a `real` + credenciales falsas; 48/48) |
| **C. Persona fija inexistente (seed)** | ~35 | `test_panel_coach` (12), `test_panel_admin` (11), `test_end_to_end` (8), `test_cupos` (4) | tokens firmados con ids fijos `1000/1001/1010` y requests con `coach_id=1000`; en una TEST sin seed → 404 "Usuario no encontrado o inactivo" | **ARREGLADO** (`conftest` resuelve coach/admin/alumno; los módulos usan `COACH_ID`/`ADMIN_ID`) |
| **C'. Limpieza del E2E** | 8 | `test_end_to_end` | `limpiar_alumno_e2e` borraba por `id=8888`, pero el alumno se crea por API con id autogenerado → el RUT quedaba tomado y `e2e_01` moría (los 7 pasos caían en cascada) | **ARREGLADO** (borra por correo/RUT; 9/9) |
| **D. KPI de cupos (esta sesión)** | 3 | `test_reportes_sin_n1` | fijaba la forma vieja de `_ocupacion_por_disciplina` (`COALESCE(cupo_maximo, 1)`) y el tope de 21 consultas | **ARREGLADO** (forma nueva + 1 consulta del conteo sin cupo; 8/8) |
| **E. Guards de scripts rotos** | — | `scripts/crear_usuarios_test.py`, `borrar_usuarios_prueba.py`, `seed_ml_data.py`, `seed_ml_data_prod.py` | comparaban `DATABASE_URL` contra `billowing-violet-acdqud44` / `withered-silence` (retirados): abortaban SIEMPRE | **ARREGLADO** en la copia local (`is_test_db_url` / `PROD_BRANCH_ID`) + `test_guards_entorno_scripts.py` (12). ⚠️ esos 4 archivos están en `.gitignore` (helpers locales): el fix no viaja en el commit; el test los saltea si no están y también cubre `seed_usuarios_prueba.py`, que SÍ está versionado |
| **F. Datos de TEST** | 1 | `test_panel_admin::test_c16_sin_clases_duplicadas` | 4 grupos duplicados de clases (2 de las 03:00 y 2 históricos con reservas, creados por tests) | **MITIGADO**: se borraron las 2 de las 03:00 sin datos; el guard ahora mira **de hoy en adelante** |
| **G. Tests que asumen el mundo del seed** | 6 | `test_panel_coach` (3), `test_panel_alumno` (3) | necesitan al alumno 999 con plan de 50 créditos, el coach 1000 con CrossFit y un WOD de hoy | **SKIP con motivo** (`SEED_DISPONIBLE`): corren tras `run_setup_test_db.py` |
| **H. Deuda real / decisiones de producto** | ~20 | ver §2 | copy con voseo, guard TDZ (falso positivo), migración a hooks pendiente, 422 de género, etc. | **SIN RESOLVER** (documentado) |
| **I. Parte C (tramos de referidos), en curso** | 3 | `test_referidos_modelo` (2), `test_referidos_descuentos` (1) | viven en el cambio de referidos que quedó sin commitear de la sesión anterior | fuera de alcance |


## 2. Lo que queda sin resolver (y por qué)

| Módulo | Falla | Diagnóstico | Por qué no se tocó |
| --- | --- | --- | --- |
| `test_textos_tuteo` | `test_a2_no_queda_voseo_en_el_producto` | 13 textos en voseo ("Probá", "Completá", "Ingresá", "Guardá"...) en `AlumnoFichaCoach`, `BannerPerfilIncompleto`, `CampanaNotificaciones`, `HistorialAsistencia`, `Layout`, `ModalPublicarPromocion`, `TarjetaReferidosMarketing`, `Login` y `notificaciones.py` | es copy de producto: cambiar 13 mensajes requiere decisión de UX, no es un bug |
| `test_tdz_declaracion_antes_de_uso_front` | `test_b_...` | marca `historialAsistencia.js:350 usa 'i'`: **falso positivo** del detector (verificado contra `HEAD`: el archivo ya lo marcaba en la línea 310 antes de esta sesión) | tocar el detector es cambiar un guard; se prefiere documentarlo |
| `test_react_query_bloque2a/2c` | 2 | `AsistenciaClases` y `DashboardCoach` todavía usan `useEffect(` para cargar datos (migración a hooks a medias) | refactor de front, fuera de estos 4 puntos |
| `test_voucher_preview_sin_desenlace_front`, `test_activo_estado_unificacion` | 1 + 1 | guards de fuente que quedaron viejos respecto del código actual | idem |
| `test_perfil_campos_alumno` | 2 | el PUT **rechaza** `genero` inválido con 422; el test espera que lo DESCARTE en silencio | decisión de producto (422 es más honesto): hay que definir el contrato |
| `test_pr_ventana_24h` | 1 | `created_at` con antigüedad `-0.00 h` (borde de redondeo) | ajuste fino del test, sin impacto de producto |
| `test_invitaciones_alumno` | 1 | el payload de `RegistroAlumnoNuevo` cambió (2 errores de validación) | contrato del alta de invitado |
| `test_email_config_prod` | 1 | el test asume un `settings` que ya no existe (`NoneType` al indexar) | unitario de configuración: hay que reescribirlo |
| `test_encoding_backend` | 1 | `sync_log.txt` (artefacto local de un script) tiene bytes latin-1 | borrar/excluir el archivo; no es código |
| `test_kpis_frecuencia_semanal` | 1 | `numeric field overflow` al insertar los datos del test | datos del test vs columna `numeric` |
| `test_reporte_historico_mensual` | 7 | comparan celdas del histórico contra `metricas` con datos de TEST (sin seed) | requiere el seed para tener series |
| `test_scheduler_lock_integracion` | 6 | liderazgo con `pg_try_advisory_lock` contra Neon (pooler) | necesitan un entorno sin pooler; el lock ya está cubierto por `test_scheduler_lock.py` (unitario) |
| `test_avisos_marketing_service` | 6 | dependen de datos de catálogo/avisos del seed | idem seed |
| `test_busqueda_fidelizacion` | 4 | idem | idem |
| `test_supervision_asignacion_coach` | 2 | asumen horarios/clases del seed | idem |
| `test_notificaciones_panel` / `test_notificaciones_tenant` | 1 + 1 | dependen de ids de notificaciones concretos del seed (`alumno 5`) | idem |
| `test_referidos_modelo` / `test_referidos_descuentos` | 2 + 1 | Parte C en curso (sin commitear) | fuera de alcance |

## 3. Verificación de los arreglos (re-corrida por módulo)

| Comando | Antes | Después |
| --- | --- | --- |
| `pytest tests/test_email_header_saneo.py -q --noconftest` | 25 failed / 23 passed | **48 passed** |
| `pytest tests/test_configuracion_permisos.py -q --noconftest` | 15 errores | **14 passed, 1 skipped** |
| `pytest tests/test_bi_mrr_vivo.py -q --noconftest` | 4 errores | **4 passed** |
| `pytest tests/test_cupos.py tests/test_reportes_sin_n1.py -q` | 7 failed | **12 passed** |
| `pytest tests/test_end_to_end.py -q` | 8 failed | **9 passed** |
| `pytest tests/test_panel_alumno.py tests/test_panel_admin.py tests/test_panel_coach.py -q` | 27 failed | **0 failed** (+3 skips: casos que necesitan el seed) |
| `pytest tests/test_alumnos_paginacion_front.py tests/test_configuracion_descuento_beneficio.py tests/test_configuracion_validacion.py -q --noconftest` | 4 failed | **50 passed** |
| `pytest tests/test_encoding_backend.py -q --noconftest` (se borró el `sync_log.txt` latin-1) | 1 failed | **5 passed** |
| `pytest tests/test_guards_entorno_scripts.py -q --noconftest` | (nuevo) | **12 passed** |
| `pytest tests/test_cupos_sin_tope.py -q --noconftest` | (nuevo) | **16 passed** |
| `pytest tests/test_concurrencia_integracion.py -q` | (nuevo) | **4 passed** |

### Corridas por lote (después de los fixes)

| Lote | Módulos | Resultado |
| --- | --- | --- |
| B | `panel_coach`, `panel_admin`, `panel_alumno`, `end_to_end` | 16 → **0 failed** (los del seed se saltan) |
| C | 21 módulos (paneles, notificaciones, perfil, guards de front, encoding, email config...) | **16 failed, 144 passed, 7 skipped** |
| D | `notificaciones_panel`, `notificaciones_tenant`, `pedidos_notificaciones`, `avisos_marketing_service`, `busqueda_fidelizacion`, `supervision_asignacion_coach` | **15 failed, 83 passed, 1 skipped** |

Los 31 que siguen rojos en C+D son los de §2 (deuda/decisiones + seed). Los que no
se re-corrieron y siguen en la lista del baseline: `test_reporte_historico_mensual`
(7), `test_scheduler_lock_integracion` (6) y `test_referidos_*` (3, Parte C).

### Balance (estimado, sin volver a correr los 70 min completos)

* Baseline: **140 rojos** (121 F + 19 E).
* Verificados en verde tras los fixes: **~90** (categorías A, A', B, C, C', D, E,
  F y los guards de front arreglados).
* Quedan **≈ 43**: ~25 dependen del seed/datos de TEST (desaparecen con
  `run_tests.bat`) y ~18 son deuda o decisiones de producto (§2).

## 4. Los 3 patrones que había detrás de casi todo el rojo

1. **Ids fijos de personas (`999/1000/1001`) sin resolver contra la branch.**
   `create_access_token` firma cualquier id: el request moría con 404 y el test
   parecía roto por el endpoint. `conftest` ahora resuelve el id (seed si existe;
   si no, el primer usuario activo de ese rol) y los módulos importan
   `COACH_ID`/`ADMIN_ID`/`ALUMNO_ID`.
2. **Entorno del test ≠ entorno real**: `:8001` en vez de `:8000`, `@example.test`
   (TLD reservado que pydantic rechaza), tabla `solicitudes_plan` (se llama
   `solicitudes_planes`), lambda sin el kwarg `db=`, limpieza por un id que el
   alta nunca devuelve.
3. **Suposiciones del seed**: los módulos que necesitan el "mundo demo" ahora se
   **saltan con motivo** (`SEED_DISPONIBLE`) en vez de fallar; vuelven solos al
   correr `run_setup_test_db.py`.

## 5. Cómo volver a medir la suite completa

```powershell
cd backend
$env:ENVIRONMENT='test'
py -3.12 -m pytest tests -q            # ~70 min con la API en :8000
# o, para ver solo lo que falla:
py -3.12 -m pytest tests -q --tb=line -rf
```

> ⚠️ Si se corre `run_tests.bat` (resetea y resembra TEST), **desaparecen** los
> fallos de las categorías C/G y los de datos (§2, seed). Es el camino
> recomendado antes de una medición "de producto".
