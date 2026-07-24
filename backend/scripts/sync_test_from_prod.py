"""
Sync PROD to TEST via TRUNCATE CASCADE + INSERT.
"""
from sqlalchemy import create_engine, MetaData, Table, text
from sqlalchemy.sql import insert
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ["ENVIRONMENT"] = "test"

PROD_URL = 'postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
TEST_URL = 'postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-curly-rain-acg2z9h1-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

pe = create_engine(PROD_URL)
te = create_engine(TEST_URL, isolation_level='AUTOCOMMIT')

TABLES = ['tenants', 'movimientos', 'disciplinas', 'planes', 'horarios',
          'usuarios', 'suscripciones', 'productos', 'clases', 'reservas',
          'pedidos', 'wods', 'wod_movimientos', 'asistencias', 'historial_rm', 'notificaciones']

print('TRUNCATE CASCADE TEST...')
with te.connect() as c:
    c.execute(text(f'TRUNCATE TABLE {", ".join(TABLES)} CASCADE'))
    c.execute(text('TRUNCATE TABLE solicitudes_planes CASCADE'))
print('TEST limpia')

print('\Copiando PROD->TEST...')
pc = pe.connect()
for tbl in TABLES:
    tbl_obj = Table(tbl, MetaData(), autoload_with=pe)
    rows = pc.execute(tbl_obj.select()).fetchall()
    if not rows:
        continue
    dicts = [dict(r._mapping) for r in rows]
    with te.connect() as tc:
        tc.execute(insert(tbl_obj), dicts)
    print(f'  {tbl}: {len(rows)}')
pc.close()

print('\nVERIFICACION:')
with te.connect() as c:
    for tbl in TABLES:
        cnt = c.execute(text(f'SELECT COUNT(*) FROM {tbl}')).fetchone()[0]
        if cnt:
            print(f'  {tbl}: {cnt}')
print('SYNC COMPLETE')
