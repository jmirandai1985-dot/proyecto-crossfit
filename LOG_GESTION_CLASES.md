# LOG DE ITERACIONES - GestionClases.jsx

## Iteración 1 — Sidebar + GestionClases reestructurado
**Commit:** `7f81ab5` (sin push)

### Implementado en código (no verificado visualmente — ver abajo)

**Sidebar coach:** ✅ "Gestión de Clases" reemplaza "Pizarra"
**Ruta:** ✅ `/coach/gestion-clases`

**Pestaña Planificar:**
- ✅ Selector fecha solo futuro
- ✅ 3 tarjetas turno (AM/MD/PM) como paso inicial
- ✅ Disciplinas dinámicas (excluye Gap y es_open_box)
- ✅ Horarios filtrados por turno + día + disciplina + checkboxes
- ✅ Formulario WOD v2 (calentamiento, fuerza_habilidad, wod_principal, tipo_metcon)
- ✅ Botón "Confirmar Clase y Publicar WOD"
- ✅ Modo lectura + editar WOD existente
- ✅ Asistencia ASISTIÓ/FALTA editable

**Pestaña Clases de Hoy:**
- ✅ Selector fecha independiente
- ✅ Mensaje "Aún no hay WOD publicado"
- ✅ Lista cronológica con WODs
- ✅ Badge "EN CURSO" según hora actual
- ✅ Botón "Tomar Asistencia"

**Backend:** ✅ Migración 006, 4 WODs borrados, test_16 v2, 18/18 tests

### Pendiente (sin verificación visual)
1. ❌ **Bug "clic Turno AM no muestra disciplinas"** — No se pudo diagnosticar en navegador. Causa más probable: el servidor no estaba en TEST o no heredó correctamente ENVIRONMENT=test.
2. ❌ **Badge progreso asistencia** (Clases de Hoy) — Muestra reservas/cupo, no asistencia marcada/total
3. ❌ **Botones "Volver"** — Solo existe "← Volver a turnos". Faltan en los demás niveles.
4. ❌ **Sidebar coach visual** — No verificado que el enlace se renderice.
5. ❌ **Selector fecha solo futuro** — Implementado con `min={hoy}`, no verificado.

### Tests más reciente
- run_tests.bat lanzado — esperando resultado.
- Histórico: 18/18 PASSED en corridas previas (91s-96s).