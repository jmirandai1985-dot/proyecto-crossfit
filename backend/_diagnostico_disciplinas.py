"""
Diagnostico: disciplinas actuales y sus horarios en PRODUCCION
"""
from sqlalchemy import text
from app.db.database import SessionLocal
import os
os.environ["ENVIRONMENT"] = ""

db = SessionLocal()
try:
    print("DISCIPLINAS actuales en PRODUCCION:")
    rows = db.execute(text("""
        SELECT id, nombre, es_open_box, activo FROM disciplinas WHERE tenant_id=1 ORDER BY id
    """)).fetchall()
    for r in rows:
        print("  ID=%d  nombre=%s  es_open_box=%s  activo=%s" % (
            r.id, r.nombre, str(r.es_open_box), str(r.activo)))

    print()
    print("Horarios por disciplina:")
    rows2 = db.execute(text("""
        SELECT d.id, d.nombre, COUNT(h.id) as total_horarios
        FROM disciplinas d LEFT JOIN horarios h ON h.disciplina_id = d.id AND h.tenant_id=1
        WHERE d.tenant_id=1
        GROUP BY d.id, d.nombre ORDER BY d.id
    """)).fetchall()
    for r in rows2:
        print("  ID=%d  %s: %d horarios" % (r.id, r.nombre, r.total_horarios))

    print()
    print("Horarios deduplicados por disciplina que REQUIERE coach:")
    print("(disciplinas con es_open_box=False)")
    rows3 = db.execute(text("""
        SELECT d.nombre, h.dia_semana, h.hora_inicio::text, h.hora_fin::text
        FROM horarios h
        JOIN disciplinas d ON h.disciplina_id = d.id
        WHERE h.tenant_id=1 AND d.activo=True AND d.es_open_box=False
        ORDER BY d.id, h.dia_semana, h.hora_inicio
    """)).fetchall()
    current = None
    for r in rows3:
        if r.nombre != current:
            print("  %s:" % r.nombre)
            current = r.nombre
        dias = {0: 'lun', 1: 'mar', 2: 'mie',
                3: 'jue', 4: 'vie', 5: 'sab', 6: 'dom'}
        print("    dia=%s  %s -> %s" %
              (dias.get(r.dia_semana, '?'), r.hora_inicio[:5], r.hora_fin[:5]))

    print()
    print("Filas totales: %d" % len(rows3))
finally:
    db.close()
