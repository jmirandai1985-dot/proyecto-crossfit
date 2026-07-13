"""
Diagnóstico rápido de WODs y disciplinas en BD de producción.
"""
from sqlalchemy import create_engine, text
import os
import sys
import importlib

# MUST be before any app import
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
os.chdir(base)
os.environ["ENVIRONMENT"] = ""

# Import after setting environment
settings = importlib.import_module("app.core.config").settings


url = settings.DATABASE_URL.replace(
    '?sslmode=require&channel_binding=require', '?sslmode=require')
engine = create_engine(url)

with engine.connect() as conn:
    # 1. COUNT de wods
    r = conn.execute(text('SELECT COUNT(*) FROM wods'))
    total_wods = r.scalar()
    print(f'[QUERY 1] WODs existentes en produccion: {total_wods}')

    # 2. WODs con movimientos estructurados (formato viejo)
    r = conn.execute(text(
        'SELECT COUNT(DISTINCT w.id) FROM wods w INNER JOIN wod_movimientos wm ON w.id = wm.wod_id'))
    wods_con_movs = r.scalar()
    print(f'[QUERY 1b] WODs con movimientos estructurados: {wods_con_movs}')

    # 3. Disciplinas
    r = conn.execute(
        text('SELECT id, nombre, es_open_box, activo FROM disciplinas ORDER BY id'))
    print('[QUERY 2] Disciplinas:')
    for row in r:
        print(
            f'   id={row[0]}, nombre="{row[1]}", es_open_box={row[2]}, activo={row[3]}')

print('Hecho.')
