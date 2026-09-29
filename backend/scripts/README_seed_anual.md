# 🌱 Seed anual de datos sintéticos para ML — `seed_anual_prod.py`

**300 alumnos · 12 meses de historia · PROD o TEST, con guards y reversión.**

Reemplaza al seed viejo (`seed_ml_data_prod.py`: 100 alumnos, 8 meses, sólo asistencias y
suscripciones). Este agrega lo que faltaba para que los modelos (`churn`, `forecast`,
`segmentación`) y los KPIs tengan de dónde aprender: **clases, reservas, créditos,
cancelaciones, perfiles de churn y 12 meses de pagos**.

Es para la **demo de la defensa (6/10/2026)**: PROD todavía no tiene alumnos reales.

| Archivo | Para qué |
| --- | --- |
| `scripts/seed_anual_prod.py` | genera e inserta el seed (idempotente, reversible) |
| `scripts/borrar_seed_anual.py` | borra SÓLO las filas del seed (y opcionalmente el viejo) |
| `scripts/README_seed_anual.md` | este documento |
| `tests/test_seed_anual_prod.py` | 27 tests unitarios **sin base** (invariantes, guards, reversión) |

---

## 1. Qué genera

Con la grilla REAL de PROD (la de `horarios`, 127 horarios: crossfit 07-22, Musculación y
Open Box con cupo 50, Gap lunes/miércoles/viernes, sábado sólo crossfit 10:00-12:00) y
`--alumnos 300`, el plan medido es:

| Tabla | Filas | Nota |
| --- | ---: | --- |
| `usuarios` | 300 | `demo.prod.anual.N@example.com`, password `MlAnual1234!` |
| `suscripciones` | ~2.0 k | una por mes y alumno, 1 vigente hoy por alumno (activo) |
| `transacciones_financieras` | ~2.0 k | 1 ingreso por suscripción (`DEMOPRODANUAL pago plan …`) |
| `clases` | ~5.5 k | SÓLO donde no había clase: las reales se REUSAN |
| `reservas` | ~23 k | vivas + faltazos (~10 %) + cancelaciones (~6 %) |
| `asistencias` | ~21 k | una por reserva asistida (`clase='WOD'`, con `clase_id`) |
| **TOTAL** | **~54 k** | **≈12 MB** a ~230 B/fila (el dump de PROD del 24/09 pesa 1.4 MB; el free tier de Neon es 512 MB) |

Reparto y forma:

- **Perfiles** (decisión 1): `FIEL` 55 % (165) · `REACTIVADO` 15 % (45) · `PRUEBA` 15 %
  (45) · `BAJA` 15 % (45).
- **Asistencia** (decisión 2): objetivo ≈100 por día hábil ponderado por `PESO_MES`, **16 el
  sábado** (el cupo del único horario real, decisión 1) y **0 el domingo**. Como las altas
  están repartidas en los 12 meses (igual que un box que crece), medido con la grilla real:
  **media 76/día hábil** (≈48/día en enero y ≈108/día en marzo; el día más cargado, 141),
  53 sábados con **media 15 y máximo 16**, y **8.3 % de ocupación** del año (Σ asistentes /
  Σ cupo), que es el ~10 % aceptado en la decisión 3.
- **Planes** (decisión 2): sólo de 16 créditos o ilimitados; los ilimitados van con
  `creditos_totales/disponibles = NULL`, igual que la app.
- **Hoy la última asistencia de todos es ≤ 40 días** (los `BAJA`, de 46 a 120 días): el
  label de churn queda inequívoco.

---

## 2. Guards (los 4 tienen que pasar)

1. **`--destino prod|test` es obligatorio.** De ahí sale `ENVIRONMENT` (`production`
   / `test`) y por lo tanto qué `.env` lee `app.core.config`.
2. **La URL tiene que ser la del destino** (ids leídos de `app.core.config`):
   - `prod` → `ep-nameless-sound-b6km6wyi` (host `nameless-sound`). Cualquier otro host
     aborta.
   - `test` → `ep-jolly-butterfly-b6ty2z89` (host `jolly-butterfly`) y **jamás** el de
     PROD (denylist primero: un copy/paste cruzado no habilita producción).
   - Si aparece `withered-silence` (el PROD **viejo**, endpoint retirado el 2026-09-24)
     aborta en los DOS destinos. El guard del seed viejo (`"withered-silence" in URL`) ya
     no puede pasar: por eso se reescribió.
   - Además se valida que `PROD_BRANCH_ID` siga conteniendo `nameless-sound`: si Neon
     recrea el endpoint, el script **aborta** en vez de escribir en una base que no es la
     que espera (y pide actualizar `config.py` + este script).
