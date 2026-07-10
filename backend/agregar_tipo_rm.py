"""
Script para agregar columna tipo_rm a la tabla historial_rm
Ejecutar: python agregar_tipo_rm.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, text
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    # Agregar columna tipo_rm si no existe
    try:
        conn.execute(text("""
            ALTER TABLE historial_rm 
            ADD COLUMN IF NOT EXISTS tipo_rm VARCHAR(20) NOT NULL DEFAULT 'peso'
        """))
        print("✅ Columna tipo_rm agregada a historial_rm")
    except Exception as e:
        print(f"⚠️ Error al agregar tipo_rm: {e}")

    # Agregar columna valor_extra para almacenar reps, tiempo, etc.
    try:
        conn.execute(text("""
            ALTER TABLE historial_rm 
            ADD COLUMN IF NOT EXISTS valor_extra VARCHAR(100)
        """))
        print("✅ Columna valor_extra agregada a historial_rm")
    except Exception as e:
        print(f"⚠️ Error al agregar valor_extra: {e}")

    conn.commit()
    print("✅ Migración completada")