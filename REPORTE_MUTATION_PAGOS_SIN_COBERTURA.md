# Mutantes sin cobertura — módulos de pago

**Fecha:** 2026-11-17
**Qué es:** cada línea es un mutante que **ningún test** de la suite de pagos
ejecutó (mapa de `coverage --cov-context=test` con los 13 archivos de test del
reporte principal). No son "sobrevivientes": no se corrieron porque no hay un
test que llegue a esa línea. Son los candidatos concretos a cubrir en la
próxima tanda.

Formato: `archivo:línea` · función · operador · cambio.


## app/services/pagos.py (107 sin cobertura)

- `app/services/pagos.py:50` · `<modulo>` · estado_str · `"membresia"` -> `"__MUTANTE__"`
- `app/services/pagos.py:51` · `<modulo>` · estado_str · `"bazar"` -> `"__MUTANTE__"`
- `app/services/pagos.py:82` · `<modulo>` · entero · `30` -> `31`
- `app/services/pagos.py:83` · `<modulo>` · entero · `30` -> `31`
- `app/services/pagos.py:84` · `<modulo>` · entero · `5` -> `6`
- `app/services/pagos.py:100` · `<modulo>` · estado_str · `"iniciado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:100` · `<modulo>` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/pagos.py:100` · `<modulo>` · estado_str · `"en_proceso"` -> `"__MUTANTE__"`
- `app/services/pagos.py:104` · `<modulo>` · estado_str · `"rechazado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:104` · `<modulo>` · estado_str · `"cancelado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:104` · `<modulo>` · estado_str · `"reembolsado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:555` · `crear_pago_bazar` · negacion · `not producto` -> `producto`
- `app/services/pagos.py:557` · `crear_pago_bazar` · negacion · `not producto.activo` -> `producto.activo`
- `app/services/pagos.py:581` · `crear_pago_bazar` · comparacion · `<=` -> `<`
- `app/services/pagos.py:660` · `registrar_evento` · booleano_const · `False` -> `True`
- `app/services/pagos.py:709` · `_fecha_mp` · booleano · `and` -> `or`
- `app/services/pagos.py:849` · `_aplicar_beneficio` · comparacion · `==` -> `!=`
- `app/services/pagos.py:120` · `__init__` · entero · `400` -> `401`
- `app/services/pagos.py:257` · `_marcar_beneficio_usado` · booleano · `and` -> `or`
- `app/services/pagos.py:500` · `_limpiar_cobro_fallido` · comparacion · `==` -> `!=`
- `app/services/pagos.py:562` · `crear_pago_bazar` · comparacion · `is` -> `is not`
- `app/services/pagos.py:568` · `crear_pago_bazar` · booleano · `or` -> `and`
- `app/services/pagos.py:570` · `crear_pago_bazar` · comparacion · `<` -> `<=`
- `app/services/pagos.py:574` · `crear_pago_bazar` · comparacion · `<` -> `<=`
- `app/services/pagos.py:581` · `crear_pago_bazar` · entero · `0` -> `1`
- `app/services/pagos.py:604` · `crear_pago_bazar` · comparacion · `is not` -> `is`
- `app/services/pagos.py:622` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:737` · `aplicar_pago` · estado_str · `"desconocido"` -> `"__MUTANTE__"`
- `app/services/pagos.py:748` · `aplicar_pago` · estado_str · `"monto_no_coincide"` -> `"__MUTANTE__"`
- `app/services/pagos.py:753` · `aplicar_pago` · estado_str · `"duplicado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:755` · `aplicar_pago` · estado_str · `"duplicado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:794` · `aplicar_pago` · estado_str · `"duplicado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:857` · `_aplicar_beneficio` · comparacion · `is` -> `is not`
- `app/services/pagos.py:863` · `_aplicar_beneficio` · comparacion · `==` -> `!=`
- `app/services/pagos.py:872` · `_aplicar_beneficio` · comparacion · `==` -> `!=`
- `app/services/pagos.py:961` · `procesar_notificacion` · estado_str · `"desconocido"` -> `"__MUTANTE__"`
- `app/services/pagos.py:964` · `procesar_notificacion` · estado_str · `"desconocido"` -> `"__MUTANTE__"`
- `app/services/pagos.py:257` · `_marcar_beneficio_usado` · comparacion · `is not` -> `is`
- `app/services/pagos.py:257` · `_marcar_beneficio_usado` · comparacion · `==` -> `!=`
- `app/services/pagos.py:327` · `crear_pago_membresia` · entero · `404` -> `405`
- `app/services/pagos.py:339` · `crear_pago_membresia` · entero · `400` -> `401`
- `app/services/pagos.py:385` · `crear_pago_membresia` · entero · `400` -> `401`
- `app/services/pagos.py:508` · `_limpiar_cobro_fallido` · booleano · `and` -> `or`
- `app/services/pagos.py:512` · `_limpiar_cobro_fallido` · comparacion · `==` -> `!=`
- `app/services/pagos.py:556` · `crear_pago_bazar` · entero · `404` -> `405`
- `app/services/pagos.py:558` · `crear_pago_bazar` · entero · `400` -> `401`
- `app/services/pagos.py:568` · `crear_pago_bazar` · comparacion · `is` -> `is not`
- `app/services/pagos.py:568` · `crear_pago_bazar` · negacion · `not variante.activo` -> `variante.activo`
- `app/services/pagos.py:570` · `crear_pago_bazar` · booleano · `or` -> `and`
- `app/services/pagos.py:574` · `crear_pago_bazar` · booleano · `or` -> `and`
- `app/services/pagos.py:582` · `crear_pago_bazar` · entero · `400` -> `401`
- `app/services/pagos.py:594` · `crear_pago_bazar` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/pagos.py:622` · `crear_pago_bazar` · entero · `0` -> `1`
- `app/services/pagos.py:764` · `aplicar_pago` · estado_str · `"duplicado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:863` · `_aplicar_beneficio` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/pagos.py:872` · `_aplicar_beneficio` · estado_str · `"rechazado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:998` · `estado_publico` · comparacion · `==` -> `!=`
- `app/services/pagos.py:1177` · `expirar_pendientes` · booleano · `and` -> `or`
- `app/services/pagos.py:477` · `_crear_preferencia` · entero · `503` -> `504`
- `app/services/pagos.py:508` · `_limpiar_cobro_fallido` · comparacion · `is not` -> `is`
- `app/services/pagos.py:508` · `_limpiar_cobro_fallido` · comparacion · `==` -> `!=`
- `app/services/pagos.py:554` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:554` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:563` · `crear_pago_bazar` · entero · `400` -> `401`
- `app/services/pagos.py:569` · `crear_pago_bazar` · entero · `400` -> `401`
- `app/services/pagos.py:570` · `crear_pago_bazar` · entero · `0` -> `1`
- `app/services/pagos.py:573` · `crear_pago_bazar` · entero · `400` -> `401`
- `app/services/pagos.py:574` · `crear_pago_bazar` · entero · `0` -> `1`
- `app/services/pagos.py:577` · `crear_pago_bazar` · entero · `400` -> `401`
- `app/services/pagos.py:590` · `crear_pago_bazar` · comparacion · `is not` -> `is`
- `app/services/pagos.py:591` · `crear_pago_bazar` · comparacion · `is not` -> `is`
- `app/services/pagos.py:625` · `crear_pago_bazar` · entero · `400` -> `401`
- `app/services/pagos.py:632` · `crear_pago_bazar` · estado_str · `"pedido"` -> `"__MUTANTE__"`
- `app/services/pagos.py:635` · `crear_pago_bazar` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/pagos.py:644` · `crear_pago_bazar` · entero · `503` -> `504`
- `app/services/pagos.py:1177` · `expirar_pendientes` · comparacion · `is not` -> `is`
- `app/services/pagos.py:1177` · `expirar_pendientes` · comparacion · `==` -> `!=`
- `app/services/pagos.py:1181` · `expirar_pendientes` · entero · `1` -> `2`
- `app/services/pagos.py:290` · `_avisar_pedido_online` · comparacion · `==` -> `!=`
- `app/services/pagos.py:508` · `_limpiar_cobro_fallido` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/pagos.py:524` · `_limpiar_cobro_fallido` · estado_str · `"cancelado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:565` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:566` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:702` · `buscar_pago` · comparacion · `==` -> `!=`
- `app/services/pagos.py:1001` · `estado_publico` · booleano · `and` -> `or`
- `app/services/pagos.py:1177` · `expirar_pendientes` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/pagos.py:1001` · `estado_publico` · comparacion · `in` -> `not in`
- `app/services/pagos.py:517` · `_limpiar_cobro_fallido` · estado_str · `"rejected"` -> `"__MUTANTE__"`
- `app/services/pagos.py:609` · `crear_pago_bazar` · comparacion · `>=` -> `>`
- `app/services/pagos.py:618` · `crear_pago_bazar` · comparacion · `>=` -> `>`
- `app/services/pagos.py:852` · `_aplicar_beneficio` · comparacion · `==` -> `!=`
- `app/services/pagos.py:853` · `_aplicar_beneficio` · comparacion · `==` -> `!=`
- `app/services/pagos.py:1000` · `estado_publico` · comparacion · `==` -> `!=`
- `app/services/pagos.py:503` · `_limpiar_cobro_fallido` · comparacion · `==` -> `!=`
- `app/services/pagos.py:504` · `_limpiar_cobro_fallido` · comparacion · `==` -> `!=`
- `app/services/pagos.py:522` · `_limpiar_cobro_fallido` · comparacion · `==` -> `!=`
- `app/services/pagos.py:523` · `_limpiar_cobro_fallido` · estado_str · `"iniciado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:523` · `_limpiar_cobro_fallido` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/pagos.py:1172` · `expirar_pendientes` · comparacion · `==` -> `!=`
- `app/services/pagos.py:1173` · `expirar_pendientes` · comparacion · `==` -> `!=`
- `app/services/pagos.py:608` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:617` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:515` · `_limpiar_cobro_fallido` · comparacion · `==` -> `!=`
- `app/services/pagos.py:516` · `_limpiar_cobro_fallido` · estado_str · `"iniciado"` -> `"__MUTANTE__"`
- `app/services/pagos.py:516` · `_limpiar_cobro_fallido` · estado_str · `"pending"` -> `"__MUTANTE__"`
- `app/services/pagos.py:607` · `crear_pago_bazar` · comparacion · `==` -> `!=`
- `app/services/pagos.py:616` · `crear_pago_bazar` · comparacion · `==` -> `!=`

