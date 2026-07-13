"""
PUNTO 1: Registros CRUDOS de horarios lunes 10:00-18:00, SIN AGRUPAR
PUNTO 2: Existe registro con hora_inicio=17:00?
"""
from sqlalchemy import text
from app.db.database import SessionLocal
import os
import sys
os.environ["ENVIRONMENT"] = ""

db = SessionLocal()
try:
    DIAS = {0: "lunes", 1: "martes", 2: "miercoles",
            3: "jueves", 4: "viernes", 5: "sabado", 6: "domingo"}

    print("=" * 80)
    print("PUNTO 1: Registros CRUDOS de horarios para LUNES (dia_semana=0)")
    print("entre 10:00 y 18:00, SIN AGRUPAR")
    print("=" * 80)

    rows = db.execute(text("""
        SELECT id, tenant_id, disciplina_id, dia_semana,
               hora_inicio::text AS hi, hora_fin::text AS hf,
               cupo_maximo, activo
        FROM horarios
        WHERE tenant_id = 1
          AND dia_semana = 0
          AND hora_inicio >= '10:00'::time
          AND hora_inicio < '18:00'::time
        ORDER BY hora_inicio, disciplina_id
    """)).fetchall()

    for r in rows:
        print("  ID=%4d  disc=%d  cupo=%d  activo=%s  %s -> %s" % (
            r.id, r.disciplina_id, r.cupo_maximo, str(r.activo), r.hi, r.hf))
    print("  Total registros: %d" % len(rows))

    # Slots unicos
    distinct = set((r.hi, r.hf) for r in rows)
    print("  Slots unicos (hi -> hf): %d" % len(distinct))
    for hi, hf in sorted(distinct):
        print("    %s -> %s" % (hi, hf))

    print()
    print("=" * 80)
    print("PUNTO 2: Existe registro con hora_inicio=17:00 en CUALQUIER dia?")
    print("=" * 80)

    rows_17 = db.execute(text("""
        SELECT id, disciplina_id, dia_semana,
               hora_inicio::text AS hi, hora_fin::text AS hf
        FROM horarios
        WHERE tenant_id = 1 AND hora_inicio = '17:00'::time
        ORDER BY dia_semana
    """)).fetchall()

    if rows_17:
        for r in rows_17:
            print("  SI existe: ID=%d  dia=%s  disc=%d  %s -> %s" % (
                r.id, DIAS.get(r.dia_semana, str(r.dia_semana)), r.disciplina_id, r.hi, r.hf))
    else:
        print("  NO existe NINGUN registro con hora_inicio=17:00")

    # hora_inicio=16:00?
    rows_16 = db.execute(text("""
        SELECT id, disciplina_id, dia_semana,
               hora_inicio::text AS hi, hora_fin::text AS hf
        FROM horarios
        WHERE tenant_id = 1 AND hora_inicio = '16:00'::time
        ORDER BY dia_semana
    """)).fetchall()
    if rows_16:
        for r in rows_16:
            print("  hora_inicio=16:00: ID=%d  dia=%s  disc=%d  %s -> %s" % (
                r.id, DIAS.get(r.dia_semana, str(r.dia_semana)), r.disciplina_id, r.hi, r.hf))
    else:
        print("  hora_inicio=16:00: NO existe")

    # hora_inicio=15:00?
    rows_15 = db.execute(text("""
        SELECT id, disciplina_id, dia_semana,
               hora_inicio::text AS hi, hora_fin::text AS hf
        FROM horarios
        WHERE tenant_id = 1 AND hora_inicio = '15:00'::time
        ORDER BY dia_semana
    """)).fetchall()
    if rows_15:
        for r in rows_15:
            print("  hora_inicio=15:00: ID=%d  dia=%s  disc=%d  %s -> %s" % (
                r.id, DIAS.get(r.dia_semana, str(r.dia_semana)), r.disciplina_id, r.hi, r.hf))
    else:
        print("  hora_inicio=15:00: NO existe")

    # Todos los registros de lunes para contexto completo
    print()
    print("Todos los registros de LUNES (dia_semana=0) completo:")
    print("-" * 60)
    all_lun = db.execute(text("""
        SELECT id, disciplina_id, hora_inicio::text AS hi, hora_fin::text AS hf, cupo_maximo
        FROM horarios WHERE tenant_id = 1 AND dia_semana = 0
        ORDER BY hora_inicio, disciplina_id
    """)).fetchall()
    for r in all_lun:
        print("  ID=%4d  disc=%d  cupo=%d  %s -> %s" %
              (r.id, r.disciplina_id, r.cupo_maximo, r.hi, r.hf))

finally:
    db.close()
