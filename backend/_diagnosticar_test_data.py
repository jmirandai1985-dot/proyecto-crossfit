"""
DIAGNÓSTICO: Busca todos los registros de prueba creados por los tests
en la BD de producción. No borra nada, solo LISTA.
Ejecutar con la API corriendo: uvicorn app.main:app
"""
import os
import sys
from sqlalchemy import text, create_engine

# Cargar .env manualmente para obtener DATABASE_URL
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

DATABASE_URL = os.getenv("DATABASE_URL")
print(f"\n🔍 Buscando datos de prueba en: {DATABASE_URL[:60]}...\n")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

PATRONES = ["TEST fuerza", "TEST gimnastico", "TEST cardio",
            "TEST maquinas", "TEST WOD", "TEST automatico",
            "TEST maquinas nuevo"]

with engine.connect() as conn:
    # 1. historial_rm
    print("=" * 70)
    print("📋 historial_rm (RMs de prueba)")
    print("=" * 70)
    for patron in PATRONES:
        rows = conn.execute(
            text("SELECT id, alumno_id, movimiento_id, peso_kg, fecha, notas "
                 "FROM historial_rm WHERE notas ILIKE :patron"),
            {"patron": f"%{patron}%"}
        ).fetchall()
        for r in rows:
            print(f"  id={r[0]} alumno={r[1]} mov_id={r[2]} "
                  f"peso={r[3]} fecha={r[4]} notas='{r[5]}'")

    # 2. wods
    print("\n" + "=" * 70)
    print("📋 wods (WODs de prueba)")
    print("=" * 70)
    rows = conn.execute(
        text("SELECT id, tenant_id, fecha, titulo, descripcion, estado "
             "FROM wods WHERE titulo ILIKE '%TEST%' OR descripcion ILIKE '%TEST%'")
    ).fetchall()
    for r in rows:
        print(f"  id={r[0]} tenant={r[1]} fecha={r[2]} titulo='{r[3]}' "
              f"desc='{r[4]}' estado={r[5]}")

    # 3. reservas
    print("\n" + "=" * 70)
    print("📋 reservas (vinculadas a clases con WODs TEST)")
    print("=" * 70)
    rows = conn.execute(
        text("SELECT r.id, r.alumno_id, r.clase_id, r.estado, r.asistio, c.fecha "
             "FROM reservas r JOIN clases c ON r.clase_id = c.id "
             "WHERE r.id IN ("
             "  SELECT r2.id FROM reservas r2 "
             "  JOIN clases c2 ON r2.clase_id = c2.id "
             "  WHERE c2.fecha >= CURRENT_DATE - INTERVAL '7 days'"
             ") AND r.alumno_id = 5 "
             "ORDER BY r.id DESC LIMIT 10")
    ).fetchall()
    for r in rows:
        print(f"  id={r[0]} alumno={r[1]} clase={r[2]} estado={r[3]} "
              f"asistio={r[4]} fecha_clase={r[5]}")

    # 4. Total por tipo
    print("\n" + "=" * 70)
    print("📊 RESUMEN - Conteo de registros TEST")
    print("=" * 70)
    total_test_rms = 0
    for patron in PATRONES:
        count = conn.execute(
            text("SELECT COUNT(*) FROM historial_rm WHERE notas ILIKE :patron"),
            {"patron": f"%{patron}%"}
        ).scalar()
        if count > 0:
            total_test_rms += count
            print(f"  historial_rm con '{patron}': {count}")
    wod_count = conn.execute(
        text("SELECT COUNT(*) FROM wods WHERE titulo ILIKE '%TEST%'")
    ).scalar()
    print(f"  wods con 'TEST': {wod_count}")
    print(f"\n  TOTAL registros de prueba: {total_test_rms + wod_count}")

print("\n✅ Diagnóstico completado. No se borró nada.")
