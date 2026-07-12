"""
Script de migración para agregar campos de certificado estudiante.
Ejecutar con: python _migrar_certificado_estudiante.py
"""
from sqlalchemy import text
from app.db.database import engine
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def migrar():
    print("🚀 Migrando: Agregar campos de certificado estudiante...")

    with engine.connect() as conn:
        # 1. requiere_certificado_estudiante en planes
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'planes' AND column_name = 'requiere_certificado_estudiante'"
        ))
        if not result.fetchone():
            conn.execute(text(
                "ALTER TABLE planes ADD COLUMN requiere_certificado_estudiante BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            print("✅ Columna requiere_certificado_estudiante agregada a planes")
        else:
            print("✅ requiere_certificado_estudiante ya existe en planes")

        # 2. certificado_estudiante_url en solicitudes_planes
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'solicitudes_planes' AND column_name = 'certificado_estudiante_url'"
        ))
        if not result.fetchone():
            conn.execute(text(
                "ALTER TABLE solicitudes_planes ADD COLUMN certificado_estudiante_url TEXT"
            ))
            print("✅ Columna certificado_estudiante_url agregada a solicitudes_planes")
        else:
            print("✅ certificado_estudiante_url ya existe en solicitudes_planes")

        conn.commit()

    print("🎉 Migración completada exitosamente")


if __name__ == "__main__":
    migrar()
