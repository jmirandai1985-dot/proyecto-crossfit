# Mutation testing — módulos de pago (primera pasada)

**Fecha:** 2026-11-17
**Rama de trabajo:** `main` local (sin commit)
**Base:** rama TEST de Neon `ep-crimson-tooth-akhx7q2s` (`ENVIRONMENT=test`)
**Alcance:** `backend/app/services/pagos.py` (308 mutantes),
`aprobacion_planes.py` (127), `suscripciones_mp.py` (153). Total **588**.
**Suite usada:** los tests que ya cubren esos módulos:
`test_pago_*`, `test_cancelar_pago`, `test_expirar_pendientes`,
`test_pago_iniciado_oculto`, `test_suscripcion_mp_alta`,
`test_suscripcion_mp_cola_integracion`, `test_mp_webhook_suscripciones`,
`test_mp_webhook_suscripciones_integracion`, `test_plan_en_cola`,
`test_pago_mercadopago_descuento`, `test_descuento_solicitud_plan`,
`test_pagos_mercadopago_estados`, `test_pagos_webhook_firma`,
`test_solicitudes_pendientes_voucher`. Línea base: **220 passed en 11m22s**.

## 1. Herramienta: por qué NO se usó `mutmut`

`mutmut` 3.x **exige `fork`**; su documentación dice que en Windows sólo corre
dentro de WSL. Este host es Windows nativo (el proyecto se prueba con
`py -3.12`), así que se instaló `coverage` + `pytest-cov` (ver
`backend/requirements-dev.txt`) y se agregó el equivalente
**`backend/scripts/mutacion_pagos.py`**:

* genera mutaciones con `ast` (comparaciones, `and`/`or`, `not`, enteros,
  booleanos y literales de estado del negocio);
* aplica UNA por vez, corre pytest y **restaura siempre** el archivo (backup
  `.mutbak` + escritura atómica, por si el proceso se corta);
* usa los contextos de `coverage --cov-context=test` para correr sólo los tests
  que ejecutan la línea mutada;
* escribe un JSON con el diff de cada mutante y los tests que cubren la línea.

Operadores incluidos: `== != < <= > >= is is-not in not-in`, `and/or`, quitar
`not`, `n -> n+1`, `True/False`, y literales de estado/concepto
(`iniciado`, `pending`, `aprobado`, `rechazado`, `membresia`, `bazar`, ...).
No se mutan docstrings, mensajes de `logger` ni strings de texto libre.

## 2. Resultado de lo EJECUTADO

| Bloque | Mutantes ejecutados | Muertos | Sobrevivientes | Timeouts |
|---|---:|---:|---:|---:|
| `pagos.py` con tests unitarios rápidos (`cancelar`, `expirar`, `iniciado`) | 105 | **105** | **0** | 0 |
| `aprobacion_planes.py` — muestra de alto riesgo (líneas 120, 146, 147, 234, 240) | 12 | **12** | **0** | 0 |
| `suscripciones_mp.py` — muestra (líneas 165, 167, 269, 293, 313, 359, 682, 688) | 12 | **12** | **0** | 0 |
| `pagos.py` — integración (líneas 740, 792, 801, 804: monto, CAS, reembolso) | 10 | **10** | **0** | 0 |
| **TOTAL** | **139** | **139** | **0** | **0** |

**Sobrevivientes en lo ejecutado: NINGUNO.** No hay diffs de sobrevivientes que
reportar en esta pasada. Los 139 mutantes ejecutados fueron detectados por la
suite existente (en su mayoría por los tests unitarios de `pagos.py`, que son
los que más rápido corren).

## 3. Lo que NO se ejecutó (y por qué)

La suite completa tarda **11m22s por corrida** contra Neon. Cada mutante es un
proceso pytest nuevo: el simple `import app.services.pagos` tarda ~13 s y un
test de integración ~26 s de arranque, más el test. Correr los 588 mutantes
completos contra Neon era ~6-8 horas; esta primera pasada se acotó así:

| Archivo | Total | Cubiertos por tests rápidos | Cobertura SÓLO de integración | Sin cobertura de ningún test |
|---|---:|---:|---:|---:|
| `pagos.py` | 308 | 105 | 96 | **107** |
| `aprobacion_planes.py` | 127 | 0 | 109 | **18** |
| `suscripciones_mp.py` | 153 | 0 | 128 | **25** |
| **TOTAL** | **588** | **105** | **333** | **150** |

