"""
Script para agregar la columna valor_extra a la tabla historial_rm
"""
from app.db.database import engine
from sqlalchemy import text
import os
import sys

# Agregar backend al path para poder importar app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


SQL_ADD_COLUMN = """
ALTER TABLE historial_rm 
ADD COLUMN IF NOT EXISTS valor_extra VARCHAR(100);
"""

SQL_VERIFY = """
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'historial_rm' 
ORDER BY ordinal_position;
"""

if __name__ == "__main__":
    print("=" * 60)
    print("  AGREGANDO COLUMNA valor_extra a historial_rm")
    print("=" * 60)

    try:
        with engine.connect() as conn:
            # Verificar columnas actuales
            result = conn.execute(text(SQL_VERIFY))
            print("\nColumnas actuales en historial_rm:")
            print("-" * 50)
            for row in result:
                print(
                    f"  {row.column_name:20s} {row.data_type:15s} {row.is_nullable}")

            # Agregar columna
            print("\nAgregando columna valor_extra...")
            conn.execute(text(SQL_ADD_COLUMN))
            conn.commit()
            print("✅ Columna valor_extra agregada exitosamente!")

            # Verificar después
            result = conn.execute(text(SQL_VERIFY))
            print("\nColumnas después del cambio:")
            print("-" * 50)
            for row in result:
                print(
                    f"  {row.column_name:20s} {row.data_type:15s} {row.is_nullable}")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    print("\n✅ Script completado")
