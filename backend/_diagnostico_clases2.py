"""
Diagnóstico detallado: cupos, tenant, fechas, y filtros
"""
from sqlalchemy import text
from app.db.database import SessionLocal
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))


def diagnosticar():
    db = SessionLocal()
    try:
        print("=== DIAGNÓSTICO DETALLADO DE CLASES ===")

        # --- 1. Ver las 41 clases de hoy con todos los detalles ---
        rows = db.execute(text("""
            SELECT c.id, c.fecha, c.hora_inicio, c.hora_fin,
                   c.cupo_maximo, c.asistentes_confirmados, c.cancelada,
                   c.tenant_id, c.coach_id, c.disciplina_id,
                   d.nombre AS disciplina_nombre
            FROM clases c
            LEFT JOIN disciplinas d ON c.disciplina_id = d.id
            WHERE c.fecha = '2026-07-10'
            ORDER BY c.hora_inicio
        """)).fetchall()

        print(f"\n1. CLASES DEL 2026-07-10: {len(rows)} registros")
        for r in rows:
            cupos_libres = r.cupo_maximo - r.asistentes_confirmados
            print(f"   id={r.id} | {r.hora_inicio}-{r.hora_fin} | "
                  f"disciplina_id={r.disciplina_id} | "
                  f"tenant_id={r.tenant_id} | coach_id={r.coach_id} | "
                  f"cupo={r.cupo_maximo} | asistentes={r.asistentes_confirmados} | "
                  f"libres={cupos_libres} | cancelada={r.cancelada} | "
                  f"disciplina='{r.disciplina_nombre}'")

        # --- 2. Simular el filtro "solo_con_cupo" ---
        con_cupo = db.execute(text("""
            SELECT COUNT(*) FROM clases c
            WHERE c.fecha = '2026-07-10'
              AND c.tenant_id = 1
              AND c.asistentes_confirmados < c.cupo_maximo
        """)).scalar()
        print(
            f"\n2. Clases con cupo disponible (asistentes < cupo): {con_cupo}")

        # --- 3. Mostrar TODAS las clases (sin filtro fecha) con disciplina ---
        todas = db.execute(text("""
            SELECT c.id, c.fecha, c.hora_inicio, c.cancelada,
                   c.asistentes_confirmados, c.cupo_maximo,
                   d.nombre AS disciplina_nombre
            FROM clases c
            LEFT JOIN disciplinas d ON c.disciplina_id = d.id
            ORDER BY c.fecha, c.hora_inicio
        """)).fetchall()
        print(f"\n3. TODAS las clases ({len(todas)} total):")
        for t in todas:
            print(f"   id={t.id} | fecha={t.fecha} | {t.hora_inicio} | "
                  f"disciplina='{t.disciplina_nombre}' | "
                  f"asistentes={t.asistentes_confirmados}/{t.cupo_maximo} | "
                  f"cancelada={t.cancelada}")

        # --- 4. Verificar que existen registros en tablas relacionadas ---
        print(f"\n4. Tablas relacionadas:")
        for tbl, qry in [
            ("tenants", "SELECT COUNT(*) FROM tenants"),
            ("horarios (activos)", "SELECT COUNT(*) FROM horarios WHERE activo=true"),
            ("disciplinas", "SELECT COUNT(*) FROM disciplinas"),
        ]:
            cnt = db.execute(text(qry)).scalar()
            print(f"   {tbl}: {cnt} registros")

        # --- 5. Ver si alguna clase tiene asistentes >= cupo (todas llenas) ---
        llenas = db.execute(text("""
            SELECT COUNT(*) FROM clases c
            WHERE c.fecha = '2026-07-10'
              AND c.asistentes_confirmados >= c.cupo_maximo
        """)).scalar()
        print(f"\n5. Clases del 2026-07-10 COMPLETAMENTE LLENAS: {llenas}")

        # --- 6. Verificar fecha actual del sistema ---
        from datetime import datetime
        ahora = datetime.now()
        print(f"\n6. Fecha/Hora del sistema: {ahora}")
        print(f"   TZ America/Santiago: UTC-4")

        # --- 7. Crear una fecha con formato ISO ---
        iso_hoy = datetime.now().strftime("%Y-%m-%d")
        print(f"   7. Hoy (formato ISO local): {iso_hoy}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    diagnosticar()
