"""Check complete movement catalog in BD"""
import psycopg2
from dotenv import load_dotenv
import sys
import os
import re
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

load_dotenv()

url = os.getenv('DATABASE_URL', '')
url = re.sub(r'&channel_binding=[^&]+', '', url)

conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute(
    "SELECT id, nombre, categoria FROM movimientos WHERE tenant_id=1 ORDER BY nombre")
rows = cur.fetchall()
print(f"TOTAL: {len(rows)} movimientos\n")
for r in rows:
    print(f"  ID={r[0]:4d} cat={r[2]:15s} \"{r[1]}\"")

print("\n--- Buscando movimientos basicos que PODRIAN faltar ---")
basicos = ["Push Press", "Push Press", "Strict Press", "Shoulder Press", "Thruster",
           "Wall Ball", "Kettlebell Swing", "Dumbbell Snatch", "Dumbbell Clean",
           "Goblet Squat", "Air Squat", "Lunge", "Walking Lunge", "Sit-up",
           "Hollow Rock", "Plank", "Dumbbell Bench", "Bench Press", "Barbell Row",
           "Power Clean", "Power Snatch", "Hang Clean", "Hang Snatch", "Split Jerk",
           "Ski Erg", "Assault Bike", "Calories", "Rowing", "Farmers Walk"]
for b in basicos:
    cur.execute(
        "SELECT id, nombre FROM movimientos WHERE tenant_id=1 AND nombre ILIKE %s", (f'%{b}%',))
    res = cur.fetchone()
    if res:
        print(f"  OK: '{b}' -> encontrado como \"{res[1]}\" (ID={res[0]})")
    else:
        print(f"  MISSING: '{b}' NO encontrado en BD")

cur.close()
conn.close()
