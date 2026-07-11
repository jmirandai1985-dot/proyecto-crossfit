"""
One-shot: Generar clases faltantes para Martes 14 y Miercoles 15 usando SQL directo
"""
from app.db.database import SessionLocal
from sqlalchemy import text
from datetime import date, timedelta

db = SessionLocal()
try:
    hoy = date(2026, 7, 14)
    fecha_hasta = date(2026, 7, 15)
    fecha_actual = hoy
    total_creadas = 0

    while fecha_actual <= fecha_hasta:
        dia_semana = fecha_actual.weekday()
        if dia_semana == 6:  # domingo
            fecha_actual += timedelta(days=1)
            continue

        # Obtener horarios base para este dia
        horarios = db.execute(text("""
            SELECT id, disciplina_id, hora_inicio, hora_fin, cupo_maximo
            FROM horarios
            WHERE tenant_id = 1 AND dia_semana = :ds AND activo = true
            ORDER BY id
        """), {"ds": dia_semana}).fetchall()

        creadas = 0
        omitidas = 0
        for h in horarios:
            # Verificar si ya existe
            existe = db.execute(text("""
                SELECT COUNT(*) FROM clases
                WHERE tenant_id = 1 AND horario_base_id = :hbid AND fecha = :f
            """), {"hbid": h.id, "f": fecha_actual}).scalar()

            if existe:
                omitidas += 1
                continue

            # Insertar clase
            db.execute(text("""
                INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada, created_at, updated_at)
                VALUES (1, :hbid, :did, :f, :hi, :hf, :cupo, 0, false, NOW(), NOW())
            """), {
                "hbid": h.id,
                "did": h.disciplina_id,
                "f": fecha_actual,
                "hi": h.hora_inicio,
                "hf": h.hora_fin,
                "cupo": h.cupo_maximo
            })
            creadas += 1

        db.commit()
        print(
            f"  {fecha_actual} (dia_semana={dia_semana}): {creadas} creadas, {omitidas} omitidas")
        total_creadas += creadas
        fecha_actual += timedelta(days=1)

    print(f"\nTotal clases creadas: {total_creadas}")
finally:
    db.close()