3. **Ventana de ejecución**: aborta si hoy es **día 1 o 15** (el mantenimiento escribe esos
   días) o si el mes en curso es **septiembre de 2026** (el run del 1/10 vencería todas las
   suscripciones de septiembre y cortaría por `MAX_VENCIDOS_PCT`). Ventana prevista:
   **2 a 5 de octubre de 2026**.
4. **Confirmación por teclado** con frase exacta (`SI QUIERO PROD` / `SI QUIERO TEST`), antes
   del dry-run y antes de cualquier escritura o borrado. Si ya hay datos del seed, pide una
   SEGUNDA confirmación (`RECICLAR`) porque los va a borrar y reinsertar.

---

## 3. Marcadores: por qué es idempotente y reversible

| Tabla | Marca | Nota |
| --- | --- | --- |
| `usuarios` | `correo LIKE 'demo.prod.anual.%@example.com'` | cae **dentro** de `PROD_PERMITIDOS` (`demo.prod.%@example.com`): A.1(c) lo ve como demo declarada y **no hay que tocar la variable de Render** |
| `transacciones_financieras` | `descripcion LIKE 'DEMOPRODANUAL%'` | cae dentro de `DEMOPROD%`, el LIKE del seed viejo |
| `clases` | `created_at = MARCA_TS` (`2026-10-02 04:17:03.123456+00`) | `clases` no tiene columna libre ni UNIQUE: el marcador es esa constante |

`clases` y `reservas` **no tienen UNIQUE** (sólo PK + índices planos), así que la
idempotencia no puede ser `ON CONFLICT`: es **borrar por marca + reinsertar en la MISMA
transacción**. Si el insert falla, el rollback deja la base exactamente como estaba
(incluido el seed anterior, si lo había).

---

## 4. Invariantes que sostienen el "0 cambios" del mantenimiento

`mantenimiento_cloud.py` con `DRY_RUN=1` tiene que dar los MISMOS hallazgos antes y
después del seed (salvo A.1(c), que es el conteo informativo de demo: sube en 300 por
diseño). Cada invariante ataca una detección o un paso concreto:

| # | Invariante | Qué evita |
| --- | --- | --- |
| 1 | label de churn (`sin susc. vigente` + `>45 días`) ⇔ perfil `BAJA`; los demás tienen plan vigente y asistencia de los últimos 40 días | que el modelo aprenda un label ambiguo y que los KPIs de riesgo mientan |
| 2 | `suscripciones.estado` sólo `activo`/`vencido`; `usuarios.estado` sólo `activo`/`baja` con `activo = (estado='activo')` | paso 2 y `transacciones_huerfanas.py` (pendientes), A.1(a) y A.1(b) |
| 3 | toda reserva viva de clase terminada tiene `asistencia_marcada_at`, y `asistio=true ⇒ marcada_at`; **nunca** `asistencia_via='cierre'` | paso 8 (cierre) y A.4(a)/(b) |
| 4 | `clases.asistentes_confirmados` = aforo base de la clase + nuestras reservas vivas (también en clases REALES) | paso 9 y A.2(a) |
| 5 | nunca más reservas vivas que `cupo_maximo` (el sábado queda exacto en 16) | A.2(c) |
| 6 | un alumno no repite clase ni hace dos clases el mismo día | A.2(b) |
| 7 | **A.3**: `creditos_totales - creditos_disponibles` = reservas vivas de la ventana + cancelaciones **tardías** (≥ 6 h antes ⇒ se devolvió ⇒ no consume); ilimitados con `creditos_* = NULL` | descuadre de créditos (A.3) |
| 8 | no se crean clases FUTURAS; en las del seed el `coach_id` es un coach activo de esa disciplina (round-robin) y NULL sólo si `requiere_coach=false` | A.5(a)/(b)/(c) |
| 9 | grilla real de `horarios`, clases reales reusadas, domingo sin clase | coherencia con la agenda y los KPIs de aforo |

Detalles que valen la pena:

- **Las cancelaciones** se escriben con márgenes holgados: `updated_at = inicio − 24 h`
  (temprana, el crédito vuelve) o `inicio + 2 h` (tardía, no vuelve). El corte de A.3 es
  `inicio − 6 h` **en horario de Chile**, así que la clasificación no depende del offset de
  DST (UTC-3/-4).