* **333 mutantes** sólo los cubren tests de integración: se ejecutó una muestra
  de 34 (las líneas de mayor riesgo: validación de aprobación, CAS de
  `activar_plan`, cola, transiciones de suscripción, monto/CAS/reembolso de
  `aplicar_pago`). Los 299 restantes quedan **pendientes** para la segunda
  pasada.
* **150 mutantes no los ejecuta NINGÚN test** de la suite usada. No son
  "sobrevivientes" en el sentido de mutation testing (no se corrieron porque no
  hay test que llegue a esa línea); son el **hueco de cobertura real** y el
  insumo más valioso para decidir qué tests agregar. La lista completa está en

### Comando para la pasada completa (cuando haya tiempo/entorno)

Desde `backend/`, con el servidor de TEST detenido (el runner muta archivos):

```powershell
$env:ENVIRONMENT = 'test'
py -3.12 scripts/mutacion_pagos.py run `
  --tests tests/test_cancelar_pago.py tests/test_expirar_pendientes.py `
          tests/test_pago_iniciado_oculto.py tests/test_pagos_mercadopago_estados.py `
          tests/test_pagos_webhook_firma.py tests/test_suscripcion_mp_alta.py `
          tests/test_mp_webhook_suscripciones.py `
          tests/test_mp_webhook_suscripciones_integracion.py `
          tests/test_suscripcion_mp_cola_integracion.py tests/test_plan_en_cola.py `
          tests/test_pago_mercadopago_descuento.py `
          tests/test_solicitudes_pendientes_voucher.py `
          tests/test_descuento_solicitud_plan.py `
  --coverage-file _mut/.coverage `
  --json _mut/reporte_completo.json --markdown _mut/reporte_completo.md
```

Para regenerar el mapa de cobertura (una vez, ~11 min):

```powershell
$env:ENVIRONMENT = 'test'
$env:COVERAGE_FILE = '_mut/.coverage'
py -3.12 -m pytest <los mismos tests> `
  --cov=app.services.pagos --cov=app.services.aprobacion_planes `
  --cov=app.services.suscripciones_mp --cov-context=test --cov-report= -q
```

## 4. Lectura de los 150 mutantes sin cobertura

No se listan todos acá para no duplicar el archivo
`REPORTE_MUTATION_PAGOS_SIN_COBERTURA.md`; los grupos que más pesan:

* **Ramas de error/limpieza de membresía** dentro de `pagos.py`:
  `_limpiar_cobro_fallido` (si MP no devuelve `init_point`, el pago quedaría
  abierto), `_marcar_beneficio_usado` (descuento F2) y `_fecha_mp` (fecha de
  aprobación) no tienen test que las ejecute. Son candidatas directas a la
  próxima tanda.
* **Bazar** dentro de `pagos.py` (`crear_pago_bazar`, stock, variantes,
  `_limpiar_cobro_fallido`): ~40 mutantes sin test en esta suite. Está fuera del
  alcance de "membresía" de esta tanda, pero es dinero: la segunda pasada
  debería incluir `test_pedidos*`/`test_bazar*`.
* **Constantes de umbral** (`MINUTOS_MEMBRESIA=30`,
  `MINUTOS_GUARD_MEMBRESIA=5`, `MINUTOS_BAZAR=30`,
  `ESTADOS_PAGO_CANCELABLES`): los literales de módulo no los ejecuta ningún
  test de esta suite; sus *usos* sí están cubiertos (y fueron mutados en las
  líneas que los consumen).
* **Ramas de error/limpieza** de `suscripciones_mp` (`IntegrityError`,
  `_abrir_periodo` con plan inexistente, `_encolar_recurrente` cuando ya hay
  cola) y de `aprobacion_planes` (`PlanNoEncontrado`, correos, matrícula).

## 5. Limitaciones de esta pasada

* No es mutation testing exhaustivo: 139/588 ejecutados (24 %). El reporte es
  honesto sobre qué se ejecutó y qué no.
* La latencia de Neon hace inviable correr todo en una sesión; el runner ya
  selecciona por cobertura y usa `--noconftest` para los tests aislados, pero
  cada proceso paga el import de la app.
* Los tests de integración escriben en la rama TEST (es su diseño). La muestra
  ejecutada limpió sus datos con los mismos fixtures existentes; no se tocó
  PROD.

  `REPORTE_MUTATION_PAGOS_SIN_COBERTURA.md`.
