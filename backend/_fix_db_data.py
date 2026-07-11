"""
Fix script - executes DB changes for PARTE 1 and PARTE 2 data
"""
from sqlalchemy import text
from app.db.database import SessionLocal
from datetime import date, timedelta
import sys
sys.path.insert(0, '.')

db = SessionLocal()
hoy = date.today()

try:
    # ===================================================
    # PARTE 1: Corregir horario sábado en horarios table
    # ===================================================
    print("=" * 60)
    print("PARTE 1: DATA - CORREGIR HORARIO SABADO")
    print("=" * 60)

    # El horario 205 en tabla 'horarios' ya está en 10:00-12:00 (verificado antes)
    r = db.execute(
        text("SELECT id, hora_inicio, hora_fin FROM horarios WHERE id = 205")).first()
    print(f"Horario 205: {r.hora_inicio}-{r.hora_fin}")

    # Verificar clase de hoy con horario_base_id=205
    r2 = db.execute(text("""
        SELECT c.id, c.hora_inicio, c.hora_fin, c.asistentes_confirmados 
        FROM clases c WHERE c.horario_base_id = 205 AND c.fecha = :f AND c.tenant_id = 1
    """), {"f": hoy}).first()

    if r2:
        print(f"Clase hoy id={r2.id}: {r2.hora_inicio}-{r2.hora_fin}")
        # Check reservas
        res = db.execute(text(
            "SELECT COUNT(*) FROM reservas WHERE clase_id = :cid"), {"cid": r2.id}).scalar()
        print(f"Reservas: {res}")

        if res == 0:
            # Delete and recreate
            db.execute(text("DELETE FROM clases WHERE id = :id"),
                       {"id": r2.id})
            db.commit()
            hb = db.execute(text(
                "SELECT disciplina_id, hora_inicio, hora_fin, cupo_maximo FROM horarios WHERE id = 205")).first()
            db.execute(text("""
                INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada)
                VALUES (1, 205, :d, :f, :hi, :hf, :c, 0, false)
            """), {"d": hb.disciplina_id, "f": hoy, "hi": hb.hora_inicio, "hf": hb.hora_fin, "c": hb.cupo_maximo})
            db.commit()
            nueva = db.execute(text(
                "SELECT id, hora_inicio, hora_fin FROM clases WHERE horario_base_id=205 AND fecha=:f AND tenant_id=1"), {"f": hoy}).first()
            print(
                f"  -> Regenerada: id={nueva.id} {nueva.hora_inicio}-{nueva.hora_fin}")
        else:
            # Update in place
            db.execute(text(
                "UPDATE clases SET hora_inicio='10:00', hora_fin='12:00' WHERE id=:id"), {"id": r2.id})
            db.commit()
            print(f"  -> Actualizada a 10:00-12:00")
    else:
        print("No hay clase para hoy con horario_base=205, creando...")
        hb = db.execute(text(
            "SELECT disciplina_id, hora_inicio, hora_fin, cupo_maximo FROM horarios WHERE id = 205")).first()
        db.execute(text("""
            INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada)
            VALUES (1, 205, :d, :f, :hi, :hf, :c, 0, false)
        """), {"d": hb.disciplina_id, "f": hoy, "hi": hb.hora_inicio, "hf": hb.hora_fin, "c": hb.cupo_maximo})
        db.commit()
        print(f"  -> Creada con {hb.hora_inicio}-{hb.hora_fin}")

    # ===================================================
    # PARTE 2: DATA - Generar clases para 3 días
    # ===================================================
    print("\n" + "=" * 60)
    print("PARTE 2: DATA - GENERAR CLASES PARA 3 DIAS")
    print("=" * 60)

    sem = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom']

    for i in range(3):
        dia = hoy + timedelta(days=i)
        ds = dia.weekday()

        if ds == 6:
            print(f"\n{dia} ({sem[ds]}) - Domingo, saltando")
            continue

        horarios = db.execute(text("""
            SELECT id, disciplina_id, hora_inicio, hora_fin, cupo_maximo
            FROM horarios WHERE tenant_id = 1 AND dia_semana = :ds AND activo = true
            ORDER BY hora_inicio
        """), {"ds": ds}).fetchall()

        creadas = 0
        omitidas = 0
        for h in horarios:
            existe = db.execute(text("SELECT id FROM clases WHERE tenant_id=1 AND horario_base_id=:hb AND fecha=:f"),
                                {"hb": h.id, "f": dia}).first()
            if existe:
                omitidas += 1
                continue
            db.execute(text("""
                INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada)
                VALUES (1, :hb, :d, :f, :hi, :hf, :c, 0, false)
            """), {"hb": h.id, "d": h.disciplina_id, "f": dia, "hi": h.hora_inicio, "hf": h.hora_fin, "c": h.cupo_maximo})
            creadas += 1
        db.commit()
        print(f"\n{dia} ({sem[ds]}): {creadas} creadas, {omitidas} omitidas")

        clases = db.execute(text("""
            SELECT c.id, c.hora_inicio, c.hora_fin, d.nombre
            FROM clases c LEFT JOIN disciplinas d ON c.disciplina_id = d.id
            WHERE c.fecha = :f AND c.tenant_id = 1 ORDER BY c.hora_inicio
        """), {"f": dia}).fetchall()
        for c in clases:
            print(f"   id={c.id} {c.hora_inicio}-{c.hora_fin} {c.nombre}")

    # ===================================================
    # VERIFICACION FINAL
    # ===================================================
    print("\n" + "=" * 60)
    print("VERIFICACION FINAL")
    print("=" * 60)

    r = db.execute(
        text("SELECT id, hora_inicio, hora_fin FROM horarios WHERE id=205")).first()
    print(f"\nHorario 205: {r.hora_inicio}-{r.hora_fin} ✅")

    r2 = db.execute(text("SELECT id, hora_inicio, hora_fin FROM clases WHERE horario_base_id=205 AND fecha=:f AND tenant_id=1"), {
                    "f": hoy}).first()
    if r2:
        print(f"Clase sabado: id={r2.id} {r2.hora_inicio}-{r2.hora_fin} ✅")

    for i in range(3):
        dia = hoy + timedelta(days=i)
        if dia.weekday() == 6:
            continue
        count = db.execute(text(
            "SELECT COUNT(*) FROM clases WHERE fecha=:f AND tenant_id=1"), {"f": dia}).scalar()
        print(f"Clases {dia} ({sem[dia.weekday()]}): {count} clase(s)")

except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    db.rollback()
finally:
    db.close()