- **Las suscripciones se anclan a mediodía UTC** (`12:00:00+00`): así `fecha_inicio::date`
  y `fecha_expiracion::date` dan el mismo día en UTC y en `America/Santiago` (la sesión de
  `psql` del job usa TZ de Chile). Con `00:00:00+00` la ventana se correría un día.
- **Ventanas mensuales** `[1º del mes (o el día del alta), último día del mes]`: el plan
  vence el último día del mes, como en el box real, y no hay solapes (A.3 exige UNA
  suscripción vigente por alumno).
- **Reservas de los próximos 7 días** (decisión 5): sólo sobre **clases reales** ya
  generadas y sólo dentro de la ventana de la suscripción vigente (que es la que las cuenta
  en A.3, así `disponibles` las incluye y el descuadre sigue en 0). Si la app no generó
  clases futuras, el dry-run lo avisa y esa fase queda vacía.
- **`asistencia_marcada_por = NULL`** (decisión 7) con `asistencia_via='n8n'`: una vía real
  del sistema (el modelo documenta `coach|admin|batch|n8n`) y distinta de `'cierre'`, que
  es la que escribe el paso 8.
- **`tokens_gastados = 1`** siempre, igual que la app; A.3 lo ignora a propósito
  (documentado en el job).

---

## 5. Plan de ejecución (orden probado)

> Todo desde `backend/`. El día de la corrida tiene que **no** ser 1 ni 15.

### Paso 1 — Tests y dry-run en TEST

```powershell
py -3.12 -m pytest tests\test_seed_anual_prod.py -q      # 27 tests, sin base
$env:ENVIRONMENT="test"
python3.12 scripts\seed_anual_prod.py --destino test --dry-run
```

### Paso 2 — Baseline del mantenimiento (ANTES del seed) y seed en TEST

```powershell
# baseline: guardar la salida completa de los pasos 1-9 y de A.1-A.6 en DRY_RUN=1
$env:DRY_RUN="1"; python -m maintenance.mantenimiento_cloud   # (con MAINT_DB_URL de TEST)
python3.12 scripts\seed_anual_prod.py --destino test          # escribe en la rama de TEST
$env:DRY_RUN="1"; python -m maintenance.mantenimiento_cloud   # mismo set de hallazgos + A.1(c) +300
```
Con el log del después en la mano: **todos los conteos iguales** salvo A.1(c). Si algo
cambió, NO seguir: el problema está en el plan y se arregla en el script.

### Paso 3 — Backup de PROD

```powershell
python -m maintenance.backup_neon      # o el job de Render; el dump queda en backend/backups/
```

### Paso 4 — Seed en PROD (2 al 5 de octubre, día ≠ 1 ≠ 15)

```powershell
$env:ENVIRONMENT="production"
python3.12 scripts\seed_anual_prod.py --destino prod --dry-run   # leer TODO el reporte
python3.12 scripts\seed_anual_prod.py --destino prod             # pedirá confirmaciones
```
Al final imprime la verificación con el SQL del propio mantenimiento (paso 8, paso 9 y
**A.3**) acotada a las filas del seed: los tres tienen que dar **0**.

### Paso 5 — Reentrenar los modelos (con el seed adentro)

```
POST /ml/reentrenar                     (churn + forecast)
POST /kpis/populate/predictions         (predicciones de todos los alumnos)
POST /segmentacion/reentrenar
POST /kpis/populate/daily?fecha=…       (opcional: backfill de KPIs del mes)
POST /kpis/populate/monthly
```

### Paso 6 — Verificación final (Render → Cron Job → Trigger Run)

Con `DRY_RUN=1`: **0 cambios, 0 detecciones nuevas** (A.1(c) informativo sube en 300). Si
usás el camino de Render, el correo del run llega con la lista completa; si no hay nada
rojo, no llega ningún correo: mirar el log del run.

---

## 6. Cómo se lee el "0 cambios / 0 detecciones nuevas"

El mantenimiento se corre 2 veces con `DRY_RUN=1` y se comparan los dos reportes. Lo que
**tiene** que salir igual:

