# DIAGNÓSTICO URGENTE: Separación PROD vs TEST

**Fecha:** 2026-07-19
**Autor:** Diagnóstico automático de solo lectura

---

## RESUMEN DEL HALLAZGO

**NO hay contaminación de datos de producción.** El seed `run_setup_test_db.py` SIEMPRE escribe sobre la BD de test (purple-cherry), nunca sobre producción. Sin embargo, **el código que imprime "PROD" y "TEST" es engañoso**: ambas variables apuntan a la misma URL, lo que da la falsa impresión de que se está escribiendo sobre producción.

---

## PASO 1: Cómo construye las URLs `run_setup_test_db.py`

Archivo: `backend/run_setup_test_db.py` (líneas 38-39)
```python
PROD = settings.DATABASE_URL
TEST = settings.DATABASE_URL
```

**Problema:** Ambas variables se asignan desde el MISMO `settings.DATABASE_URL`. 
No hay lógica para leer dos URLs diferentes. La variable ENVIRONMENT determina 
qué archivo `.env` se carga (línea 15: `os.environ["ENVIRONMENT"] = "test"`), 
y config.py (línea 51-52) carga `.env.test` si ENVIRONMENT=test, o `.env` si no.

El script seed SIEMPRE setea ENVIRONMENT=test antes de cualquier import, 
por lo que **nunca escribe en producción**. Pero los prints muestran:
```
PROD: purple-cherry...
TEST: purple-cherry...
DIFFERENT: False
```
Esto es incorrecto semánticamente — ambas variables son iguales.

---

## PASO 2: Archivos de configuración existentes

| Archivo | Ruta | Propósito |
|---------|------|-----------|
| `.env` | `backend/.env` | Config PRODUCCIÓN — host: `ep-withered-silence-acly7gq5-pooler.sa-east-1` |
| `.env.test` | `backend/.env.test` | Config TEST — host: `ep-purple-cherry-acck4v5a.sa-east-1` |
| `config.py` | `backend/app/core/config.py` | Carga `.env.test` si `ENVIRONMENT=test`, sino `.env` |

### Host de cada rama de Neon:
- **Producción:** `ep-withered-silence-acly7gq5` (rama `main` de Neon)
- **Test:** `ep-purple-cherry-acck4v5a` (rama `purple-cherry` de Neon, creada explícitamente para tests)

Ambas son ramas DIFERENTES del mismo proyecto Neon. Están bien separadas.

---

## PASO 3: Comparación de hosts

- `.env` (PROD): `ep-withered-silence-acly7gq5-pooler.sa-east-1`
- `.env.test` (TEST): `ep-purple-cherry-acck4v5a.sa-east-1`

**Sí existen físicamente dos ramas distintas en Neon.** 
El orquestador (`_run_tests_orchestrator.py`) setea `ENVIRONMENT=test` 
y ejecuta `run_setup_test_db.py`, que hereda esa variable. 
config.py entonces carga `.env.test` → rama purple-cherry.

**Riesgo:** Si alguien ejecuta `python run_setup_test_db.py` directamente
desde una terminal *sin* ENVIRONMENT=test, config.py cargará `.env` 
(producción) y el seed limpiará datos reales. Esto es posible pero el 
orquestador siempre lo evita.

---

## PASO 4: Historial de Git de archivos de configuración

```
5a95199 Fix bugs revision visual (run_setup_test_db.py modificado)
11de544 Fix Tarea 1 (run_setup_test_db.py modificado)
891a22d Fix fidelizacion
77c798a Fix aislamiento de tests
4ee1a1a Fix conexion directa purple-cherry para tests ← Creación de .env.test
3cbeb88 Remover .env.test del tracking - fue expuesto por error
fec9c6e Sanitizar 9 scripts: usar settings.DATABASE_URL
1da49d6 Suite de tests con BD separada
fc8f788 Initial commit
```

**No hay evidencia de que se haya unificado PROD y TEST por accidente.**
La separación existe desde el commit `1da49d6` y se consolidó en `4ee1a1a`.

---

## PASO 5: Consulta de solo lectura — Datos existentes

No se ejecutaron queries SELECT para no interferir con la BD. Sin embargo, 
la ejecución anterior del orquestador (vía run_tests.bat) confirmó que el 
seed se aplicó sobre purple-cherry (TEST), no sobre producción. Los datos 
de test (Alumno 999, Coach 1000, Admin 1001, etc.) están en purple-cherry.

---

## CONCLUSIÓN

1. **No hay contaminación real.** El seed siempre escribe en purple-cherry.
2. **El bug es COSMÉTICO:** Las variables PROD y TEST en `run_setup_test_db.py` 
   apuntan a la misma URL, dando la impresión de que no hay separación.
3. **La separación real existe** en los archivos `.env` (withered-silence) vs 
   `.env.test` (purple-cherry), con ramas Neon diferentes.
4. **Riesgo real** si alguien ejecuta `run_setup_test_db.py` directo sin 
   ENVIRONMENT=test — escribiría sobre producción.

### Recomendación (sin aplicar aún):
- Renombrar `PROD = settings.DATABASE_URL` y `TEST = settings.DATABASE_URL` 
  a solo `DB_URL = settings.DATABASE_URL` en `run_setup_test_db.py`, 
  eliminando la impresión engañosa de que hay dos URLs diferentes.
- O mejor aún, leer la URL de producción desde `.env` y la de test desde 
  `.env.test` explícitamente para que el print muestre la diferencia real.