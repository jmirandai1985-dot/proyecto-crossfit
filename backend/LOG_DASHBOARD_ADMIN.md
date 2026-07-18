# LOG_DASHBOARD_ADMIN - Dashboard de Admin con Fidelización

## Fecha: 17/07/2026

## Cambios realizados

### Backend - fidelizacion.py
1. **Nuevo endpoint GET /fidelizacion/tenant/{tenant_id}/en-riesgo**
   - Devuelve TODOS los alumnos activos del tenant con días sin asistir > umbral
   - Similar al endpoint por coach, pero sin filtrar
   - Umbral configurable (default 7 días)

2. **Nuevo endpoint GET /fidelizacion/tenant/{tenant_id}/vencimientos**
   - Devuelve alumnos con membresía activa cuya fecha_expiracion está en los próximos N días
   - Incluye datos del usuario, plan, fecha expiracion, días restantes, créditos
   - Umbral configurable (default 5 días)

### Frontend - admin/Dashboard.jsx
1. **Tarjeta "Alumnos en Riesgo"** - Muestra conteo de alumnos con >7 días sin actividad
2. **Tarjeta "Vencimientos Inminentes"** - Muestra conteo de membresías por vencer en 5 días
3. **Panel de Acción y Fidelización** - Tabla debajo de solicitudes con:
   - Nombre del alumno
   - Estado de alerta ("Inactivo hace X días" o "Vence en X días")
   - Botón "Acción Rápida" (STUB - muestra mensaje de pendiente configuración Resend)
4. Carga asíncrona de datos de fidelización junto con solicitudes

### Nota
- El envío real de email está marcado como STUB (handleAccionRapida)
- Falta configurar cuenta de Resend para envío real