| Bloque | Antes del seed | Después del seed |
| --- | --- | --- |
| Pasos 1-9 (`cambios`) | lo que hubiera | **exactamente igual** |
| Detección A.1(a)/(b) | 0 (el CHECK de la 034) | 0 |
| A.1(c) usuarios demo | *n* | **n + 300** (es el único número que sube, y es informativo a propósito) |
| A.2(a)/(b)/(c) | 0 | 0 (invariantes 4, 5 y 6) |
| **A.3 descuadre de créditos** | 0 | **0** (invariante 7: es el que más fácil se rompe) |
| A.4(a) reservas sin marcar | lo que hubiera | sin filas del seed (invariante 3) |
| A.4(b) `asistio` sin marcar | 0 | 0 |
| A.5(a)/(b)/(c) clases futuras | ≥ 0 | igual (invariante 8: el seed no crea clases futuras) |
| A.6 `reservas.estado` raro | 0 | 0 (estado sólo `confirmada`/`cancelada`) |
| Integridad (RUT/correo/FK/fechas) | 0 | 0 |

Tres cosas que hacen ruido y **no** son fallas del seed:

1. **A.5(a)/(b) ya venían rojas/informativas en PROD** por las 25 clases futuras sin coach
   de Musculación/Open Box. El seed **no las agrega** (no crea clases futuras) pero tampoco
   las arregla: si querés el run verde, destildá `requiere_coach` en Disciplinas (migración
   018) o asigná esos coaches — es un tema aparte, documentado en `maintenance/README.md`.
2. **`fecha_expiracion` a fin de mes**: el 1/11 el paso 1 va a marcar vencidas las
   suscripciones de octubre (≈300 filas) ⇒ `MAX_VENCIDOS_PCT=80` **corta el run**. Por eso
   la reversión va **antes del 1/11**.
3. **`tokens_gastados`**: A.3 lo ignora a propósito; no lo "arregles" en el seed.

---

## 7. Reversión y limpieza

```powershell
# 1) ver qué borraría (no borra nada)
$env:ENVIRONMENT="production"
python3.12 scripts\borrar_seed_anual.py --destino prod --dry-run

# 2) borrar SÓLO el seed anual (pide 'BORRAR SEED PROD' y después 'BORRAR')
python3.12 scripts\borrar_seed_anual.py --destino prod

# 3) borrar también el seed VIEJO (demo.prod.N@example.com / DEMOPROD%)
python3.12 scripts\borrar_seed_anual.py --destino prod --limpiar-viejo
```

Qué hace exactamente (una sola transacción, `BEGIN` … `COMMIT`):

1. Localiza las filas por **marcadores** (§3), nunca por rango de fechas ni por `id >`:
   usuarios del seed + sus suscripciones + sus reservas + sus asistencias + sus
   transacciones, y las `clases` con `created_at = MARCA_TS`.
2. Borra en el orden de `pasos_borrado()` (hijos primero; verificado por un test):
   `asistencias` → `reservas` → `clases` → `transacciones` → `suscripciones` → `usuarios`
   (la cascada se lleva `predictions_churn`, `student_segments`, `kpi_daily`…).
3. **Recalcula el aforo de las clases REALES** que el seed infló:
   `asistentes_confirmados = <reservas vivas que quedan>`. Sin esto, el run siguiente
   tendría cientos de cambios del paso 9 en la cola.
4. Verifica: 0 filas del seed en las 6 tablas, 0 huérfanas y el **paso 9 en 0**.

`--limpiar-viejo` usa el LIKE ancho (`demo.prod.%@example.com` / `DEMOPROD%`) y por eso pide
una confirmación extra —después de `BORRAR SEED PROD`, la frase `TAMBIEN EL VIEJO`— porque
ese LIKE también matchea al seed nuevo.

⚠️ **El borrado NO deshace** el efecto del mantenimiento ya aplicado (si en el medio corrió
un `DRY_RUN=0`, pudo haber marcado vencidas las suscripciones seed): eso son filas reales de
`usuarios`/`suscripciones` que el script no revierte. Cómo mitigarlo: revertir con
`DRY_RUN=1` o, si ya se aplicó, restaurar el dump del paso 3.

### Borrar y volver a sembrar = lo mismo

El seed **siempre** borra el seed anterior y reinserta **en la misma transacción**
(`borrar_en_transaccion()` + inserts + `COMMIT`). Y el borrado que hace es el MISMO que el
del script de borrado. Corolario: es idempotente (2 corridas ⇒ 1 seed) y no hay estado
intermedio visible. Con `RECICLAR` se confirma que eso es lo que se quiere.

---

## 8. Supuestos y limitaciones (decididos, no bugs)

