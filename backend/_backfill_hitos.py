"""Backfill retroactivo de hitos (Sistema de Asistencia, Fase 2).

Se ejecuta UNA vez al desplegar la funcionalidad en cada box: genera los hitos
que correspondan a los últimos 12 meses cerrados de reservas existentes, SIN
enviar correos retroactivos (notificado=True). Idempotente: re-ejecutarlo no
duplica nada (UNIQUE(alumno_id, nivel)).

Uso (seleccionar el entorno con ENVIRONMENT):
    $env:ENVIRONMENT='test'; python _backfill_hitos.py          # branch test
    $env:ENVIRONMENT='';      python _backfill_hitos.py          # producción
Opcional: --tenant_id=N para un box puntual (default: todos).
"""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app.db.database import SessionLocal  # noqa: E402
from app.services import asistencia_service as svc  # noqa: E402

tenant_id = None
for arg in sys.argv[1:]:
    if arg.startswith("--tenant_id="):
        tenant_id = int(arg.split("=")[1])

db = SessionLocal()
try:
    res = svc.backfill_hitos(db, meses=12, tenant_id=tenant_id)
    print(f"backfill: hitos_creados={res['hitos_creados']} "
          f"alumnos_procesados={res['alumnos_procesados']} "
          f"ventana_meses={res['ventana_meses']}")
    for d in res["detalle"]:
        print(f"  - alumno {d['alumno_id']} ({d['nombre']}): nivel {d['nivel']} "
              f"(racha {d['meses_consecutivos']}) en {d['mes_alcanzado']}")
finally:
    db.close()
