# LOG_AISLAMIENTO_TESTS - Arreglo de tests admin

## Fecha: 17/07/2026

## Problema original

Los tests del panel admin (`test_panel_admin.py`) compartían el alumno id=999
con los tests de alumno y coach. El test_a03 (aprobar solicitud) creaba una
nueva suscripcion a traves del endpoint PUT /solicitudes/{id}/aprobar, lo que
dejaba al alumno 999 con 2 suscripciones activas. Esto causaba que GET
/membresia-activa devolviera la suscripcion equivocada y test_07 fallara.

Ademas, test_a07 usaba params= (query params) en vez de data= (form-data) para
POST /productos, que espera Form(...) args.

## Cambios realizados

### 1. run_setup_test_db.py
- Agregado usuario 1010 ("Alumno Admin Test") dedicado para tests admin

### 2. test_panel_admin.py
- Creado ALUMNO_ADMIN_ID = 1010 en vez de usar ALUMNO_ID = 999
- test_a02: usa alumno 1010 para crear solicitud
- test_a08/a09: usa alumno 1010 para pedidos
- test_a07: cambiado params= a data= (form-data) para POST /productos

## Resultados

### Antes
- 36 tests, 31 passed, 5 failed
- a07, a08, a09, test_07, c07 = FAILED

### Despues
- 37 tests (1 nuevo), 37/37 PASSED
- Todos los tests pasan consistentemente