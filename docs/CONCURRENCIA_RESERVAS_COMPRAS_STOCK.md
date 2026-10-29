# Concurrencia: último cupo, compras del mismo alumno y stock del Bazar

Verificación del **2026-10-29** sobre TEST. Para cada carrera: dónde está la
protección, con qué mecanismo, y el test de integración que la dispara con dos
requests **simultáneos** (no secuenciales).

Estado: **las tres ya estaban protegidas**. El único hueco encontrado y cerrado
fue la **compra de emergencia** (no tenía lock). No se cambió la mecánica de las
otras dos: se documentó y se agregó la prueba real.

---

## 1. Último cupo de una clase (disciplinas CON tope)

**Mecanismo: `UPDATE` condicional atómico en la base.** No hay `FOR UPDATE` ni
lectura previa que decida: la condición y el incremento van en la MISMA
sentencia, así que Postgres serializa por fila y el que llega segundo ya ve el
contador actualizado.

`app/api/v1/reservas.py:154-172` (`POST /reservas`):

```python
result = db.execute(
    update(Clase)
    .where(Clase.id == clase.id)
    .where(or_(Clase.cupo_maximo.is_(None),                     # 066: sin tope
               Clase.asistentes_confirmados < Clase.cupo_maximo))
    .values(asistentes_confirmados=Clase.asistentes_confirmados + 1)
)
if result.rowcount == 0:
    raise HTTPException(400, "Clase sin cupos disponibles")
```

Mismo patrón en `app/api/v1/asistencia.py:683-696` (presencia sin cargo) y en la
cancelación (`reservas.py:939-945`, `- 1` con `WHERE asistentes > 0`).

Redes adicionales de la MISMA carrera:

* índice único parcial `uq_reservas_clase_alumno_viva` (migración 057): dos
  requests del mismo alumno en la misma clase → el segundo choca y se traduce a
  400 con `es_reserva_duplicada()` (`models/reserva.py:19-29`);
* `SELECT ... FOR UPDATE` de la suscripción (`reservas.py:215-225`) serializa el
  gasto de créditos del alumno y, de paso, el "¿ya reservó?".

Con `cupo_maximo IS NULL` (Musculación / Open Box, migración 066) el `OR` deja
pasar siempre: la sala es de acceso libre y **nunca** hay "cupo lleno".

**Test:** `tests/test_concurrencia_integracion.py::test_ultimo_cupo_solo_entra_uno`
— crea una clase con `cupo = 1` y dos alumnos con créditos, dispara los dos
`POST /reservas` con una `threading.Barrier` y exige `201 + 400`,
`asistentes_confirmados = 1` y **una** reserva viva.

---

## 2. Compras concurrentes del mismo alumno

### 2.1 Alta manual de suscripción (`POST /suscripciones`)

**Mecanismo: `SELECT ... FOR UPDATE` sobre la fila del ALUMNO + ventana de
idempotencia.** `app/api/v1/suscripciones.py:61-87`:

```python
db.query(Usuario).filter(
    Usuario.id == data.usuario_id, Usuario.tenant_id == data.tenant_id,
).with_for_update().first()
gemela = db.query(Suscripcion).filter(... created_at >= now() - 10 min ...).first()
if gemela: raise HTTPException(409, ...)
```

El segundo request espera el lock y, al entrar, ve la suscripción que el primero
commiteó → 409. La ventana es de 10 minutos a propósito: un admin SÍ puede
vender el mismo plan dos veces (renovación), sólo se bloquea el reintento
inmediato.

**Test:** `tests/test_concurrencia_integracion.py::test_doble_compra_del_mismo_alumno_crea_una_sola`
— dos `POST /suscripciones` simultáneos con un admin real del box, exige
`201 + 409`, **una** suscripción y **un** ingreso en `transacciones_financieras`.

### 2.2 Compra de emergencia (`POST /planes/comprar-emergencia`) — hueco cerrado

**Antes:** el endpoint filtraba la suscripción vigente **sin lock**
(`comprar_emergencia.py:69-74`). Dos requests simultáneos leían
`fecha_compra_emergencia IS NULL` los dos, y los dos "compraban": el cupo anual
es **1**, así que la segunda compra no correspondía.

