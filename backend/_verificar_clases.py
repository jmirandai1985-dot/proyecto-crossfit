"""Verificar clases en BD para los 5 días"""
from app.db.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    fechas = ['2026-07-11', '2026-07-12',
              '2026-07-13', '2026-07-14', '2026-07-15']
    print('=== CLASES EN BD POR FECHA ===')
    for f in fechas:
        count = db.execute(
            text("SELECT COUNT(*) FROM clases WHERE tenant_id=1 AND fecha=:f"),
            {"f": f}
        ).scalar()
        print(f"  {f}: {count} clases")
finally:
    db.close()
