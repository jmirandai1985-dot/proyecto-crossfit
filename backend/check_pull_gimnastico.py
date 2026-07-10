from sqlalchemy import func
from app.models.historial_rm import HistorialRM
from app.db.database import SessionLocal
from app.models.movimiento import Movimiento
db = SessionLocal()
pull = db.query(Movimiento).filter(
    Movimiento.tenant_id == 1,
    Movimiento.nombre.ilike('%pull%')
).all()
print(f'Movimientos con "pull": {len(pull)}')
for m in pull:
    print(f'  ID:{m.id} Nombre:"{m.nombre}" Categoria:{m.categoria}')

chest = db.query(Movimiento).filter(
    Movimiento.tenant_id == 1,
    Movimiento.nombre.ilike('%chest%')
).all()
print(f'\nMovimientos con "chest": {len(chest)}')
for m in chest:
    print(f'  ID:{m.id} Nombre:"{m.nombre}" Categoria:{m.categoria}')

rms = db.query(HistorialRM.movimiento_id, func.max(HistorialRM.peso_kg), Movimiento.nombre, Movimiento.categoria).filter(
    HistorialRM.tenant_id == 1,
    HistorialRM.alumno_id == 5
).join(Movimiento, HistorialRM.movimiento_id == Movimiento.id).group_by(
    HistorialRM.movimiento_id, Movimiento.nombre, Movimiento.categoria
).all()
print(f'\nRMs del alumno 5: {len(rms)}')
for r in rms:
    print(f'  ID:{r[0]} Nombre:"{r[2]}" Categoria:{r[3]} Peso:{r[1]}')

db.close()
