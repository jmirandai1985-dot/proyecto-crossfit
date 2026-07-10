"""
Script para agregar 80+ movimientos de CrossFit categorizados.

Ejecutar con el servidor DETENIDO (uvicorn no corriendo).
Luego reiniciar para que SQLAlchemy detecte el nuevo campo 'categoria'.

python backend/agregar_movimientos_completos.py
"""
from sqlalchemy import text
from app.db.database import SessionLocal, engine
from app.models.movimiento import Movimiento
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


TENANT_ID = 1

# Lista de (nombre, descripcion, categoria)
MOVIMIENTOS = [
    # ===== FUERZA - Halterofilia =====
    ("Snatch", "Arrancada olímpica", "fuerza"),
    ("Clean & Jerk", "Envión olímpico", "fuerza"),
    ("Power Snatch", "Snatch de potencia", "fuerza"),
    ("Power Clean", "Clean de potencia", "fuerza"),
    ("Squat Clean", "Clean con sentadilla", "fuerza"),
    ("Squat Snatch", "Snatch con sentadilla", "fuerza"),
    ("Hang Snatch", "Snatch desde hang", "fuerza"),
    ("Hang Clean", "Clean desde hang", "fuerza"),
    ("Muscle Snatch", "Snatch sin sentadilla", "fuerza"),
    ("Muscle Clean", "Clean sin sentadilla", "fuerza"),

    # ===== FUERZA - Sentadillas =====
    ("Back Squat", "Sentadilla trasera con barra", "fuerza"),
    ("Front Squat", "Sentadilla frontal con barra", "fuerza"),
    ("Overhead Squat", "Sentadilla con barra sobre cabeza", "fuerza"),
    ("Goblet Squat", "Sentadilla con pesa rusa al pecho", "fuerza"),
    ("Air Squat", "Sentadilla con peso corporal", "fuerza"),
    ("Bulgarian Split Squat", "Sentadilla búlgara", "fuerza"),
    ("Pistol Squat", "Sentadilla a una pierna", "fuerza"),
    ("Box Squat", "Sentadilla a cajón", "fuerza"),

    # ===== FUERZA - Peso Muerto =====
    ("Deadlift", "Peso muerto convencional", "fuerza"),
    ("Sumo Deadlift", "Peso muerto sumo", "fuerza"),
    ("Romanian Deadlift", "Peso muerto rumano", "fuerza"),
    ("Deficit Deadlift", "Peso muerto con déficit", "fuerza"),
    ("Trap Bar Deadlift", "Peso muerto con barra hexagonal", "fuerza"),

    # ===== FUERZA - Press / Push =====
    ("Bench Press", "Press de banca", "fuerza"),
    ("Push Press", "Press con impulso de piernas", "fuerza"),
    ("Push Jerk", "Envión con salto", "fuerza"),
    ("Split Jerk", "Envión en split", "fuerza"),
    ("Shoulder Press", "Press militar estricto", "fuerza"),
    ("Thruster", "Front squat + push press", "fuerza"),
    ("Incline Bench Press", "Press inclinado", "fuerza"),
    ("Dumbbell Bench Press", "Press con mancuernas", "fuerza"),
    ("Dumbbell Shoulder Press", "Press militar con mancuernas", "fuerza"),

    # ===== FUERZA - Remo / Row =====
    ("Barbell Row", "Remo con barra", "fuerza"),
    ("Pendlay Row", "Remo Pendlay", "fuerza"),
    ("Dumbbell Row", "Remo con mancuerna", "fuerza"),
    ("Ring Row", "Remo en anillas", "fuerza"),

    # ===== FUERZA - Accesorios =====
    ("Kettlebell Swing", "Balanceo de pesa rusa", "fuerza"),
    ("Wall Ball Shot", "Lanzamiento de balón medicinal", "fuerza"),
    ("Medicine Ball Clean", "Clean con balón medicinal", "fuerza"),
    ("Good Morning", "Buenos días con barra", "fuerza"),
    ("Back Extension", "Extensión de espalda", "fuerza"),
    ("Hip Thrust", "Empuje de cadera", "fuerza"),

    # ===== GIMNÁSTICOS - Dominadas =====
    ("Pull-up", "Dominada", "gimnastico"),
    ("Strict Pull-up", "Dominada estricta", "gimnastico"),
    ("Kipping Pull-up", "Dominada con balanceo", "gimnastico"),
    ("Butterfly Pull-up", "Dominada mariposa", "gimnastico"),
    ("Chest to Bar", "Pecho a barra", "gimnastico"),
    ("Chest-to-Bar Pull-up", "Dominada pecho a barra", "gimnastico"),
    ("Chin-up", "Dominada supina", "gimnastico"),

    # ===== GIMNÁSTICOS - Muscle Ups =====
    ("Bar Muscle-up", "Muscle-up en barra", "gimnastico"),
    ("Ring Muscle-up", "Muscle-up en anillas", "gimnastico"),

    # ===== GIMNÁSTICOS - Flexiones =====
    ("Push-up", "Flexión de brazos", "gimnastico"),
    ("Handstand Push-up", "Flexión invertida", "gimnastico"),
    ("Pike Push-up", "Flexión en pike", "gimnastico"),
    ("Ring Push-up", "Flexión en anillas", "gimnastico"),
    ("Clapping Push-up", "Flexión con palmada", "gimnastico"),

    # ===== GIMNÁSTICOS - Fondos =====
    ("Dips", "Fondos en paralelas", "gimnastico"),
    ("Ring Dips", "Fondos en anillas", "gimnastico"),
    ("Bar Dips", "Fondos en barra", "gimnastico"),
    ("Bench Dips", "Fondos en banca", "gimnastico"),

    # ===== GIMNÁSTICOS - Cuerda y Barra =====
    ("Rope Climb", "Trepa de cuerda", "gimnastico"),
    ("Toes to Bar", "Pies a la barra", "gimnastico"),
    ("Knees to Elbows", "Rodillas a codos", "gimnastico"),
    ("Toes to Ring", "Pies a las anillas", "gimnastico"),
    ("Legless Rope Climb", "Trepa sin piernas", "gimnastico"),

    # ===== GIMNÁSTICOS - Parada de Manos =====
    ("Handstand Hold", "Parada de manos estática", "gimnastico"),
    ("Handstand Walk", "Caminata en parada de manos", "gimnastico"),
    ("Wall Walk", "Caminata por pared", "gimnastico"),
    ("Handstand Shoulder Tap", "Parada tocarse hombros", "gimnastico"),

    # ===== GIMNÁSTICOS - Saltos =====
    ("Box Jump", "Salto al cajón", "gimnastico"),
    ("Box Jump Over", "Salto sobre el cajón", "gimnastico"),
    ("Burpee", "Flexión + salto", "gimnastico"),
    ("Burpee Box Jump", "Burpee + salto al cajón", "gimnastico"),
    ("Burpee Over Box", "Burpee sobre cajón", "gimnastico"),

    # ===== GIMNÁSTICOS - Cuerda =====
    ("Double Under", "Doble salto a la cuerda", "gimnastico"),
    ("Single Under", "Salto simple a la cuerda", "gimnastico"),
    ("Triple Under", "Triple salto a la cuerda", "gimnastico"),

    # ===== GIMNÁSTICOS - Abdominales =====
    ("Sit-up", "Abdominal", "gimnastico"),
    ("GHD Sit-up", "Abdominal en GHD", "gimnastico"),
    ("AbMat Sit-up", "Abdominal con tapete", "gimnastico"),
    ("V-up", "Abdominal en V", "gimnastico"),
    ("Hollow Rock", "Balanceo hueco", "gimnastico"),
    ("Plank", "Plancha", "gimnastico"),
    ("L-sit", "L-sit sostenido", "gimnastico"),
    ("Dragon Flag", "Bandera de dragón", "gimnastico"),

    # ===== GIMNÁSTICOS - Varios =====
    ("Lunges", "Zancada", "gimnastico"),
    ("Walking Lunge", "Zancada caminando", "gimnastico"),
    ("Reverse Lunge", "Zancada hacia atrás", "gimnastico"),
    ("Bear Crawl", "Gateo de oso", "gimnastico"),
    ("Mountain Climber", "Escalador", "gimnastico"),
    ("Burpee Broad Jump", "Burpee + salto largo", "gimnastico"),

    # ===== CARDIO =====
    ("Rowing Machine", "Remo en máquina", "cardio"),
    ("Assault Bike", "Bicicleta de asalto", "cardio"),
    ("Ski Erg", "Máquina de esquí", "cardio"),
    ("Air Runner", "Cinta sin motor", "cardio"),
    ("Sled Push", "Empuje de trineo", "cardio"),
    ("Sled Pull", "Tracción de trineo", "cardio"),
    ("Farmer Carry", "Carga del granjero", "cardio"),
    ("Sandbag Carry", "Carga de saco", "cardio"),
    ("Running 400m", "Carrera 400 metros", "cardio"),
    ("Running 800m", "Carrera 800 metros", "cardio"),
    ("Running 1km", "Carrera 1 kilómetro", "cardio"),
    ("Running 5km", "Carrera 5 kilómetros", "cardio"),
]


def main():
    db = SessionLocal()

    # Eliminar movimientos existentes del tenant
    print("Eliminando movimientos viejos...")
    db.query(Movimiento).filter(Movimiento.tenant_id == TENANT_ID).delete()

    # Insertar nuevos movimientos
    print(f"Insertando {len(MOVIMIENTOS)} movimientos...")
    for nombre, descripcion, categoria in MOVIMIENTOS:
        mov = Movimiento(
            tenant_id=TENANT_ID,
            nombre=nombre,
            descripcion=descripcion,
            categoria=categoria,
            activo=True
        )
        db.add(mov)

    db.commit()
    print(f"✅ {len(MOVIMIENTOS)} movimientos insertados correctamente")

    # Verificar
    total = db.query(Movimiento).filter(
        Movimiento.tenant_id == TENANT_ID).count()
    por_cat = db.query(Movimiento.categoria, Movimiento.id).filter(
        Movimiento.tenant_id == TENANT_ID).all()
    print(f"\nTotal en BD: {total}")
    cats = {}
    for c, _ in por_cat:
        cats[c] = cats.get(c, 0) + 1
    for cat, cnt in sorted(cats.items()):
        print(f"  {cat}: {cnt} movimientos")

    db.close()


if __name__ == "__main__":
    main()
