# Auditoría de salud backend / frontend (diagnóstico)

Fecha: **2026-10-29** · Entorno: **TEST** (`ep-crimson-tooth-akhx7q2s`) · Alcance:
backend (`backend/app`, `backend/maintenance`), frontend (`frontend/src`) y
automatizaciones (`n8n/`).

**Este documento se escribió como DIAGNÓSTICO.** Cada hallazgo trae archivo:línea,
evidencia y una recomendación; los fixes que ya se aplicaron están marcados abajo
en [Estado de los fixes](#estado-de-los-fixes-2026-10-29), el resto queda como
evidencia para decidir y promptear aparte.

> **Actualización (2026-10-29):** ya se aplicaron los fixes de **1.1**, **1.3**,
> **2.1**, **2.2** y **4.1** (sólo en TEST, sin deploy a PROD). El detalle de cada
> fix y la prueba que lo cubre están en
> [Estado de los fixes](#estado-de-los-fixes-2026-10-29). Los hallazgos **1.2**,
> **2.3-2.7** y **3.1** quedan abiertos a propósito: es deuda sin impacto medible
> hoy.

Método: lectura de código + búsquedas dirigidas + una heurística AST para
"consulta dentro de un `for`" (script descartable en `%TEMP%`) + conteo de
`SessionLocal()`/`db.close()` por archivo. Nada se ejecutó contra PROD.

Severidades: **Crítica** (fuga o corrupción de datos), **Alta** (impacto medible
en producción hoy), **Media** (riesgo real pero acotado), **Baja** (deuda).

---

## Resumen

| # | Severidad | Dimensión | Hallazgo | Dónde |
| --- | --- | --- | --- | --- |
| 1.1 | Media | Excepciones | Errores de BD (unique/FK/CHECK) llegan al cliente como 500 genérico en endpoints de escritura que no capturan `IntegrityError` | `horarios.py`, `disciplinas.py`, `planes.py`, `coach_disciplinas.py`, `clases.py`, `configuracion.py` |
| 1.2 | Baja | Excepciones | `detail=str(e)` devuelve el mensaje interno (validación/SQL) al cliente | `beneficios.py:409-413,486,508-510`, `fidelizacion_plantillas.py:141-163`, `wods.py:1377` |
| 1.3 | Media | CORS | Orígenes explícitos (bien), pero `allow_methods=["*"]`/`allow_headers=["*"]` con credenciales; la lista de orígenes no se valida al arrancar | `main.py:116-130`, `config.py:68,156` |
| 2.1 | Alta | N+1 | 1 consulta por reserva para resolver el nombre del alumno | `reservas.py:481-483` |
| 2.2 | Media | N+1 | 2 consultas por solicitud pendiente (plan + alumno) | `solicitudes_planes.py:238-241` |
| 2.3 | Media | N+1 | 1 consulta por fila de RM para resolver el movimiento | `historial_rm.py:727` |
| 2.4 | Baja | N+1 | 1 `COUNT` por coach en el KPI de retención | `retencion.py:171` |
| 2.5 | Baja | N+1 | 1 `SELECT` por horario al generar clases del día | `generar_clases.py:71` |
| 2.6 | Baja | N+1 | 2 consultas por sugerencia de plantilla | `fidelizacion_plantillas.py:598,608` |
| 2.7 | Baja | Queries | Hasta 6 `SELECT 1` por archivo estático servido (`lru_cache` mitiga) | `core/static_publico.py:61-73` |
| 3.1 | Baja | React | Toasts con `setTimeout` sin `clearTimeout`: `setState` tras el desmontaje | 12 archivos (lista en §3.1) |
| 4.1 | Media | Credenciales | Contraseñas literales en scripts de TEST y en 2 tests | `backend/scripts/*.py`, `backend/tests/*.py` (§4.1) |

Lo que **está bien** y conviene no romper (verificado en esta pasada):

* `get_db()` cierra SIEMPRE la sesión (`app/db/database.py:74-83`), y las
  sesiones propias (`email_service`, `scheduler`, `main`, `churn_service`,
  `maintenance/health_check`) cierran en `finally`.
* Handler global de excepciones + Sentry (`main.py:145-154`): ningún endpoint
  puede devolver un traceback al cliente.
* `pedidos.py::_con_nombres` resuelve nombres con 2 consultas `IN` (no N+1) y
  `reportes.py::_ocupacion_por_disciplina` es una sola CTE
  (`tests/test_reportes_sin_n1.py` fija el techo de consultas del endpoint).

---

## Estado de los fixes (2026-10-29)

Se arreglaron **1.1, 1.3, 2.1, 2.2 y 4.1** con pruebas de regresión. Nada se
desplegó a PROD: todo se validó contra TEST (`ep-crimson-tooth-akhx7q2s`).

| # | Estado | Fix aplicado | Cubierto por |
| --- | --- | --- | --- |
| 1.1 | ✅ Cerrado | `backend/app/utils/db_commit.py` (`commit_o_4xx` / `flush_o_4xx`): `rollback()` + SQLSTATE → **409** (`23505`) / **400** (FK, CHECK, NOT NULL, resto), detalle real al log con `exc_info=True` y **nunca** al cliente (el `str(IntegrityError)` trae SQL y parámetros). Aplicado a los 8 routers de escritura: `horarios`, `disciplinas`, `planes`, `coach_disciplinas`, `clases`, `finanzas`, `comprar_emergencia`, `configuracion`. | `backend/tests/test_integrity_error_4xx.py` (31): tabla de mapeo, rollback obligatorio, "el SQL queda en el log y no en la respuesta", `sqlstate` real contra TEST (fail-closed si no hay BD) y guarda AST que prohíbe `db.commit()`/`db.flush()` crudo en esos routers. |
| 1.2 | ⬜ Abierto | `detail=str(e)` sigue en `beneficios.py`, `fidelizacion_plantillas.py` y `wods.py`. | — |
| 1.3 | ✅ Cerrado | `config.validar_cors_origins` / `problemas_cors_origins`: barra final, `*`, espacios, esquema no `http(s)`, path y `localhost` en PROD se rechazan (PROD: `RuntimeError` al arrancar; TEST/dev: `WARNING`). `main.py` pasa `CORS_METHODS`/`CORS_HEADERS` explícitos (sin `*`) y conserva `expose_headers=["X-Total-Count"]`. | `backend/tests/test_cors_endurecido.py` (21) |
| 2.1-2.2 | ✅ Cerrado | un `outerjoin` por endpoint en vez de 1-2 consultas por fila. | `backend/tests/test_sin_n1_reservas_y_solicitudes.py` (techo de consultas contadas con `event.listen`) |
| 3.1 | ⬜ Abierto | toasts con `setTimeout` sin `clearTimeout`. | — |
| 4.1 | ✅ Cerrado | `TEST_SEED_PASSWORD` en `Settings` (**sin** default) + `backend/.env.test` (gitignored). Los scripts de seed la leen y **abortan** si falta; los tests que crean su propio usuario generan una clave aleatoria por corrida; k6 la recibe con `k6 run -e TEST_SEED_PASSWORD=...`. `.env.example` documenta la variable vacía. | Manual: el `grep` del anexo ya no devuelve ningún `PASSWORD = "..."`. |

Hallazgo lateral corregido de paso: `tests/test_end_to_end.py` usaba `uuid` sin
importarlo (la clave aleatoria de 4.1 lo necesita).

---

## 1. Excepciones y CORS

### 1.1 Errores de base que se convierten en 500 (Media) — ✅ resuelto

El handler global (`main.py:145-154`) atrapa todo y responde
`{"detail": "Error interno del servidor"}`. Para lo inesperado es lo correcto,
pero un `IntegrityError` **esperable** (nombre de disciplina repetido, plan con
nombre repetido, FK inválida, un `CHECK`) termina como 500 y dispara una alerta
de Sentry que no es una alerta.

Sólo tres routers traducen `IntegrityError` a un 4xx de negocio:

```
asistencia.py:717   (reserva duplicada -> 400)
reservas.py:304     (reserva duplicada -> 400)
referidos.py:919,1079
```

Endpoints de escritura con `db.commit()` y **cero** `except` en el archivo
(conteo por archivo, `app/api/v1/*.py`):

| Archivo | Rutas | `except` |
| --- | --- | --- |
| `horarios.py` | 5 | 0 |
| `disciplinas.py` | 5 | 0 |
| `planes.py` | 4 | 0 |
| `coach_disciplinas.py` | 3 | 0 |
| `comprar_emergencia.py` | 1 | 0 |
| `configuracion.py` | 6 | 0 |
| `finanzas.py` | 4 | 0 |

Ejemplo concreto: `POST /horarios` (`horarios.py:20-58`) crea el `HorarioBase` y
hace `db.commit()` sin `try`: una FK inválida o el CHECK nuevo
`ck_horarios_cupo_maximo_positivo` (migración 066) que se viole por otra vía
terminan en 500.

**Recomendación (no aplicada):** un helper único
`commit_o_409(db, mensaje)` que traduzca `IntegrityError`/`DBAPIError` a 409/400
con el patrón que ya usan `reservas.py` y `asistencia.py`, aplicado en los
routers de la tabla. No tocar los `except Exception` que loguean y responden 500
a propósito (`reportes.py:246-253,562-568`): ahí el mensaje genérico es la
decisión correcta.

### 1.2 `detail=str(e)` (Baja)

`beneficios.py:409-413,486,508-510`, `fidelizacion_plantillas.py:141-163` y
`wods.py:1377` devuelven el texto crudo de la excepción. En un `ValueError` de
negocio es útil; si alguna vez es un `DBAPIError`, filtra nombres de columnas y
fragmentos de SQL. **Recomendación:** loguear `exc_info=True` y devolver un texto
propio por caso (el patrón de `reportes.py`).

### 1.3 CORS (Media) — ✅ resuelto

`main.py:118-130`:

```python
allow_origins=_cors_origins          # CORS_ORIGINS + FRONTEND_URL (nunca "*")
allow_credentials=True
allow_methods=["*"]
allow_headers=["*"]
expose_headers=["X-Total-Count"]
```

* Está **bien** que los orígenes sean explícitos: con `allow_credentials=True`,
  un `"*"` habría sido crítico.
* El riesgo es de **configuración**: `CORS_ORIGINS` es una cadena que se parte
  por comas sin validar (`config.py:68,156`). Si en Render alguien agrega un
  comodín (`https://*.onrender.com`, un preview de Vercel) o un dominio de
  terceros, ese origen puede mandar `Authorization` al backend.
* Inconsistencia entre entornos: `.env.test` permite la IP de LAN
  (`http://192.168.100.241:5173`) y `.env` sólo localhost. En TEST es correcto;
  el punto es que **no hay un test** que fije los orígenes de PROD (hay tests
  para el modo email, no para CORS).


---

## 2. SQLAlchemy: fugas de sesión y N+1

### 2.1 N+1 en el roster de una clase (Alta) — ✅ resuelto

`reservas.py:474-493` (`GET /reservas/clase/{id}`): trae las reservas y después,
**por cada reserva**, consulta el usuario:

```python
for r in reservas:
    alumno = db.query(Usuario).filter(
        Usuario.id == r.alumno_id, Usuario.tenant_id == tenant_id).first()
```

Una clase de 20 alumnos = 21 viajes a Neon. Es el endpoint que abre el modal de
asistencia del coach, así que se llama seguido. **Recomendación:** el patrón `IN`
de `pedidos.py::_con_nombres` (1 consulta de reservas + 1 de usuarios). Test de
referencia: `tests/test_reportes_sin_n1.py`.

### 2.2 N+1 doble en solicitudes pendientes (Media) — ✅ resuelto

`solicitudes_planes.py:238-241`: por cada solicitud, una consulta al plan y otra
al alumno (2N+1). Es el listado que mira el admin para aprobar planes; con 30
pendientes son 61 consultas. Mismo fix (`IN` sobre `plan_id` y `alumno_id`).

### 2.3 N+1 en el progreso de RM (Media)

`historial_rm.py:727`: resuelve el `Movimiento` por nombre dentro del bucle de
detalles de RM (`obtener_nivel_fuerza_alumno`). **Recomendación:** precargar los
movimientos del tenant en un dict (una consulta).

### 2.4–2.6 N+1 acotados por N pequeño (Baja)

* `retencion.py:171`: `COUNT` por coach (~9 coaches = 9 consultas). Fix trivial
  con `GROUP BY coach_id`.
* `generar_clases.py:71`: un `SELECT` por horario al generar el día (~24). No es
  un problema de latencia hoy; se resuelve con un `IN (horario_ids)` + `fecha`
  y un set en memoria.
* `fidelizacion_plantillas.py:598,608`: plan + predicción por sugerencia.

### 2.7 Consultas por archivo estático (Baja)

`core/static_publico.py:61-73` (`_referenciado`) hace hasta 6 `SELECT 1` por
archivo servido, con `SessionLocal()` nueva y `lru_cache(maxsize=4096)`. La
tabla/columna van **fijas** (constantes de módulo), no hay inyección; el cache
hace que el costo se pague una vez por nombre. Se deja anotado, no urge.

### 2.8 Fugas de sesión: ninguna encontrada

`get_db()` cierra en `finally`. Las sesiones propias cierran en `finally` o al
final del bloque (verificado 1:1 en `email_service` 6/6, `scheduler` 5/5,
`main` 3/3, `churn_service` 1/1, `maintenance/health_check.py:35-44`). El riesgo
residual está en los scripts de `backend/maintenance/*` que abren
`SessionLocal()` sin `try` (p. ej. `transacciones_huerfanas.py:20`): si una
consulta lanza, la conexión se libera por GC y no por `close()`.
**Recomendación:** `with SessionLocal() as db:` en todos los scripts (el patrón
ya existe en `tests/test_notificaciones_enviadas_n1.py:73`).

**Recomendación:** validar `CORS_ORIGINS` al arrancar (rechazar `*` y orígenes
sin esquema), fijar `allow_methods` a la lista real (`GET,POST,PUT,PATCH,DELETE`)
y agregar un test que compare los orígenes de PROD contra una lista blanca
versionada.


---

## 3. `useEffect` sin cleanup (frontend)

Barrido de `setInterval`/`setTimeout`/`addEventListener` en `frontend/src`
(52 coincidencias). **La mayoría limpia bien**: `InicioMobile.jsx:189-190`,
`AdminTarjetaAlumnosPrueba.jsx:34-35`, `RankingAsistencia.jsx:303-304`,
`SupervisionClases.jsx:426-427`, `InicioMobileAdmin.jsx:442-456,527-531,547-560`,
`DashboardCoach.jsx:450-473`, `Layout.jsx:79-95`, `CampanaNotificaciones.jsx:175`,
`useInactividad.js:53-56`, `CarruselMarketing.jsx:351-364`,
`useDocumentoAutenticado.js:66-90` (revoca el object URL y aborta el fetch).

### 3.1 Toasts de un solo disparo sin `clearTimeout` (Baja)

`setTimeout(() => setToast(null), 2600)` y similares no se cancelan al
desmontar: `AsistenciaClases.jsx:532`, `PanelAlumnosPrueba.jsx:38`,
`RegistroAlumnoNuevo.jsx:42`, `Setup.jsx:56`, `PizarraRMs.jsx:142,217,236`,
`Pedidos.jsx:229,233,252,631`, `Dashboard.jsx` (admin) `276-329`,
`Fidelizacion.jsx:205,225`, `InicioMobileAdmin.jsx:565`,
`DashboardCoach.jsx:1449`, `Reportes.jsx:108`, `Alumnos.jsx:904`.

Impacto real: `setState` sobre un componente desmontado (React 18/19 ya no avisa
y no es fuga de memoria). **Recomendación:** un hook `useToastTemporal()` que
guarde el id y lo limpie en el `return`. No es urgente.

### 3.2 Listeners globales a propósito (no es un hallazgo)

`utils/recargaAutomatica.js:98-99` registra `vite:preloadError` y
`unhandledrejection` a nivel de módulo: se instalan UNA vez y deben sobrevivir a
la navegación. Correcto; se documenta para que nadie lo "arregle".

---

## 4. Credenciales hardcodeadas

### 4.1 Contraseñas literales en scripts/tests de TEST (Media) — ✅ resuelto

| Archivo:línea | Valor | Guarda de entorno |
| --- | --- | --- |
| `backend/scripts/crear_usuarios_test.py:40` | `PASSWORD = "Test1234!"` | fuerza `ENVIRONMENT=test` (17-19) |
| `backend/scripts/seed_usuarios_prueba.py:42` | `PASSWORD = "Test1234!"` | `ENVIRONMENT=test` + `is_test_db_url` (26-27, 57) |
| `backend/scripts/enviar_emails_test.py:42` | `password="TestPass123!"` | script manual |
| `backend/scripts/test_emails_data_uri.py:48` | `password="FinalPass123!"` | manual |
| `backend/scripts/test_emails_reenvio.py:51` | `password="FinalPass123!"` | `ENVIRONMENT='test'` (3) |
| `backend/scripts/test_todos_emails_final.py:48` | `password="FinalPass123!"` | manual |
| `backend/tests/test_end_to_end.py:16` | `E2E_PASSWORD = "TestPass123!"` | suite TEST |
| `backend/tests/test_login_no_retiene_conexion_bcrypt.py:44` | `PASSWORD = "Test1234!"` | suite TEST |

> **Cerrado (2026-10-29).** Ninguna de esas 8 filas queda con la clave literal, y
> se sumaron `k6-tests/_seed_load_test.py` y `k6-tests/test_500_logins.js` (misma
> clave, mismo problema). Ahora la clave sale de `settings.TEST_SEED_PASSWORD`
> (`backend/.env.test`, gitignored; `.env.example` muestra la variable vacía):
>
> * `crear_usuarios_test.py`, `seed_usuarios_prueba.py` y `_seed_load_test.py`
>   **abortan** con `sys.exit` si la variable falta, así que no se pueden crear
>   cuentas con una clave conocida por accidente.
> * `test_end_to_end.py` y `test_login_no_retiene_conexion_bcrypt.py` crean su propio
>   usuario, así que generan una clave aleatoria por corrida (`uuid4`): no necesitan
>   la variable y no repiten credencial entre corridas.
> * k6 la recibe por entorno: `k6 run -e TEST_SEED_PASSWORD=<clave> test_500_logins.js`
>   (el script falla con un mensaje claro si no se pasa).


Los scripts fuerzan TEST antes de importar `config`, así que **no pueden** crear
esos usuarios en PROD por accidente. El riesgo es de higiene: son contraseñas
conocidas, repetidas y versionadas; si alguna de esas cuentas de TEST se reusa
como cuenta real (o si alguien copia el hash a otra base), la clave ya es
pública. **Recomendación:** leer la clave de `TEST_SEED_PASSWORD`, generarla
aleatoria si falta (con `cambiar_password_al_login=True`) y borrar las variantes
`FinalPass123!` que ya no se usan.

> Nota de versionado (2026-10-29): `crear_usuarios_test.py`, `borrar_usuarios_prueba.py`,
> `seed_ml_data.py` y `seed_ml_data_prod.py` están en `.gitignore` (helpers LOCALES):
> no viajan en el repo, pero existen en las máquinas de desarrollo y en el server
> de TEST. `test_end_to_end.py` y `test_login_no_retiene_conexion_bcrypt.py` sí
> están versionados.

### 4.2 Lo que se buscó y NO se encontró

* URLs de Neon con usuario/contraseña dentro de código (`postgresql://...:...@`):
  ninguna en `backend/app`, `frontend/src` ni `n8n/`.
* Claves de R2 / JWT / N8N: todas por entorno (`config.py`), sin defaults.
* Tokens en `n8n/*.json`: no hay workflows versionados con credenciales; el
  README explica usar `{{ $credentials.n8nApiKey.value }}`.

---

## Anexo: comandos usados (reproducibles)

```powershell
# Heurística de "consulta dentro de un for" (lista de §2)
py -3.12 $env:TEMP\heur_n1.py

# ¿Quién abre sesión propia?
Get-ChildItem backend -Recurse -Include *.py |
  Select-String -Pattern 'SessionLocal\(\)|db.close\(\)'

# Listeners / timers del front
Get-ChildItem frontend\src -Recurse -Include *.jsx,*.js |
  Select-String -Pattern 'setInterval|setTimeout|addEventListener'

# Contraseñas literales
Get-ChildItem backend -Recurse -Include *.py | Select-String -Pattern 'PASSWORD = "|password="(Test|Final)'

# ¿Queda algún router de escritura con commit/flush crudo? (auditoría 1.1)
Select-String -Path backend\app\api\v1\*.py -Pattern 'db\.commit\(\)|db\.flush\(\)' |
  Select-String -Pattern 'horarios|disciplinas|planes|coach_disciplinas|clases|finanzas|comprar_emergencia|configuracion'
```

* CORS **no** usa `"*"` en orígenes y hay `SecurityHeadersMiddleware` +
  `TenantAuditMiddleware` (`main.py:132-139`).
* No hay secretos de JWT/BD/R2 hardcodeados: `JWT_SECRET_KEY` sale del entorno y
  `security.py` falla si falta (`config.py:48-55,189-193`); `N8N_API_KEY` se
  valida con `compare_digest` y se documenta cómo rotarla (`n8n/README.md:92-101`).

### Regresión de los fixes (necesita TEST y `backend/.env.test`)

```powershell
cd backend; $env:ENVIRONMENT='test'
py -3.12 -m pytest tests\test_integrity_error_4xx.py -q              # 31 (1.1)
py -3.12 -m pytest tests\test_cors_endurecido.py -q                  # 21 (1.3)
py -3.12 -m pytest tests\test_sin_n1_reservas_y_solicitudes.py -q    # 4  (2.1/2.2)
```
