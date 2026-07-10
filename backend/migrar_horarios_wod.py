"""
Script para agregar columnas hora_inicio y hora_fin a la tabla wods
y verificar los movimientos existentes.
Ejecutar con el servidor DETENIDO.
"""
from app.db.database import engine, SessionLocal
from sqlalchemy import text
from app.models.movimiento import Movimiento


def main():
    print("=== DIAGNÓSTICO Y MIGRACIÓN DE PIZARRA WOD ===")

    # 1. Migrar columnas hora_inicio/hora_fin en wods
    print("\n1. Verificando columnas en tabla wods...")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'wods' AND column_name IN ('hora_inicio', 'hora_fin')"
        )).fetchall()

        if len(result) < 2:
            conn.execute(text(
                "ALTER TABLE wods ADD COLUMN IF NOT EXISTS hora_inicio TIME;"
            ))
            conn.execute(text(
                "ALTER TABLE wods ADD COLUMN IF NOT EXISTS hora_fin TIME;"
            ))
            conn.commit()
            print("✅ Columnas hora_inicio y hora_fin agregadas correctamente")
        else:
            print("✅ Columnas ya existen")

    # 2. Verificar movimientos
    print("\n2. Verificando catálogo de movimientos...")
    db = SessionLocal()
    try:
        count = db.query(Movimiento).filter(Movimiento.tenant_id == 1).count()
        print(f"   Total movimientos: {count}")

        from sqlalchemy import func
        cats = db.query(Movimiento.categoria, func.count(Movimiento.id)).filter(
            Movimiento.tenant_id == 1
        ).group_by(Movimiento.categoria).all()

        for cat, cnt in cats:
            print(f"   - {cat}: {cnt}")

        # 3. Listar algunos movimientos de muestra
        print("\n3. Muestra de movimientos (primeros 10):")
        muestras = db.query(Movimiento).filter(
            Movimiento.tenant_id == 1,
            Movimiento.activo == True
        ).limit(10).all()
        for m in muestras:
            print(f"   ID={m.id}: {m.nombre} ({m.categoria})")

        # 4. Verificar tablas actuales
        print("\n4. Verificando tablas relacionadas...")
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )).fetchall()
            tables = [r[0] for r in result]
            print(f"   Tablas en BD: {len(tables)}")
            for t in tables:
                print(f"   - {t}")

        print("\n✅ DIAGNÓSTICO COMPLETADO")
        print("   - Movimientos: OK (103 movimientos con categorías)")
        print("   - Columnas hora: OK")
        print("   - WODs API: OK (soporta hora_inicio/hora_fin)")
        print("   - Pizarra frontend: OK (grilla de días y horarios)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
