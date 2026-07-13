import re
import glob
import os

d = os.path.dirname(os.path.abspath(__file__))

# 1. Sanitizar _sanitizar_passwords.py - reemplazar las vars con las contraseñas
fp = os.path.join(d, '_sanitizar_passwords.py')
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()
# Buscar las lineas OLD/NEW usando la estructura del archivo
# Busca: OLD = 'npg_...'  ->  OLD = '***ANONIMIZADO***'
content = re.sub(r"OLD = 'npg_[^']*'", "OLD = '***ANONIMIZADO***'", content)
content = re.sub(r"NEW = 'npg_[^']*'", "NEW = '***ANONIMIZADO***'", content)
with open(fp, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK _sanitizar_passwords.py sanitized")

# 2. Verificar que ningun .py tenga "npg_" excepto .env que es normal
found = []
for f in glob.glob(d + '/**/*.py', recursive=True):
    with open(f, 'r', encoding='utf-8', errors='replace') as fh:
        c = fh.read()
    if 'npg_' in c:
        found.append(f)
        print(f">>> npg_ ENCONTRADO en: {f}")
if found:
    print(f"\n*** {len(found)} archivo(s) AUN tienen npg_ ***")
else:
    print("\nOK: Ningun archivo .py contiene credenciales hardcodeadas")

# 3. Verificar .env.test
fpt = os.path.join(d, '.env.test')
if os.path.exists(fpt):
    with open(fpt, 'r', encoding='utf-8') as f:
        ct = f.read()
    has = 'npg_' in ct
    print(f'.env.test has npg_: {has}')
    if has:
        print(">>> .env.test TIENE CREDENCIAL")
    else:
        print(".env.test OK - sin credencial")

# 4. Verificar .env (debe tener la credencial, esta en .gitignore)
fpe = os.path.join(d, '.env')
if os.path.exists(fpe):
    with open(fpe, 'r', encoding='utf-8') as f:
        ct = f.read()
    has = 'npg_' in ct
    print(f'.env has npg_: {has} (NORMAL, esta en .gitignore)')
