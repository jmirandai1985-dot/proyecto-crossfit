"""
Diagnóstico: horarios_base por día de semana y cálculo de fechas para 5 días
"""
from app.db.database import SessionLocal
from sqlalchemy import text
from datetime import date, timedelta

db = SessionLocal()
try:
    # ── 1. Verificar registros horarios_base por dia_semana ──
    print("=" * 60)
    print("1. HORARIOS BASE POR DIA (tenant_id=1)")
    print("=" * 60)
    result = db.execute(text("""
        SELECT dia_semana, COUNT(*) as total,
               bool_or(activo) as hay_activos
        FROM horarios
        WHERE tenant_id = 1
        GROUP BY dia_semana
        ORDER BY dia_semana
    """)).fetchall()

    nombres = {0: 'LUNES', 1: 'MARTES', 2: 'MIERCOLES', 3: 'JUEVES',
               4: 'VIERNES', 5: 'SABADO', 6: 'DOMINGO'}
    for r in result:
        print(f"  dia_semana={r.dia_semana} ({nombres.get(r.dia_semana, '?')}): "
              f"{r.total} registros, activos={r.hay_activos}")

    total = db.execute(
        text("SELECT COUNT(*) FROM horarios WHERE tenant_id=1")).scalar()
    print(f"\n  Total registros: {total}\n")

    # ── 2. Verificar qué día de la semana es cada fecha ──
    print("=" * 60)
    print("2. CALCULO DE DIA_SEMANA PARA CADA FECHA (usando fecha.weekday())")
    print("=" * 60)
    hoy = date(2026, 7, 11)  # Sábado según el contexto del usuario
    print(
        f"  Hoy = {hoy} -> weekday()={hoy.weekday()} ({nombres[hoy.weekday()]})")

    for i in range(5):
        f = hoy + timedelta(days=i)
        wd = f.weekday()  # 0=Lun...6=Dom
        print(f"  HOY+{i}: {f} -> weekday()={wd} ({nombres[wd]})")

    print()

    # ── 3. Verificar qué horarios_base existen y a qué dia_semana pertenecen ──
    print("=" * 60)
    print("3. TODOS LOS HORARIOS BASE ACTIVOS (detalle)")
    print("=" * 60)
    horarios = db.execute(text("""
        SELECT h.id, h.dia_semana, h.hora_inicio, h.hora_fin, 
               h.cupo_maximo, h.activo, d.nombre as disciplina
        FROM horarios h
        LEFT JOIN disciplinas d ON h.disciplina_id = d.id
        WHERE h.tenant_id = 1
        ORDER BY h.dia_semana, h.hora_inicio
    """)).fetchall()

    for h in horarios:
        print(f"  id={h.id} dia={h.dia_semana}({nombres[h.dia_semana]}) "
              f"{h.hora_inicio}-{h.hora_fin} cupo={h.cupo_maximo} "
              f"activo={h.activo} disciplina={h.disciplina}")

finally:
    db.close()
