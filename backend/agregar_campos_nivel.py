"""
Script para agregar los campos necesarios para el cálculo de nivel:
1. pesos, genero, fecha_nacimiento a usuarios
2. nivel_calculado a historial_rm
"""
from app.db.database import engine, SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    # 1. Agregar columnas a usuarios
    print("Agregando peso_kg, genero, fecha_nacimiento a usuarios...")
    try:
        db.execute(text("ALTER TABLE usuarios ADD COLUMN peso_kg FLOAT"))
        print("  -> peso_kg agregado")
    except Exception as e:
        print(f"  -> peso_kg ya existe o error: {e}")

    try:
        db.execute(text("ALTER TABLE usuarios ADD COLUMN genero VARCHAR(10)"))
        print("  -> genero agregado")
    except Exception as e:
        print(f"  -> genero ya existe o error: {e}")

    try:
        db.execute(text("ALTER TABLE usuarios ADD COLUMN fecha_nacimiento DATE"))
        print("  -> fecha_nacimiento agregado")
    except Exception as e:
        print(f"  -> fecha_nacimiento ya existe o error: {e}")

    # 2. Agregar nivel_calculado a historial_rm
    print("Agregando nivel_calculado a historial_rm...")
    try:
        db.execute(
            text("ALTER TABLE historial_rm ADD COLUMN nivel_calculado VARCHAR(50)"))
        print("  -> nivel_calculado agregado")
    except Exception as e:
        print(f"  -> nivel_calculado ya existe o error: {e}")

    db.commit()
    print("✅ Migración completada")
except Exception as e:
    db.rollback()
    print(f"❌ Error: {e}")
finally:
    db.close()