## app/services/aprobacion_planes.py (18 sin cobertura)

- `app/services/aprobacion_planes.py:53` · `<modulo>` · estado_str · `"manual"` -> `"__MUTANTE__"`
- `app/services/aprobacion_planes.py:54` · `<modulo>` · estado_str · `"mercadopago"` -> `"__MUTANTE__"`
- `app/services/aprobacion_planes.py:244` · `activar_plan` · comparacion · `is not` -> `is`
- `app/services/aprobacion_planes.py:94` · `precio_lista` · comparacion · `is not` -> `is`
- `app/services/aprobacion_planes.py:94` · `precio_lista` · entero · `0` -> `1`
- `app/services/aprobacion_planes.py:114` · `_validar_aprobacion_manual` · estado_str · `"no_encontrada"` -> `"__MUTANTE__"`
- `app/services/aprobacion_planes.py:199` · `activar_plan` · estado_str · `"no_encontrada"` -> `"__MUTANTE__"`
- `app/services/aprobacion_planes.py:243` · `activar_plan` · comparacion · `==` -> `!=`
- `app/services/aprobacion_planes.py:333` · `activar_plan` · comparacion · `>` -> `>=`
- `app/services/aprobacion_planes.py:497` · `_registrar_plan_en_cola` · comparacion · `is` -> `is not`
- `app/services/aprobacion_planes.py:498` · `_registrar_plan_en_cola` · comparacion · `>` -> `>=`
- `app/services/aprobacion_planes.py:245` · `activar_plan` · comparacion · `==` -> `!=`
- `app/services/aprobacion_planes.py:248` · `activar_plan` · estado_str · `"ya_procesada"` -> `"__MUTANTE__"`
- `app/services/aprobacion_planes.py:248` · `activar_plan` · estado_str · `"no_encontrada"` -> `"__MUTANTE__"`
- `app/services/aprobacion_planes.py:333` · `activar_plan` · entero · `0` -> `1`
- `app/services/aprobacion_planes.py:498` · `_registrar_plan_en_cola` · entero · `0` -> `1`
- `app/services/aprobacion_planes.py:390` · `activar_plan` · estado_str · `"suscripcion"` -> `"__MUTANTE__"`
- `app/services/aprobacion_planes.py:544` · `_registrar_plan_en_cola` · estado_str · `"solicitud_plan"` -> `"__MUTANTE__"`

