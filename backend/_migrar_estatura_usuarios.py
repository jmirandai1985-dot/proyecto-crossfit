"""
Script de migración para agregar estatura_cm a usuarios.
Ejecutar con: python _migrar_estatura_usuarios.py
"""
from sqlalchemy import text
from app.db.database import engine
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def migrar():
    print("🚀 Migrando: Agregar estatura_cm a usuarios...")

    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'usuarios' AND column_name = 'estatura_cm'"
        ))
        if result.fetchone():
            print("✅ estatura_cm ya existe. Saltando...")
            return

        conn.execute(text(
            "ALTER TABLE usuarios ADD COLUMN estatura_cm INTEGER"
        ))
        print("✅ Columna estatura_cm agregada a usuarios")
        conn.commit()

    print("🎉 Migración completada exitosamente")


if __name__ == "__main__":
    migrar()