| # | Supuesto | Por qué |
| --- | --- | --- |
| 1 | Los 300 alumnos son **nuevos** (nadie del box real): 55 % fieles, 15 % reactivados, 15 % de prueba, 15 % de baja | no ensucia datos de personas reales y da las 4 clases de churn que los modelos tienen que separar |
| 2 | El alumno es una fila en `usuarios` con `email_verificado=true`, `activo=true` (salvo los BAJA) y password `MlAnual1234!` | permite entrar a la app con un alumno de demo si hace falta mostrarla en vivo |
| 3 | Ocupación ≈8 % (Σ asistentes / Σ cupo), con sábado exacto en 16 y 0 domingos | aceptado: los cupos reales de Musculación/Open Box (50) inflan el denominador; el día "típico" de crossfit queda lleno razonablemente |
| 4 | Las clases REALES que ya existen se **reusan** (no se duplican) y se les suma aforo | evita choques con la agenda real y con las clases futuras que genera el backend |
| 5 | Reservas vivas sólo en los **próximos 7 días** | la app tiene su propia ventana de reserva; sin esto habría reservas "imposibles" |
| 6 | `coach_id` round-robin entre coaches activos de la disciplina, y **NULL** en las disciplinas self-service (`requiere_coach=false`) | A.5(a) exige coach real; A.5 lo salta en self-service (migración 018) |
| 7 | `asistencia_marcada_por = NULL` y `asistencia_via='n8n'` | una vía real del sistema; `'cierre'` es exclusiva del paso 8 y A.4(b) exige la auditoría |
| 8 | No se crean `pagos`/`cobros` ni `solicitudes`: sólo `transacciones_financieras` de ingreso | es el mínimo que necesitan los KPIs; menos tablas tocadas = menos riesgo de huerfanitas |
| 9 | El seed **no** reentrena los modelos ni popula KPIs (paso 5 del plan) | reentrenar es una acción de la app (`POST /ml/reentrenar`) y no del script |

Y lo que no controla el plan (lo avisa el dry-run): cuántas clases futuras generó el
backend, si `horarios` cambió, si algún alumno del seed quedó con `asistencia` duplicada
por un cierre del mantenimiento en el medio.

---

## 9. Tests

```powershell
cd backend
py -3.12 -m pytest tests\test_seed_anual_prod.py -q      # 27 passed (sin base, sin red)
```

⚠️ Usar **`py -3.12`**: el `python` del PATH (3.13) no tiene pytest instalado (la misma
nota que en `maintenance/README.md`).

Cubren, sin tocar ninguna base:

- **Invariantes del plan** (`test_plan_cumple_todos_los_invariantes` + 12 tests de detalle:
  aforo, `asistencia_marcada_at`, reservas futuras, coach, estados, una sola suscripción
  vigente, label de churn ⇔ BAJA, sin huérfanas ni duplicados, una asistencia por reserva
  asistida, una transacción por suscripción, reparto por día, **créditos contra A.3** y
  cancelaciones contra el corte de **6 h**).
- **Determinismo**: mismo `SEED` + mismo insumo ⇒ plan idéntico (el seed es reproducible).
- **Guards**: URL por destino (incluido el rechazo de `withered-silence` y del host cruzado)
  y ventana de ejecución (día 1, 15 y 2026-09).
- **Pureza del módulo**: `test_el_seed_no_importa_la_app_al_importarse` — importar el seed
  no abre conexiones ni lee el `.env` (por eso se puede testear sin base).
- **Reversión**: marcadores coherentes entre seed y borrado, filtros por defecto vs
  `--limpiar-viejo`, orden de `pasos_borrado()` y que la reversión deje el aforo de las
  clases reales **como estaba**.
- **Estimación de filas**: `estimar_filas()` cuenta lo mismo que se inserta (los números de §1).

---

## 10. Qué NO hace (a propósito)

- **No toca `horarios`, `disciplinas`, `usuarios` reales, `coaches` ni la configuración.**
  Sólo inserta filas nuevas y actualiza `clases.asistentes_confirmados` de las clases reales
  que infló (y lo deja como estaba al borrar).
- **No corre migraciones, no cambia `alembic_version`.**
- **No hace backup ni reentrena**: el backup es el paso 3 (job de Render o
  `maintenance/backup_neon.py`) y el reentrenamiento es el paso 5 (endpoints de la app).
- **No se puede correr en cualquier día**: los guards de §2 lo impiden (1, 15, septiembre).
- **No escribe nada sin `--destino` + la frase de teclado**, ni siquiera en `--dry-run`.
