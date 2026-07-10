from app.db.database import SessionLocal
from app.models.movimiento import Movimiento
db = SessionLocal()
m = db.query(Movimiento).filter(Movimiento.id == 2870).first()
if m:
    print(f'ANTES: id={m.id} nombre="{m.nombre}" cat={m.categoria}')
    m.nombre = "Chest to Bar (C2B)"
    db.commit()
    print(f'DESPUES: id={m.id} nombre="{m.nombre}" cat={m.categoria}')
else:
    print("Movimiento 2870 no encontrado")
db.close()
