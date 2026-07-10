from app.db.database import SessionLocal
from app.models.movimiento import Movimiento
db = SessionLocal()
movs = db.query(Movimiento).filter(
    Movimiento.tenant_id == 1,
    Movimiento.nombre.in_(['Assault Bike', 'Rowing Machine'])
).all()
for m in movs:
    print(
        f'id={m.id} | nombre="{m.nombre}" | categoria="{m.categoria}" | activo={m.activo}')
db.close()