**Ahora** (`comprar_emergencia.py:69-80`):

```python
suscripcion = db.query(Suscripcion).filter(
    Suscripcion.tenant_id == data.tenant_id,
    Suscripcion.usuario_id == data.alumno_id,
    Suscripcion.estado == 'activo',
    vigente_hoy(Suscripcion.fecha_expiracion),
).order_by(Suscripcion.fecha_expiracion.desc()).with_for_update().first()
```

El segundo request espera, re-lee la fila ya actualizada (READ COMMITTED +
`FOR UPDATE` = valor fresco) y cae en el 400 de "Ya usaste tu compra de
emergencia este año". Es el MISMO patrón que el alta de suscripción.

**Test:** `tests/test_concurrencia_integracion.py::test_compra_de_emergencia_simultanea_solo_una`
— alumno sin créditos, dos POST simultáneos → `200 + 400` y
`fecha_compra_emergencia` sellada una sola vez.


---

## 3. Stock del Bazar (último ítem)

**Mecanismo: `UPDATE` condicional atómico sobre `productos.stock`.**
`app/api/v1/pedidos.py:170-190` (`POST /pedidos`):

```python
resultado = db.execute(
    update(Producto)
    .where(Producto.id == producto.id)
    .where(Producto.stock >= pedido_data.cantidad)
    .values(stock=Producto.stock - pedido_data.cantidad)
)
if resultado.rowcount == 0:
    raise HTTPException(400, "Stock insuficiente...")
```

Dos compras simultáneas del último ítem: una obtiene `rowcount = 1`, la otra
`0` → 400, y el stock nunca queda negativo. Las devoluciones (`DELETE` y
rechazo) usan `FOR UPDATE` del pedido **y** del producto para no devolver el
stock dos veces (`pedidos.py:569-594,675-702`).

**Test:** `tests/test_concurrencia_integracion.py::test_ultimo_item_del_bazar_no_se_vende_dos_veces`
— producto con `stock = 1`, dos alumnos, dos `POST /pedidos` simultáneos →
`201 + 400`, `stock = 0` y **un** pedido.

---

## 4. Cómo se corren

```powershell
cd backend
$env:ENVIRONMENT='test'
py -3.12 -m pytest tests/test_concurrencia_integracion.py -q
```

* Los requests salen de hilos distintos y arrancan juntos (`threading.Barrier`):
  la ventana de carrera es real, no "el primero terminó antes del segundo".
* Cada test crea sus usuarios/clases/productos y los borra en el `finally`
  (`Escenario.limpiar`), incluidos los avisos que generan el pedido y el alta
  (FK `NO ACTION` sobre `usuarios`).
* Se saltea solo si la API no está en `:8000` o si `ENVIRONMENT != test`.
* Resultado de la última corrida: **4 passed** (~59 s).

Los tests unitarios de la misma familia (sin red) siguen en
`tests/test_concurrencia_acid.py` (**38 passed**): simulan Postgres y además
tienen guardas de sensibilidad (apagan el índice o el lock y muestran el bug).

---

## 5. Resumen

| Carrera | Mecanismo | Dónde | Test real |
| --- | --- | --- | --- |
| Último cupo | `UPDATE ... WHERE asistentes < cupo` (+ índice único de reserva viva) | `reservas.py:154-172`, `asistencia.py:683-696` | `test_ultimo_cupo_solo_entra_uno` |
| Dos compras del mismo alumno | `FOR UPDATE` del alumno + ventana de idempotencia | `suscripciones.py:61-87` | `test_doble_compra_del_mismo_alumno_crea_una_sola` |
| Compra de emergencia | `FOR UPDATE` de la suscripción (**agregado**) | `comprar_emergencia.py:69-80` | `test_compra_de_emergencia_simultanea_solo_una` |
| Último ítem del Bazar | `UPDATE ... WHERE stock >= cantidad` | `pedidos.py:170-190` | `test_ultimo_item_del_bazar_no_se_vende_dos_veces` |
