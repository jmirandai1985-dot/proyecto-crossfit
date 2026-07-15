# INFORME DE PRUEBAS: Flujo Coach → Alumno (End-to-End)

## Fecha: 2026-07-14

---

## PASO 1 — Arquitectura de `GET /wods/hoy`

### Código revisado (wods.py, líneas 729-746):
```python
@router.get("/hoy")
def obtener_wod_hoy(tenant_id: int = Query(1), db: Session = Depends(get_db)):
    hoy = date.today()
    wod = db.query(Wod).filter(
        Wod.tenant_id == tenant_id,
        Wod.fecha == hoy,
        Wod.activo == True
    ).order_by(Wod.created_at.desc()).first()
    if not wod:
        return None
    return schemas.WodResponse.from_orm_with_names(wod)
```

### Hallazgo CRÍTICO:
`GET /wods/hoy` **NO discrimina por disciplina, clase ni alumno.** Si hay múltiples WODs publicados el mismo día (uno para CrossFit, otro para Levantamiento Olímpico, etc.), este endpoint **devuelve solo el primer WOD** creado (`.first()`), sin relación con la disciplina donde el alumno está inscrito.

**Esto es un bug de diseño:** El alumno que reservó una clase de CrossFit podría ver el WOD de Levantamiento Olímpico, o viceversa. El endpoint debería aceptar un `clase_id` o `disciplina_id` opcional para filtrar.

### Confirmación práctica:
- Se ejecutó `GET /api/v1/wods/hoy?tenant_id=1`
- Respuesta: `[null]` (no hay WODs hoy después de la limpieza del seed)

---

## Resultados de `run_tests.bat`: 25 PASSED, 2 FAILED

### Tests existentes (test_panel_alumno.py): ✅ 18/18 PASSED
### Tests nuevos (test_panel_coach.py): ✅ 7/9 PASSED, ❌ 2 FAILED

---

## PASO 2 — Fallos documentados (sin corregir)

### FALLO 1: `test_c07_marcar_asistencia` → GET /reservas/por-clase/{id} devuelve 404

**Qué paso intentaba:**
1. Crear una reserva para ALUMNO_ID=999 en la clase asignada (clase del día con WOD)
2. Si el POST de reserva falla, obtener reservas vía GET /reservas/por-clase/{clase_id}
3. Marcar asistencia en esa reserva

**Qué esperaba:**
- POST /reservas devuelve 201 con la reserva creada
- GET /reservas/por-clase/{id} devuelve lista de reservas

**Qué pasó realmente:**
- POST /reservas devolvió algo que no fue 200/201 (probable error de validación)
- GET /reservas/por-clase/{clase_id} devolvió **404**

**Evidencia:**
```
r = requests.get(f"{BASE}/reservas/por-clase/{Shared.clase_asignada_id}")
assert r.status_code == 200, f"Status {r.status_code}"
# → AssertionError: Status 404
```

**Causa probable:** El router de reservas usa `router = APIRouter()` sin prefijo y `por-clase` no es un endpoint registrado con ese path. Posiblemente el endpoint real tiene otro nombre o está bajo otro prefijo. No se investigó más por directriz de no corregir.

### FALLO 2: `test_c08_asistencia_false_no_devuelve_credito` → Dependiente del FALLO 1

**Causa raíz:** El test depende de `Shared.reserva_id` que no se pudo obtener porque el test anterior falló.
- `Shared.reserva_id is None` → assert falla inmediatamente.

---

## Resumen

| Aspecto | Estado |
|---------|--------|
| GET /disciplinas | ✅ PASA |
| GET /horarios por disciplina | ✅ PASA |
| POST /wods (texto libre) | ✅ PASA |
| GET /wods/{id} | ✅ PASA |
| PUT /wods/{id} (editar) | ✅ PASA |
| POST asignar WOD a clase | ✅ PASA |
| POST /reservas + GET /reservas/por-clase | ❌ FALLA (404) |
| PUT /reservas/{id}/asistencia | ❌ NO EJECUTADO (depende del anterior) |
| GET /wods/hoy sin filtro por disciplina | ⚠️ Bug de diseño |
| Cleanup | ✅ PASA |

**Total: 25/27 tests pasan, 2 fallan (1 real + 1 dependiente).**
No se corrigió ningún bug — solo se documenta para revisión mañana.