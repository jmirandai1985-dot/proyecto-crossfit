"""
Migration directa: Agregar columna categoria a movimientos
Ejecutar CON uvicorn detenido: python backend/migrar_categoria.py
"""
from sqlalchemy import text
from app.db.database import engine
import sys
import os

# Asegurar que backend/ está en el path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))


# Clasificacion de los 55 movimientos
CATEGORIAS = {
    "fuerza": [
        "Snatch", "Clean & Jerk", "Power Snatch", "Power Clean",
        "Back Squat", "Front Squat", "Overhead Squat", "Goblet Squat",
        "Deadlift", "Sumo Deadlift", "Bench Press", "Push Press",
        "Shoulder Press", "Thruster", "Kettlebell Swing",
        "Wall Ball Shot", "Medicine Ball Clean", "Good Morning"
    ],
    "gimnastico": [
        "Pull-up", "Strict Pull-up", "Chest to Bar", "Kipping Pull-up",
        "Butterfly Pull-up", "Bar Muscle-up", "Ring Muscle-up",
        "Push-up", "Handstand Push-up", "Pike Push-up", "Ring Dips",
        "Dips", "Rope Climb", "Toes to Bar", "Knees to Elbows",
        "Handstand Walk", "Wall Walk", "Pistol Squat", "Lunges",
        "Walking Lunge", "Bear Crawl", "Sit-up", "GHD Sit-up",
        "AbMat Sit-up", "V-up", "Hollow Rock", "Plank", "L-sit",
        "Mountain Climber", "Burpee Broad Jump"
    ],
    "cardio": [
        "Burpee", "Burpee Box Jump", "Box Jump", "Box Jump Over",
        "Double Under", "Single Under", "Box Step-up",
        "Sled Push", "Sled Pull", "Farmer Carry"
    ],
    "maquinas": [
        "Assault Bike", "Rowing Machine"
    ],
    "dudosos": [
        "Squat Clean", "Squat Snatch", "Hang Snatch", "Hang Clean",
        "Bulgarian Split Squat", "Romanian Deadlift", "Push Jerk",
        "Dumbbell Bench Press", "Barbell Row", "Pendlay Row",
        "Dumbbell Row", "Ring Row", "Toes to Ring", "Legless Rope Climb",
        "Handstand Shoulder Tap", "Lateral Box Jump", "Handstand Hold"
    ]
}


def main():
    print("== Migracion: Agregar columna categoria a movimientos ==")

    # 1. Leer movimientos actuales
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, nombre FROM movimientos WHERE tenant_id = 1 ORDER BY id"
        )).fetchall()

    print(f"\nMovimientos encontrados: {len(rows)}")
    for rid, rnombre in rows:
        print(f"  ID={rid}: {rnombre}")

    # 2. Agregar columna
    print("\n1. Agregando columna categoria...")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE movimientos ADD COLUMN IF NOT EXISTS categoria VARCHAR(50) DEFAULT 'fuerza'"
        ))
        conn.commit()
    print("   ✅ Columna agregada")

    # 3. Clasificar cada movimiento
    print("\n2. Clasificando movimientos...")
    stats = {}
    for rid, rnombre in rows:
        cat = None
        # Buscar en que categoria esta
        for categoria, nombres in CATEGORIAS.items():
            if rnombre in nombres:
                cat = categoria
                break
        if cat is None:
            # Por defecto: si tiene Snatch/Clean/Squat/Deadlift/Press es fuerza
            n = rnombre.lower()
            if any(k in n for k in ["snatch", "clean", "squat", "deadlift", "press", "jerk",
                                    "row", "bench", "curl", "kettlebell", "thruster",
                                    "dumbbell", "barbell", "extension", "thrust"]):
                cat = "fuerza"
            elif any(k in n for k in ["pull", "muscle", "push", "dip", "rope", "toes",
                                      "knees", "handstand", "wall walk", "lunge",
                                      "crawl", "sit", "ghd", "abmat", "v-up",
                                      "hollow", "plank", "l-sit", "mountain",
                                      "burpee broad", "pistol"]):
                cat = "gimnastico"
            elif any(k in n for k in ["burpee", "box jump", "double under", "single under",
                                      "sled", "farmer", "box step"]):
                cat = "cardio"
            elif any(k in n for k in ["assault bike", "rowing machine", "air bike", "remo",
                                      "bike"]):
                cat = "maquinas"
            else:
                cat = "dudosos"
                print(f"   ⚠️ DUDOSO: {rnombre} -> {cat}")

        with engine.connect() as conn:
            conn.execute(text(
                f"UPDATE movimientos SET categoria = '{cat}' WHERE id = {rid}"
            ))
            conn.commit()
        stats[cat] = stats.get(cat, 0) + 1
        print(f"   ID={rid}: {rnombre} -> {cat}")

    # 4. Resumen
    print("\n" + "=" * 40)
    print("RESUMEN POR CATEGORIA")
    print("=" * 40)
    for cat, cnt in sorted(stats.items()):
        print(f"  {cat}: {cnt}")
    total = sum(stats.values())
    print(f"  TOTAL: {total}")
    print("=" * 40)


if __name__ == "__main__":
    main()