## app/services/suscripciones_mp.py (25 sin cobertura)

- `app/services/suscripciones_mp.py:127` · `<modulo>` · estado_str · `"actualizada"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:128` · `<modulo>` · estado_str · `"sin_cambios"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:129` · `<modulo>` · estado_str · `"obsoleto"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:130` · `<modulo>` · estado_str · `"estado_desconocido"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:131` · `<modulo>` · estado_str · `"sin_suscripcion"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:132` · `<modulo>` · estado_str · `"cobro_registrado"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:133` · `<modulo>` · estado_str · `"cobro_actualizado"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:134` · `<modulo>` · estado_str · `"duplicado"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:135` · `<modulo>` · estado_str · `"monto_invalido"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:136` · `<modulo>` · estado_str · `"sin_id"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:137` · `<modulo>` · estado_str · `"otro_preapproval"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:138` · `<modulo>` · estado_str · `"en_cola"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:105` · `<modulo>` · estado_str · `"authorized"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:106` · `<modulo>` · estado_str · `"pending"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:107` · `<modulo>` · estado_str · `"paused"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:108` · `<modulo>` · estado_str · `"cancelled"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:115` · `<modulo>` · estado_str · `"scheduled"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:116` · `<modulo>` · estado_str · `"processed"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:117` · `<modulo>` · estado_str · `"recycling"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:118` · `<modulo>` · estado_str · `"cancelled"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:115` · `<modulo>` · estado_str · `"pendiente"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:116` · `<modulo>` · estado_str · `"en_proceso"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:117` · `<modulo>` · estado_str · `"en_proceso"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:118` · `<modulo>` · estado_str · `"cancelado"` -> `"__MUTANTE__"`
- `app/services/suscripciones_mp.py:501` · `__init__` · entero · `400` -> `401`