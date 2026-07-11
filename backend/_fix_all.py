"""
Script único para:
  PARTE 1: Corregir horario sábado (10:00-12:00) en horarios_base y regenerar clase de hoy
  PARTE 2: Generar clases para HOY + 2 días siguientes
"""
from sqlalchemy import text
from app.db.database import SessionLocal
from datetime import date, timedelta
import sys
sys.path.insert(0, '.')

db = SessionLocal()
hoy = date.today()
dias_semana = ['Lunes', 'Martes', 'Miércoles',
               'Jueves', 'Viernes', 'Sábado', 'Domingo']

try:
    # ══════════════════════════════════════════════
    # DIAGNÓSTICO INICIAL
    # ══════════════════════════════════════════════
    print("=" * 60)
    print("DIAGNÓSTICO INICIAL")
    print("=" * 60)

    # Horarios sábado
    rows = db.execute(text("""
        SELECT h.id, h.disciplina_id, d.nombre as disc_nombre,
               h.dia_semana, h.hora_inicio, h.hora_fin, h.cupo_maximo, h.activo
        FROM horarios_base h
        LEFT JOIN disciplinas d ON h.disciplina_id = d.id
        WHERE h.dia_semana = 5
        ORDER BY h.hora_inicio
    """)).fetchall()
    print("\n📋 HORARIOS DEL SÁBADO:")
    for r in rows:
        print(f"   id={r.id} disc_id={r.disciplina_id} disc='{r.disc_nombre}' dia={r.dia_semana} inicio={r.hora_inicio} fin={r.hora_fin} cupo={r.cupo_maximo} activo={r.activo}")

    # Clases hoy
    rows = db.execute(text("""
        SELECT c.id, c.fecha, c.hora_inicio, c.hora_fin, d.nombre as disc,
               c.asistentes_confirmados, c.cupo_maximo
        FROM clases c
        LEFT JOIN disciplinas d ON c.disciplina_id = d.id
        WHERE c.fecha = :fecha AND c.tenant_id = 1
        ORDER BY c.hora_inicio
    """), {"fecha": hoy}).fetchall()
    print(f"\n📋 CLASES PARA HOY ({hoy}):")
    for r in rows:
        # Check reservas
        cnt = db.execute(text(
            "SELECT COUNT(*) FROM reservas WHERE clase_id = :cid"), {"cid": r.id}).scalar()
        print(f"   id={r.id} {r.fecha} {r.hora_inicio}-{r.hora_fin} {r.disc} asistentes={r.asistentes_confirmados} cupo={r.cupo_maximo} reservas={cnt}")

    # Clases mañana y pasado
    for i in [1, 2]:
        dia = hoy + timedelta(days=i)
        cnt = db.execute(text(
            "SELECT COUNT(*) FROM clases WHERE fecha = :fecha AND tenant_id = 1"), {"fecha": dia}).scalar()
        print(
            f"\n📋 CLASES PARA {dias_semana[dia.weekday()]} ({dia}): {'(sin clases)' if cnt == 0 else f'{cnt} clase(s)'}")

    # ══════════════════════════════════════════════
    # PARTE 1: CORREGIR HORARIO SÁBADO
    # ══════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PARTE 1: CORREGIR HORARIO DEL SÁBADO")
    print("=" * 60)

    # 1. Actualizar horarios_base
    result = db.execute(
        text("UPDATE horarios_base SET hora_inicio = '10:00', hora_fin = '12:00' WHERE id = 205")
    )
    db.commit()
    print(f"\n✅ Horario 205 actualizado a 10:00-12:00")

    # 2. Verificar la clase de hoy
    clase_hoy = db.execute(text("""
        SELECT c.id, c.hora_inicio, c.hora_fin, c.asistentes_confirmados
        FROM clases c
        WHERE c.horario_base_id = 205 AND c.fecha = :fecha AND c.tenant_id = 1
    """), {"fecha": hoy}).first()

    if clase_hoy:
        reservas = db.execute(
            text("SELECT COUNT(*) FROM reservas WHERE clase_id = :cid"),
            {"cid": clase_hoy.id}
        ).scalar()

        print(f"\nClase de hoy id={clase_hoy.id} (horario actual: {clase_hoy.hora_inicio}-{clase_hoy.hora_fin}, asistentes={clase_hoy.asistentes_confirmados}, reservas={reservas})")

        if reservas == 0:
            print("  → Sin reservas. Eliminando y regenerando...")
            # Eliminar
            db.execute(text("DELETE FROM clases WHERE id = :id"),
                       {"id": clase_hoy.id})
            db.commit()

            # Regenerar desde horarios_base
            hb = db.execute(text("""
                SELECT id, disciplina_id, hora_inicio, hora_fin, cupo_maximo
                FROM horarios_base WHERE id = 205
            """)).first()

            if hb:
                db.execute(text("""
                    INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada)
                    VALUES (1, :hb_id, :disc_id, :fecha, :hora_ini, :hora_fin, :cupo, 0, false)
                """), {
                    "hb_id": hb.id, "disc_id": hb.disciplina_id, "fecha": hoy,
                    "hora_ini": hb.hora_inicio, "hora_fin": hb.hora_fin, "cupo": hb.cupo_maximo
                })
                db.commit()

                nueva = db.execute(text("""
                    SELECT id, hora_inicio, hora_fin FROM clases
                    WHERE horario_base_id = 205 AND fecha = :fecha AND tenant_id = 1
                """), {"fecha": hoy}).first()
                print(
                    f"  ✅ Nueva clase id={nueva.id}: {nueva.hora_inicio}-{nueva.hora_fin}")
        else:
            print(
                f"  → Tiene {reservas} reservas. Actualizando horario existente...")
            db.execute(text("""
                UPDATE clases SET hora_inicio = '10:00', hora_fin = '12:00'
                WHERE id = :id
            """), {"id": clase_hoy.id})
            db.commit()
            print(f"  ✅ Clase id={clase_hoy.id} actualizada a 10:00-12:00")
    else:
        print(f"\n  → No hay clase para hoy con horario_base 205, creando...")
        hb = db.execute(text("""
            SELECT id, disciplina_id, hora_inicio, hora_fin, cupo_maximo
            FROM horarios_base WHERE id = 205
        """)).first()
        if hb:
            db.execute(text("""
                INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada)
                VALUES (1, :hb_id, :disc_id, :fecha, :hora_ini, :hora_fin, :cupo, 0, false)
            """), {
                "hb_id": hb.id, "disc_id": hb.disciplina_id, "fecha": hoy,
                "hora_ini": hb.hora_inicio, "hora_fin": hb.hora_fin, "cupo": hb.cupo_maximo
            })
            db.commit()
            print(
                f"  ✅ Clase creada con horario {hb.hora_inicio}-{hb.hora_fin}")

    # ══════════════════════════════════════════════
    # PARTE 2: GENERAR CLASES PARA 3 DÍAS
    # ══════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PARTE 2: GENERAR CLASES PARA 3 DÍAS")
    print("=" * 60)

    for i in range(3):
        dia = hoy + timedelta(days=i)
        dia_sem = dia.weekday()

        if dia_sem == 6:
            print(
                f"\n📅 {dia} ({dias_semana[dia_sem]}) → Domingo, sin horarios")
            continue

        # Obtener horarios base para este día
        horarios = db.execute(text("""
            SELECT id, disciplina_id, hora_inicio, hora_fin, cupo_maximo
            FROM horarios_base
            WHERE tenant_id = 1 AND dia_semana = :dia AND activo = true
            ORDER BY hora_inicio
        """), {"dia": dia_sem}).fetchall()

        print(
            f"\n📅 {dia} ({dias_semana[dia_sem]}): {len(horarios)} horarios base encontrados")

        creadas = 0
        omitidas = 0

        for hb in horarios:
            existe = db.execute(text("""
                SELECT id FROM clases
                WHERE tenant_id = 1 AND horario_base_id = :hb_id AND fecha = :fecha
            """), {"hb_id": hb.id, "fecha": dia}).first()

            if existe:
                omitidas += 1
                continue

            db.execute(text("""
                INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada)
                VALUES (1, :hb_id, :disc_id, :fecha, :hora_ini, :hora_fin, :cupo, 0, false)
            """), {
                "hb_id": hb.id, "disc_id": hb.disciplina_id, "fecha": dia,
                "hora_ini": hb.hora_inicio, "hora_fin": hb.hora_fin, "cupo": hb.cupo_maximo
            })
            creadas += 1

        db.commit()
        print(f"  → {creadas} creadas, {omitidas} omitidas")

    # ══════════════════════════════════════════════
    # VERIFICACIÓN FINAL
    # ══════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("VERIFICACIÓN FINAL")
    print("=" * 60)

    # Verificar horarios_base
    hb = db.execute(text("""
        SELECT h.id, h.hora_inicio, h.hora_fin, d.nombre as disc
        FROM horarios_base h
        LEFT JOIN disciplinas d ON h.disciplina_id = d.id
        WHERE h.id = 205
    """)).first()
    print(
        f"\n✅ Horario base Sábado (id=205): {hb.hora_inicio}-{hb.hora_fin} ({hb.disc})")

    # Verificar todos los días
    for i in range(3):
        dia = hoy + timedelta(days=i)
        if dia.weekday() == 6:
            continue

        clases = db.execute(text("""
            SELECT c.id, c.horario_base_id, c.hora_inicio, c.hora_fin,
                   c.cupo_maximo, c.asistentes_confirmados, d.nombre as disc
            FROM clases c
            LEFT JOIN disciplinas d ON c.disciplina_id = d.id
            WHERE c.fecha = :fecha AND c.tenant_id = 1
            ORDER BY c.hora_inicio
        """), {"fecha": dia}).fetchall()

        print(f"\n📋 Clases para {dia} ({dias_semana[dia.weekday()]}):")
        if clases:
            for c in clases:
                print(
                    f"   id={c.id} hb={c.horario_base_id} {c.hora_inicio}-{c.hora_fin} cupo={c.cupo_maximo} asistentes={c.asistentes_confirmados} disc='{c.disc}'")
        else:
            print("   (sin clases)")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    db.rollback()
finally:
    db.close()
