"""
Fix: Update movement names in DB to match CROSSFIT_RATIOS and CROSSFIT_HABILIDADES keys.
This ensures the nivel calculation works correctly.
"""
from app.services.nivel_service import calcular_nivel_general
from sqlalchemy import func
from app.models.historial_rm import HistorialRM
from app.db.database import SessionLocal
from app.models.movimiento import Movimiento
from app.db.crossfit_ratios import CROSSFIT_RATIOS
from app.db.crossfit_habilidades import CROSSFIT_HABILIDADES

db = SessionLocal()

# Get all movements from this tenant
movimientos = db.query(Movimiento).filter(Movimiento.tenant_id == 1).all()

# Build reverse mapping: simple name -> full crossfit table name
# e.g. 'Snatch' -> 'Snatch (Arrancada)'
simple_to_full = {
    'snatch': 'Snatch (Arrancada)',
    'clean': 'Clean (Cargada)',
    'deadlift': 'Deadlift (Peso Muerto)',
    'jerk': 'Jerk (Envión)',
    'thruster': 'Thruster',
    'back squat': 'Back Squat (Sentadilla Trasera)',
    'front squat': 'Front Squat (Sentadilla Frontal)',
    'overhead squat': 'Overhead Squat (Sentadilla Over-Head)',
    'pull-ups': 'Pull-ups (Dominadas)',
    'chest to bar': 'Chest to Bar (C2B)',
    'toes to bar': 'Toes to Bar (T2B)',
    'bar muscle-up': 'Bar Muscle-up (BMU)',
    'ring muscle-up': 'Ring Muscle-up (RMU)',
    'handstand push-ups': 'Handstand Push-ups / HSPU',
    'double unders': 'Double Unders / DU',
    'pistol squat': 'Pistol Squat',
    'burpees': 'Burpees',
    'wall balls': 'Wall Balls',
    'box jumps': 'Box Jumps',
    'kettlebell swing': 'Kettlebell Swing',
    'rope climb': 'Rope Climb (Trepada)',
    'handstand walk': 'Handstand Walk / HSW',
    'bear crawl': 'Bear Crawl (Caminata)',
    'farmer carry': 'Farmer Carry (Carga)',
    'clean & jerk': 'Clean (Cargada)',  # Complex -> use Clean
}

all_keys_lower = {k.lower(): k for k in list(
    CROSSFIT_RATIOS.keys()) + list(CROSSFIT_HABILIDADES.keys())}

updated_count = 0
for mov in movimientos:
    name_lower = mov.nombre.lower().strip()

    # Try exact match first
    if name_lower in all_keys_lower:
        new_name = all_keys_lower[name_lower]
        if mov.nombre != new_name:
            print(f'[{mov.id}] "{mov.nombre}" -> "{new_name}"')
            mov.nombre = new_name
            updated_count += 1
        continue

    # Try simple name mapping
    if name_lower in simple_to_full:
        new_name = simple_to_full[name_lower]
        if mov.nombre != new_name:
            print(f'[{mov.id}] "{mov.nombre}" -> "{new_name}"')
            mov.nombre = new_name
            updated_count += 1
        continue

    # Try substring matching
    for key_lower, full_name in all_keys_lower.items():
        if name_lower in key_lower or key_lower in name_lower:
            if mov.nombre != full_name:
                print(
                    f'[{mov.id}] "{mov.nombre}" -> "{full_name}" (partial match: "{key_lower}")')
                mov.nombre = full_name
                updated_count += 1
            break

db.commit()

print(f'\nTotal actualizados: {updated_count}')
print(f'Total movimientos tenant=1: {len(movimientos)}')

# Verify by testing a nivel calculation
print('\n--- Test nivel calculation for alumno=5 ---')

result = calcular_nivel_general(5, db, 1)
print(f'nivel_fuerza: {result["nivel_fuerza"]}')
print(f'nivel_gimnastico: {result["nivel_gimnastico"]}')
print(f'detalle_fuerza: {len(result["detalle_fuerza"])} items')
for d in result['detalle_fuerza']:
    print(f'  - {d["movimiento"]}: {d["nivel"]}')
print(f'detalle_gimnastico: {len(result["detalle_gimnastico"])} items')
for d in result['detalle_gimnastico']:
    print(f'  - {d["movimiento"]}: {d["nivel"]}')

db.close()
