"""
One-shot: Generar clases faltantes para Martes 14 y Miercoles 15
Ejecutar: python _generar_faltantes.py
"""
from datetime import date
from app.services.generar_clases import generar_clases_para_rango
from app.db.database import SessionLocal
import sys
sys.path.insert(0, '.')

db = SessionLocal()
try:
    print(
        "Generando clases faltantes para el rango [2026-07-14, 2026-07-15]...")
    resultado = generar_clases_para_rango(
        db, tenant_id=1, fecha_desde=date(2026, 7, 14), fecha_hasta=date(2026, 7, 15))
    print("  Creadas:", resultado["creadas"])
    print("  Omitidas:", resultado["omitidas"])
    print("  Fechas procesadas:", resultado["fechas_procesadas"])
    print("  Message:", resultado["message"])
finally:
    db.close()
