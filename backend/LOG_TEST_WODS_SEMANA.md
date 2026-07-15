# LOG TEST WODS SEMANA

Fecha ejecucion: 2026-07-15T17:03:21.414546
WODs creados: 7
Reservas creadas: 0

## Log detallado

```
[17:01:36] === FASE 0: SETUP DISCIPLINAS Y HORARIOS ===
[17:01:38] Disciplinas existentes: ['CrossFit']
[17:01:40]   POST /disciplinas/ -> 422: {"detail":[{"type":"missing","loc":["query","nombre"],"msg":"Field required","input":null}]}
[17:01:40] ERROR creando disciplina 'Levantamiento Olimpico': 422 {"detail":[{"type":"missing","loc":["query","nombre"],"msg":"Field required","input":null}]}
[17:01:42]   POST /disciplinas/ -> 422: {"detail":[{"type":"missing","loc":["query","nombre"],"msg":"Field required","input":null}]}
[17:01:42] ERROR creando disciplina 'Clase Intensiva Sabado': 422 {"detail":[{"type":"missing","loc":["query","nombre"],"msg":"Field required","input":null}]}
[17:01:42] Disciplina IDs: {'CrossFit': 1}
[17:01:42] 
=== FASE 1: CREAR WODS POR DIA Y DISCIPLINA ===
[17:01:42] 
--- DIA 1: Miercoles (2026-07-15) ---
[17:01:46]   Clase encontrada: id=356, hora=10:00:00
[17:01:49]   WOD CREADO: id=107, titulo='TEST MIERCOLES - CrossFit'
[17:01:52]   WOD asignado a clase 356
[17:01:54]   POST /reservas/ -> 400: {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:01:54]   WARNING: Reserva: 400 {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:01:57]   VERIFICACION ALUMNO: WOD visto = 'TEST MIERCOLES - CrossFit'
  DATA: {"id": 107, "tenant_id": 1, "fecha": "2026-07-15", "hora_inicio": null, "hora_fin": null, "titulo": "TEST MIERCOLES - CrossFit", "descripcion": null, "calentamiento": "Calentamiento TEST para Miercoles", "fuerza_habilidad": "Fuerza TEST para Miercoles", "wod_principal": "WOD PRINCIPAL: 21-15-9 de Cr
[17:01:57]   SKIP Levantamiento Olimpico: sin disciplina_id
[17:01:57]   SKIP Clase Intensiva Sabado: solo aplica Sabado
[17:01:57] 
--- DIA 2: Jueves (2026-07-16) ---
[17:01:59]   Clase encontrada: id=357, hora=10:00:00
[17:02:02]   WOD CREADO: id=108, titulo='TEST JUEVES - CrossFit'
[17:02:05]   WOD asignado a clase 357
[17:02:08]   POST /reservas/ -> 400: {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:08]   WARNING: Reserva: 400 {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:11]   VERIFICACION ALUMNO: WOD visto = 'TEST MIERCOLES - CrossFit'
  DATA: {"id": 107, "tenant_id": 1, "fecha": "2026-07-15", "hora_inicio": null, "hora_fin": null, "titulo": "TEST MIERCOLES - CrossFit", "descripcion": null, "calentamiento": "Calentamiento TEST para Miercoles", "fuerza_habilidad": "Fuerza TEST para Miercoles", "wod_principal": "WOD PRINCIPAL: 21-15-9 de Cr
[17:02:11]   SKIP Levantamiento Olimpico: sin disciplina_id
[17:02:11]   SKIP Clase Intensiva Sabado: solo aplica Sabado
[17:02:11] 
--- DIA 3: Viernes (2026-07-17) ---
[17:02:14]   Clase encontrada: id=358, hora=10:00:00
[17:02:17]   WOD CREADO: id=109, titulo='TEST VIERNES - CrossFit'
[17:02:20]   WOD asignado a clase 358
[17:02:23]   POST /reservas/ -> 400: {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:23]   WARNING: Reserva: 400 {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:25]   VERIFICACION ALUMNO: WOD visto = 'TEST MIERCOLES - CrossFit'
  DATA: {"id": 107, "tenant_id": 1, "fecha": "2026-07-15", "hora_inicio": null, "hora_fin": null, "titulo": "TEST MIERCOLES - CrossFit", "descripcion": null, "calentamiento": "Calentamiento TEST para Miercoles", "fuerza_habilidad": "Fuerza TEST para Miercoles", "wod_principal": "WOD PRINCIPAL: 21-15-9 de Cr
[17:02:25]   SKIP Levantamiento Olimpico: sin disciplina_id
[17:02:25]   SKIP Clase Intensiva Sabado: solo aplica Sabado
[17:02:25] 
--- DIA 4: Sabado (2026-07-18) ---
[17:02:28]   Clase encontrada: id=359, hora=10:00:00
[17:02:31]   WOD CREADO: id=110, titulo='TEST SABADO - CrossFit'
[17:02:34]   WOD asignado a clase 359
[17:02:37]   POST /reservas/ -> 400: {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:37]   WARNING: Reserva: 400 {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:40]   VERIFICACION ALUMNO: WOD visto = 'TEST MIERCOLES - CrossFit'
  DATA: {"id": 107, "tenant_id": 1, "fecha": "2026-07-15", "hora_inicio": null, "hora_fin": null, "titulo": "TEST MIERCOLES - CrossFit", "descripcion": null, "calentamiento": "Calentamiento TEST para Miercoles", "fuerza_habilidad": "Fuerza TEST para Miercoles", "wod_principal": "WOD PRINCIPAL: 21-15-9 de Cr
[17:02:40]   SKIP Levantamiento Olimpico: sin disciplina_id
[17:02:40]   SKIP Clase Intensiva Sabado: sin disciplina_id
[17:02:40] 
--- DIA 5: Domingo (2026-07-19) ---
[17:02:42]   Clase encontrada: id=360, hora=10:00:00
[17:02:45]   WOD CREADO: id=111, titulo='TEST DOMINGO - CrossFit'
[17:02:48]   WOD asignado a clase 360
[17:02:51]   POST /reservas/ -> 400: {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:51]   WARNING: Reserva: 400 {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:02:54]   VERIFICACION ALUMNO: WOD visto = 'TEST MIERCOLES - CrossFit'
  DATA: {"id": 107, "tenant_id": 1, "fecha": "2026-07-15", "hora_inicio": null, "hora_fin": null, "titulo": "TEST MIERCOLES - CrossFit", "descripcion": null, "calentamiento": "Calentamiento TEST para Miercoles", "fuerza_habilidad": "Fuerza TEST para Miercoles", "wod_principal": "WOD PRINCIPAL: 21-15-9 de Cr
[17:02:54]   SKIP Levantamiento Olimpico: sin disciplina_id
[17:02:54]   SKIP Clase Intensiva Sabado: solo aplica Sabado
[17:02:54] 
--- DIA 6: Lunes (2026-07-20) ---
[17:02:56]   Clase encontrada: id=361, hora=10:00:00
[17:02:59]   WOD CREADO: id=112, titulo='TEST LUNES - CrossFit'
[17:03:02]   WOD asignado a clase 361
[17:03:05]   POST /reservas/ -> 400: {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:03:05]   WARNING: Reserva: 400 {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:03:07]   VERIFICACION ALUMNO: WOD visto = 'TEST MIERCOLES - CrossFit'
  DATA: {"id": 107, "tenant_id": 1, "fecha": "2026-07-15", "hora_inicio": null, "hora_fin": null, "titulo": "TEST MIERCOLES - CrossFit", "descripcion": null, "calentamiento": "Calentamiento TEST para Miercoles", "fuerza_habilidad": "Fuerza TEST para Miercoles", "wod_principal": "WOD PRINCIPAL: 21-15-9 de Cr
[17:03:07]   SKIP Levantamiento Olimpico: sin disciplina_id
[17:03:07]   SKIP Clase Intensiva Sabado: solo aplica Sabado
[17:03:07] 
--- DIA 7: Martes (2026-07-21) ---
[17:03:10]   Clase encontrada: id=362, hora=10:00:00
[17:03:13]   WOD CREADO: id=113, titulo='TEST MARTES - CrossFit'
[17:03:15]   WOD asignado a clase 362
[17:03:18]   POST /reservas/ -> 400: {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:03:18]   WARNING: Reserva: 400 {"detail":"El alumno ya tiene una reserva activa para esta clase"}
[17:03:21]   VERIFICACION ALUMNO: WOD visto = 'TEST MIERCOLES - CrossFit'
  DATA: {"id": 107, "tenant_id": 1, "fecha": "2026-07-15", "hora_inicio": null, "hora_fin": null, "titulo": "TEST MIERCOLES - CrossFit", "descripcion": null, "calentamiento": "Calentamiento TEST para Miercoles", "fuerza_habilidad": "Fuerza TEST para Miercoles", "wod_principal": "WOD PRINCIPAL: 21-15-9 de Cr
[17:03:21]   SKIP Levantamiento Olimpico: sin disciplina_id
[17:03:21]   SKIP Clase Intensiva Sabado: solo aplica Sabado
```
