from sqlalchemy import create_engine, text
import importlib
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.environ['ENVIRONMENT'] = 'test'
settings = importlib.import_module('app.core.config').settings
url = settings.DATABASE_URL.replace(
    '?sslmode=require&channel_binding=require', '?sslmode=require')
engine = create_engine(url)
with engine.connect() as conn:
    r = conn.execute(text('SELECT id, nombre, es_open_box FROM disciplinas'))
    rows = r.fetchall()
    print(f'Disciplinas en TEST DB: {len(rows)}')
    for row in rows:
        print(f'  id={row[0]}, nombre="{row[1]}", es_open_box={row[2]}')
