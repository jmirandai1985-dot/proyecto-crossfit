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
Producto marcado inactivo sigue sumando en "Total de Productos", "Stock Total" y "Valor Inventario" del Dashboard de Bazar. Pendiente para próxima sesión.
A simple vista, es probable que incluya datos de asistencia individual.
Se documentará con detalle cuando se analice.

## Duda 2: Manejo de eliminación de alumnos
Confirmado: backend hace soft delete (activo=false). 
El frontend NO llama al backend al "eliminar" - solo modifica estado local.
Se corrige en Tarea 1.

## Duda 3: Filtro por activo en GET usuarios
El endpoint GET /api/v1/usuarios no filtra por defecto activo=true.
Se decide que el frontend pase activo=true explicitamente.