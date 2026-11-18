# Priorización — líneas de pago sin cobertura

**Fecha:** 2026-11-17
**Insumo:** `REPORTE_MUTATION_PAGOS_SIN_COBERTURA.md` (150 mutantes sin test:
`pagos.py` 107, `aprobacion_planes.py` 18, `suscripciones_mp.py` 25).
**Decisión:** no se escribe ningún test en esta tanda. Esta lista es para que
Jebbus y el equipo elijan qué cubrir primero.

## Antes de priorizar: hay “falsos huecos”

Una parte importante de los 150 son **literales de módulo** (constantes de
estado, umbrales, mapas) que sí se ejecutan al importar, pero `coverage` no les
asigna contexto de test. No son ramas de negocio sin probar: sus **usos** están
cubiertos por tests existentes. Ejemplos:

- `pagos.py:50-51`, `82-84`, `100`, `104` (conceptos/estados/umbrales),
- `aprobacion_planes.py:53-54` (`ORIGEN_*`),
- `suscripciones_mp.py:105-118`, `127-138` (mapas y resultados).

Recomendación técnica: excluir del conteo los nodos de nivel módulo o marcar
“importado por la suite” en `scripts/mutacion_pagos.py`. Mientras tanto, la
lista de abajo son las líneas de **comportamiento** que de verdad no tienen un
test que las ejecute.

## P0 — dinero / activación / idempotencia

| # | Línea | Por qué | Test que debería cubrirla |
|---|---|---|---|
| 1 | `pagos.py:748` | Retorno/alerta de `monto_no_coincide`: MP cobró otro monto y no se activa nada. La comparación `740` ya está cubierta/mutada; falta el retorno. | `test_pagos_mercadopago_estados.py` o `test_pago_mercadopago_descuento.py` |
| 2 | `aprobacion_planes.py:243-248` | Rama `rowcount == 0` del CAS: distingue `ya_procesada` de `no_encontrada`; es la defensa contra doble aprobación admin/webhook. | `test_plan_en_cola.py` |
| 3 | `aprobacion_planes.py:94` | `precio_lista()`: base del descuento y de la transacción; el fallback a `plan.precio_clp`/`0` no se ejecuta. | `test_descuento_solicitud_plan.py` |
| 4 | `pagos.py:500-524` | `_limpiar_cobro_fallido`: si MP no devuelve `init_point`, la solicitud y el pago deben quedar cerrados (no bloqueando al alumno). | `test_cancelar_pago.py` / `test_pago_mercadopago_descuento.py` |
| 5 | `pagos.py:753, 755, 794` | Retornos `duplicado` del webhook: la idempotencia ya está cubierta por CAS, pero nadie afirma el resultado que ve el llamador. | `test_mp_webhook_suscripciones.py` |

## P1 — reglas de negocio que mueven plata indirectamente

| # | Línea | Por qué | Test que debería cubrirla |
|---|---|---|---|
| 6 | `pagos.py:257` | `_marcar_beneficio_usado`: si no marca el beneficio, el mismo descuento se puede reutilizar. | `test_descuento_solicitud_plan.py` |
| 7 | `pagos.py:660` | `registrar_evento(... firma_valida=False)`: default de auditoría/seguridad del webhook. | `test_pagos_webhook_firma.py` |
| 8 | `pagos.py:709` | `_fecha_mp`: parseo de `date_approved`; una fecha mal parseada cambia `pagado_en`. | `test_pagos_mercadopago_estados.py` |
| 9 | `pagos.py:737` | Estado de MP desconocido: no debe tocar nada; falta el retorno explícito. | `test_pagos_mercadopago_estados.py` |
| 10 | `aprobacion_planes.py:333` | `descuento_referido["descuento_clp"] > 0`: conversión del referido al aprobar. | `test_descuento_solicitud_plan.py` |
| 11 | `aprobacion_planes.py:497-498` | Misma regla de referido en la rama “plan en cola”. | `test_plan_en_cola.py` |
| 12 | `pagos.py:1000-1001` | `estado_publico`: el flag `aplicado` de la pantalla de resultado; un error muestra “aprobado” sin plan aplicado. | `test_pagos_mercadopago_estados.py` |

## P2 — ramas defensivas o fuera del alcance de “membresía”

- **Bazar** (`pagos.py:555-625`, `1172-1181` stock, variantes, expiración):
  es dinero, pero pertenece a la pasada de Bazar/pedidos, no a esta tanda.
- Códigos HTTP de error (`pagos.py:327/339/385/556/625`, `suscripciones_mp.py:501`):
  contrato de API, bajo riesgo; cubrirlos sólo si se toca el endpoint.
- `pagos.py:290` (`_avisar_pedido_online`) y `pagos.py:849/857/863/872`
  (Bazar en `_aplicar_beneficio`): ramas de notificación/estado del Bazar.
- Constantes de módulo listadas arriba: **no** son prioridad real.

## Orden sugerido de trabajo

1. **P0 #2, #3 y #4** (activación/idempotencia + precio + limpieza): son los
   que pueden terminar en un plan mal activado o un alumno bloqueado.
2. **P0 #1, #5** (resultado del webhook): tests de contrato, baratos.
3. **P1 #6, #10, #11** (descuentos/referidos): impactan la caja.
4. **P1 #7, #8, #9, #12** (auditoría/fecha/estado): defensivos, se pueden
   agrupar en un solo test parametrizado.
5. Bazar: pasada aparte.
