"""
SANITIZAR: Reemplazar contrasena vieja (npg_uFlE47iJbMgn) por la nueva
ROTADA por el usuario en Neon (npg_dgH4Goce5DkB) en todos los archivos .py
"""
import os

root = os.path.dirname(os.path.abspath(__file__))
OLD = '***ELIMINADA***'
NEW = '***LEER DESDE .env***'

files = [
    'check_cols.py', 'check_horarios_base.py', 'create_tables.py',
    'fix_toes_to_bar.py', 'insertar_alumno.py', 'insertar_maquinas.py',
    'run_setup_test_db.py', 'test_db_simple.py',
    '_diagnosticar_creditos.py', '_fix_creditos_final.py',
    '_setup_test_db.py', '_traza_reservas.py'
]

count = 0
for f in files:
    fp = os.path.join(root, f)
    if not os.path.exists(fp):
        print("NOT FOUND: " + f)
        continue
    with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
        content = fh.read()
    if OLD in content:
        content = content.replace(OLD, NEW)
        with open(fp, 'w', encoding='utf-8') as fh:
            fh.write(content)
        print("UPDATED: " + f)
        count += 1
    else:
        print("NO CHANGE: " + f)

print()
print("Total actualizados: " + str(count))
print("OFF PASSWORD: " + OLD)
print("NEW PASSWORD: " + NEW)
