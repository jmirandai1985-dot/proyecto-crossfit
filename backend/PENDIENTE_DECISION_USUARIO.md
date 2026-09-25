# PENDIENTE DECISION USUARIO

## Cambios de código solicitados:

1. Si el endpoint GET /wods/hoy debe aceptar un parámetro `fecha` opcional
   (para que coach pueda consultar WODs de días futuros), confírmalo y lo
   implementamos. Por ahora no se tocó porque no es un bug — el endpoint
   solo responde "hoy" por diseño.

2. [2026-09-23] `run_setup_test_db.py` (~línea 70) deriva la conexión directa con
   `_setup_url.replace("-pooler.sa-east-1", ".sa-east-1")`. Neon cambió el formato del host
   (`ep-XXXX-pooler.c-2.sa-east-1.aws.neon.tech` → segmento `c-2`), así que ese replace
   YA NO matchea: el `DROP SCHEMA public CASCADE` / `create_all` viajaría por el pooler en vez
   de la conexión directa. Fix sugerido (NO aplicado): `replace("-pooler.", ".")` o leer
   directamente `settings.DIRECT_URL`.
   ✅ APLICADO (2026-09-24): `run_setup_test_db.py` ahora prioriza `settings.DIRECT_URL` (con
   fallback `replace("-pooler.", ".")`, que sirve para los dos formatos de host) para el
   `DROP SCHEMA`/`create_all`. Antes el replace viejo no matcheaba y el DDL viajaba por el pooler.
   Endpoint TEST **actual**: `ep-jolly-butterfly-b6ty2z89` (rama del MISMO proyecto Neon que PROD,
   desde el 2026-09-24). Histórico: ep-odd-smoke (2026-09-23) → ep-long-salad → ep-billowing-violet
   → ep-purple-cherry.

## Notas
- Los 2 "bugs" reportados inicialmente eran errores del script de prueba,
  no del backend. Las disciplinas Levantamiento Olímpico (id=5) y Clase
  Intensiva Sabado (id=6) ya existen en BD.
- Tests: 28/28 passed en 149.47s.