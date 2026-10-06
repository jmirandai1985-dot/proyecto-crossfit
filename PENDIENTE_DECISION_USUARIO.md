# Pendientes de Decisión del Usuario
Creado: 2026-07-19

## Duda 1: Columnas del reporte descargable (Excel)
El endpoint de reporte descargable está en `backend/app/api/v1/reportes.py`.

## Duda 2: Mejoras y bugs pendientes (sesión 2026-07-19)
### BUG 5 — CrossFit sin clases hoy
Verificar si el seed genera clases de CrossFit para la fecha actual. Si no, es legítimo (fin de semana con menos clases). Si el seed genera pero el filtro no las muestra, hay bug de fecha.

### BUG 9 — Horarios duplicados en Horarios.jsx
El seed actual crea horarios con `horario_counter` incremental y los asigna a `(hoy.weekday() + 0) % 7`. Si se ejecuta múltiples veces sin limpiar BD, pueden duplicarse. Ya se limpia con DELETE FROM horarios al inicio del seed.

### MEJORA 6 — Clases.jsx vs Supervisión
Recomendación: fusionar la pantalla vieja `Clases.jsx` (tabla CRUD) con `SupervisionClases.jsx` (tarjetas por turno). La tabla CRUD puede coexistir como pestaña "Programación" dentro de Supervisión.

### MEJORA 7 — Planes por género + botón Nuevo
Actualmente Planes.jsx tiene botón "+ Nuevo Plan". La tabla plana podría organizarse en tarjetas por género (Masculino / Femenino / Unisex). No existen planes "estudiante" como categoría en BD — requiere decisión.

### MEJORA 8 — Horarios por turnos
Horarios.jsx actualmente lista plana ordenada por hora. Se recomienda agrupar por turno (AM/MD/PM) como en Supervisión.

### BUG 10 — Bazar: productos inactivos cuentan en stats
Producto marcado inactivo sigue sumando en "Total de Productos", "Stock Total" y "Valor Inventario" del Dashboard de Bazar. **[Corregido 2026-10-04]** Los KPIs (Total productos / Stock total / Valor inventario) y el chip "Stock bajo" ahora cuentan solamente productos `activo=true`; los inactivos siguen visibles en la tabla y en el chip "Inactivos". Estado previo: pendiente para próxima sesión.

### P6 — Dashboard Administrativo: gráficos de negocio
Pendiente de decisión: ¿el Dashboard (/admin/dashboard) debe mostrar los **mismos** gráficos que ya existen en Reportes (/admin/reportes), o gráficos **distintos/más resumidos**? Opciones:
a) Mismos gráficos pero como vista rápida (duplicar componentes Recharts ya creados)
b) Solo KPIs numéricos sin gráficos (alumnos activos, membresías mes, ingreso mes)
c) Gráficos resumidos diferentes a Reportes (ej. solo tendencia de membresías, no ventas)
No implementar hasta decidir.

## Duda 2: Manejo de eliminación de alumnos
Confirmado: backend hace soft delete (activo=false). 
El frontend NO llama al backend al "eliminar" - solo modifica estado local.
Se corrige en Tarea 1.

> **Actualizado 2026-09-23 (migración 034):** el soft delete ahora setea **los dos campos**:
> `estado='baja'` (fuente de verdad) + `activo=false` (derivado), y la BD lo garantiza con el CHECK
> `ck_usuarios_activo_estado` (`activo = (estado = 'activo')`). El frontend sí llama al backend
> (`DELETE /usuarios/{id}` y el selector "Inactivo" de los modales de Alumnos/Coaches manda `estado`).

## Duda 3: Filtro por activo en GET usuarios
El endpoint GET /api/v1/usuarios no filtra por defecto activo=true.
Se decide que el frontend pase activo=true explicitamente.

---

## Pendientes técnicos (sesión 2026-10-04)

### TEST — 2 tests de entrega por código postean pedidos sin `tenant_id` (422)

`backend/tests/test_pedido_entrega_codigo.py::_crear_pedido` (lo usan
`test_validar_genera_el_codigo_y_el_admin_lo_entrega` y
`test_el_respaldo_sin_codigo_del_admin_tambien_sella_la_traza`) hace
`POST /api/v1/pedidos` con `{alumno_id, producto_id, cantidad, voucher_url}` y **sin
`tenant_id`**, pero `PedidoCreate` lo exige (`app/schemas/pedido.py`:
`tenant_id: int = Field(..., gt=0)`) → **422** y los 2 tests fallan.

* **Es pre-existente**: no depende del cambio de "ventas del Bazar" (nada del diff toca
  `pedidos.py` ni sus schemas). `test_pedidos_admin.py` sí manda `tenant_id` y pasa.
* **Arreglo (cuando se retome, NO en esta sesión)**: agregar `"tenant_id"` al payload del
  helper (tomarlo del fixture del alumno/box) — o decidir si el endpoint debe seguir
  exigiéndolo en el body. `voucher_url` ya es obligatorio por P0-4/B-03.