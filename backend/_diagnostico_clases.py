"""
Diagnóstico: consulta directa a la tabla clases en Neon PostgreSQL
"""
from sqlalchemy import text
from app.db.database import SessionLocal
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))


def diagnosticar():
    db = SessionLocal()
    try:
        # 1. Total de registros en clases
        total = db.execute(text("SELECT COUNT(*) FROM clases")).scalar()
        print(f"=== DIAGNÓSTICO TABLA CLASES ===")
        print(f"1. TOTAL registros en tabla clases: {total}")

        # 2. Registros para 2026-07-10
        hoy = db.execute(
            text("SELECT COUNT(*) FROM clases WHERE fecha = :fecha"),
            {"fecha": "2026-07-10"}
        ).scalar()
        print(f"2. Registros con fecha 2026-07-10: {hoy}")

        # 3. Mostrar TODAS las fechas presentes
        fechas = db.execute(
            text("SELECT fecha, COUNT(*) as cnt FROM clases GROUP BY fecha ORDER BY fecha")
        ).fetchall()
        print(f"\n3. Distribución por fecha:")
        for f in fechas:
            print(f"   - {f.fecha}: {f.cnt} clases")

        # 4. Primeros 5 registros (sin importar fecha)
        muestras = db.execute(
            text("SELECT id, fecha, hora_inicio, disciplina_id, tenant_id, cancelada FROM clases LIMIT 5")
        ).fetchall()
        print(f"\n4. Muestra de 5 registros:")
        for m in muestras:
            print(f"   id={m.id}, fecha={m.fecha}, hora={m.hora_inicio}, disciplina_id={m.disciplina_id}, tenant_id={m.tenant_id}, cancelada={m.cancelada}")

        # 5. Verificar si existe el tenant_id=1
        tenant = db.execute(
            text("SELECT id, nombre FROM tenants WHERE id = 1")
        ).first()
        print(f"\n5. Tenant ID=1: {dict(tenant) if tenant else 'NO EXISTE'}")

        # 6. Verificar si hay horarios_base activos
        horarios = db.execute(
            text("SELECT COUNT(*) FROM horarios WHERE activo = true AND tenant_id = 1")
        ).scalar()
        print(f"6. Horarios base activos (tenant=1): {horarios}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    diagnosticar()
