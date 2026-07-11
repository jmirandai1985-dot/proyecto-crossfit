"""
Script temporal para diagnosticar horarios_base del sábado y clases de hoy
"""
from sqlalchemy import text
from app.db.database import SessionLocal
import sys
sys.path.insert(0, '.')
db = SessionLocal()
try:
    # First check what columns actually exist
    tables = ['horarios', 'clases', 'reservas']
    for table in tables:
        rows = db.execute(text(
            f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position"
        )).fetchall()
        print(f'=== COLUMNAS DE {table} ===')
        for r in rows:
            print(f'  {r.column_name} ({r.data_type})')
        print()

    # Now check horarios for Saturday (dia_semana=5)
    rows = db.execute(text(
        'SELECT * FROM horarios WHERE dia_semana = 5 ORDER BY hora_inicio')).fetchall()
    print('=== HORARIOS BASE SÁBADO (dia_semana=5) ===')
    for r in rows:
        print(dict(r._mapping))

    # Check disciplinas
    rows2 = db.execute(text(
        'SELECT id, nombre FROM disciplinas')).fetchall()
    print('\n=== DISCIPLINAS ===')
    for r in rows2:
        print(dict(r._mapping))

    # Check today's classes
    from datetime import date, timedelta
    hoy = date.today()
    manana = hoy + timedelta(days=1)
    pasado = hoy + timedelta(days=2)
    print(f'\n=== CLASES PARA HOY ({hoy}) ===')
    rows3 = db.execute(text('SELECT * FROM clases WHERE fecha = :fecha AND tenant_id = 1 ORDER BY hora_inicio'),
                       {'fecha': hoy}).fetchall()
    for r in rows3:
        print(dict(r._mapping))

    # Check reservas for today's classes
    if rows3:
        clase_ids = [r.id for r in rows3]
        if clase_ids:
            placeholders = ','.join([':id' + str(i)
                                    for i in range(len(clase_ids))])
            params = {}
            for i, cid in enumerate(clase_ids):
                params['id' + str(i)] = cid
            rows4 = db.execute(text(
                f'SELECT clase_id, COUNT(*) as cnt FROM reservas WHERE clase_id IN ({placeholders}) GROUP BY clase_id'), params).fetchall()
            if rows4:
                print('\n=== RESERVAS EN CLASES DE HOY ===')
                for r in rows4:
                    print(dict(r._mapping))
            else:
                print('\n  (sin reservas en clases de hoy)')

    # Also check next 2 days
    for dia_futuro, label in [(manana, 'MAÑANA'), (pasado, 'PASADO MAÑANA')]:
        print(f'\n=== CLASES PARA {label} ({dia_futuro}) ===')
        rows_fut = db.execute(text('SELECT * FROM clases WHERE fecha = :fecha AND tenant_id = 1 ORDER BY hora_inicio'),
                              {'fecha': dia_futuro}).fetchall()
        if rows_fut:
            for r in rows_fut:
                print(dict(r._mapping))
        else:
            print('  (sin clases generadas)')
finally:
    db.close()
