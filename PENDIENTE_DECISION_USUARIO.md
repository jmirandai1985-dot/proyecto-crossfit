# Pendientes de Decisión del Usuario
Creado: 2026-07-19

## Duda 1: Columnas del reporte descargable (Excel)
El endpoint de reporte descargable está en `backend/app/api/v1/reportes.py`. 
A simple vista, es probable que incluya datos de asistencia individual.
Se documentará con detalle cuando se analice.

## Duda 2: Manejo de eliminación de alumnos
Confirmado: backend hace soft delete (activo=false). 
El frontend NO llama al backend al "eliminar" - solo modifica estado local.
Se corrige en Tarea 1.

## Duda 3: Filtro por activo en GET usuarios
El endpoint GET /api/v1/usuarios no filtra por defecto activo=true.
Se decide que el frontend pase activo=true explicitamente.