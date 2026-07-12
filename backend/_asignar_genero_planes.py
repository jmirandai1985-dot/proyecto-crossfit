"""
Script para asignar el campo 'genero' a los 16 planes existentes.
Ejecutar DESPUÉS de aplicar la migración que agrega la columna 'genero'.

Uso: python _asignar_genero_planes.py
"""
from sqlalchemy import text
from app.models.plan import Plan
from app.db.database import SessionLocal
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


FEMENINO = [
    "Princesa", "Vikinga", "Super Woman", "Diosa Griega",
    "Girly", "Aesthetic", "Influencer", "Bichota"
]

MASCULINO = [
    "Baby Chimp", "Simio", "Gorila", "Alpha",
    "King Kong", "Diddy Kong", "Donkey Kong", "Brocoli"
]

# Planes que requieren certificado de estudiante
PLANES_ESTUDIANTE = [
    "Brocoli", "Diddy Kong", "Donkey Kong",  # Masculinos
    "Girly", "Aesthetic", "Influencer"        # Femeninos
]


def asignar():
    db = SessionLocal()
    try:
        planes = db.query(Plan).filter(Plan.tenant_id == 1).all()
        print(f"📋 Total planes encontrados: {len(planes)}")
        genero_actualizados = 0
        estudiante_actualizados = 0

        for plan in planes:
            # Asignar género
            if plan.nombre in FEMENINO:
                plan.genero = "femenino"
                print(f"  ♀️  {plan.nombre} → femenino")
                genero_actualizados += 1
            elif plan.nombre in MASCULINO:
                plan.genero = "masculino"
                print(f"  ♂️  {plan.nombre} → masculino")
                genero_actualizados += 1
            else:
                print(
                    f"  ❓ {plan.nombre} → SIN CLASIFICAR (no está en las listas)")

            # Asignar certificado estudiante
            if plan.nombre in PLANES_ESTUDIANTE:
                plan.requiere_certificado_estudiante = True
                print(f"  🎓 {plan.nombre} → requiere certificado estudiante")
                estudiante_actualizados += 1

        db.commit()
        print(f"\n✅ {genero_actualizados} planes actualizados con su género")
        print(
            f"✅ {estudiante_actualizados} planes marcados como 'requiere certificado'")
        print(f"❌ {len(planes) - genero_actualizados} planes sin clasificar género")
    finally:
        db.close()


if __name__ == "__main__":
    asignar()
