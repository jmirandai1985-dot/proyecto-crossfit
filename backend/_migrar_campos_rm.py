"""
Script de migración para agregar campos estructurados a historial_rm.
Ejecutar con: python _migrar_campos_rm.py
"""
from sqlalchemy import text
from app.db.database import engine
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def migrar():
    print("🚀 Migrando: Agregar campos estructurados a historial_rm...")

    with engine.connect() as conn:
        # Verificar si las columnas ya existen
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'historial_rm' AND column_name = 'repeticiones'"
        ))
        if result.fetchone():
            print("✅ Los campos ya existen. Saltando...")
            return

        # Agregar columnas
        conn.execute(text(
            "ALTER TABLE historial_rm ADD COLUMN repeticiones INTEGER"
        ))
        conn.execute(text(
            "ALTER TABLE historial_rm ADD COLUMN series INTEGER"
        ))
        conn.execute(text(
            "ALTER TABLE historial_rm ADD COLUMN minutos INTEGER"
        ))
        conn.execute(text(
            "ALTER TABLE historial_rm ADD COLUMN vueltas INTEGER"
        ))
        conn.execute(text(
            "ALTER TABLE historial_rm ADD COLUMN km DOUBLE PRECISION"
        ))
        conn.execute(text(
            "ALTER TABLE historial_rm ADD COLUMN calorias INTEGER"
        ))
        print("✅ Columnas agregadas a historial_rm")

        # Migrar valor_extra con formato "NxM" a series/repeticiones
        conn.execute(text("""
            UPDATE historial_rm 
            SET series = CAST(SPLIT_PART(valor_extra, 'x', 1) AS INTEGER),
                repeticiones = CAST(SPLIT_PART(valor_extra, 'x', 2) AS INTEGER)
            WHERE valor_extra ~ '^[0-9]+x[0-9]+$'
        """))
        print("✅ Datos existentes migrados (valor_extra -> series/repeticiones)")

        conn.commit()

    print("🎉 Migración completada exitosamente")


if __name__ == "__main__":
    migrar()
