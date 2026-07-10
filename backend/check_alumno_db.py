"""
Verifica datos del alumno 5 en BD
"""
from app.db.database import SessionLocal
from app.models.usuario import Usuario

db = SessionLocal()
alumno = db.query(Usuario).filter(Usuario.id == 5).first()
if alumno:
    print(f"ID: {alumno.id}")
    print(f"Nombre: {alumno.nombre}")
    print(f"peso_kg: {alumno.peso_kg}")
    print(f"genero: {alumno.genero}")
else:
    print("Alumno no encontrado")
db.close()
