"""
Script de migración para agregar columna 'genero' a la tabla 'planes'
Ejecutar con: python _migrar_genero_planes.py
"""
from sqlalchemy import text
from app.db.database import engine
import os
import sys

# Asegurar que podemos importar desde app/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def migrar():
    print("🚀 Migrando: Agregar columna 'genero' a tabla 'planes'...")

    with engine.connect() as conn:
        # Verificar si la columna ya existe
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'planes' AND column_name = 'genero'"
        ))
        if result.fetchone():
            print("✅ La columna 'genero' ya existe. Saltando...")
            return

        # Agregar columna
        conn.execute(text(
            "ALTER TABLE planes ADD COLUMN genero VARCHAR(20)"
        ))
        print("✅ Columna 'genero' agregada a la tabla 'planes'")

        # Crear índice
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_planes_genero ON planes (genero)"
        ))
        print("✅ Índice ix_planes_genero creado")

        conn.commit()

    print("🎉 Migración completada exitosamente")


if __name__ == "__main__":
    migrar()
