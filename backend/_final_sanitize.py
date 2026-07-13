"""
Refactor FINAL: reemplazar conexiones hardcodeadas (postgresql://user:pass@...)
por settings.DATABASE_URL en todos los archivos.
NO comitea - solo modifica los archivos en disco.
"""
import os
import re

root = os.path.dirname(os.path.abspath(__file__))

# Mapeo de archivo -> (lineas a eliminar, lineas a agregar)
# Cada entrada: (regex_a_buscar, reemplazo_con_settings)

files_to_fix = {
    'check_cols.py': {
        'old_pattern': r"'postgresql://neondb_owner:[^']+@[^']+'",
        'new_line': "from app.core.config import settings\nconn_str = settings.DATABASE_URL.replace('?sslmode=require&channel_binding=require', '?sslmode=require')\n",
        'replace_with': "conn_str"
    },
    'check_horarios_base.py': {
        'old_pattern': r"'postgresql://neondb_owner:[^']+@[^']+'",
        'new_line': "from app.core.config import settings\nconn_str = settings.DATABASE_URL.replace('?sslmode=require&channel_binding=require', '?sslmode=require')\n",
        'replace_with': "conn_str"
    },
    'create_tables.py': {
        'old_pattern': r'DATABASE_URL = "postgresql://neondb_owner:[^"]+@[^"]+"',
        'new_line': "from app.core.config import settings\nDATABASE_URL = settings.DATABASE_URL\n",
        'replace_with': "# DATABASE_URL ahora se obtiene de settings"
    },
    'fix_toes_to_bar.py': {
        'old_pattern': r'DATABASE_URL = "postgresql://neondb_owner:[^"]+@[^"]+"',
        'new_line': "from app.core.config import settings\nDATABASE_URL = settings.DATABASE_URL\n",
        'replace_with': "# DATABASE_URL ahora se obtiene de settings"
    },
    'insertar_alumno.py': {
        'old_pattern': r'"postgresql://neondb_owner:[^"]+"',
        'new_line': "from app.core.config import settings\n# URL se obtiene de settings.DATABASE_URL\n",
        'replace_with': 'settings.DATABASE_URL.split("@")[0] + "@" + settings.DATABASE_URL.split("@")[1].split("/")[0]'
    },
    'insertar_maquinas.py': {
        'old_pattern': r'DATABASE_URL = "postgresql://neondb_owner:[^"]+@[^"]+"',
        'new_line': "from app.core.config import settings\nDATABASE_URL = settings.DATABASE_URL\n",
        'replace_with': "# DATABASE_URL ahora se obtiene de settings"
    },
    'test_db_simple.py': {
        'old_pattern': r'DATABASE_URL = "postgresql://neondb_owner:[^"]+@[^"]+"',
        'new_line': "from app.core.config import settings\nDATABASE_URL = settings.DATABASE_URL\n",
        'replace_with': "# DATABASE_URL ahora se obtiene de settings"
    },
    '_setup_test_db.py': {
        'old_pattern': r'PROD = "postgresql://neondb_owner:[^"]+@[^"]+"',
        'new_line': "# PROD se obtiene de settings.DATABASE_URL con ENVIRONMENT='' \n# (definido en _run_tests_orchestrator.py)\n",
        'replace_with': 'PROD = settings.DATABASE_URL'
    },
    'run_setup_test_db.py': {
        'old_pattern': r'PROD = "postgresql://neondb_owner:[^"]+@[^"]+"',
        'new_line': "# PROD se obtiene de settings.DATABASE_URL con ENVIRONMENT='' \n# (definido en _run_tests_orchestrator.py)\n",
        'replace_with': 'PROD = settings.DATABASE_URL'
    },
}

for fname, rule in files_to_fix.items():
    fp = os.path.join(root, fname)
    if not os.path.exists(fp):
        print(f"NOT FOUND: {fname}")
        continue

    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check if already has 'from app.core.config import settings'
    has_settings_import = 'from app.core.config import settings' in content

    # Replace the hardcoded URL
    old = rule['old_pattern']
    new = rule['replace_with']
    new_content = re.sub(old, new, content)

    # Add settings import if not present and replaced
    if new_content != content and not has_settings_import:
        # Add import after existing imports
        lines = new_content.split('\n')
        insert_pos = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                insert_pos = i + 1
        if insert_pos > 0:
            lines.insert(insert_pos, rule['new_line'])
        else:
            lines.insert(0, rule['new_line'])
        new_content = '\n'.join(lines)

    if new_content != content:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"REFACTORED: {fname}")
    else:
        print(f"NO CHANGE: {fname} (pattern not found or already refactored)")

print()
print("Done. 10 files processed.")
