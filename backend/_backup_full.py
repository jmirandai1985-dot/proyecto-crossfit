"""Backup COMPLETO (pg_dump, formato SQL) de la BD activa (settings.DATABASE_URL).

Usa el pg_dump de PostgreSQL 18 instalado en C:\\Program Files\\PostgreSQL\\18\\bin.
Las credenciales viajan por variables de entorno (PGHOST/PGPORT/PGUSER/PGPASSWORD/...)
para no exponer la password en la línea de comandos.
"""
import os
import sys
import subprocess
from datetime import datetime
from urllib.parse import urlparse

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app.core.config import settings  # noqa: E402

PG_DUMP = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"

url = urlparse(settings.DATABASE_URL)
backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
os.makedirs(backup_dir, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_file = os.path.join(backup_dir, f"neon_backup_full_{ts}.sql")

env = dict(os.environ)
env["PGHOST"] = url.hostname
env["PGPORT"] = str(url.port or 5432)
env["PGUSER"] = url.username
env["PGPASSWORD"] = url.password
env["PGDATABASE"] = url.path.lstrip("/")
env["PGSSLMODE"] = "require"

cmd = [
    PG_DUMP,
    "--no-owner", "--no-privileges",
    "--clean", "--if-exists",
    "-f", out_file,
]

print("Backup de:", f"{url.hostname}/{url.path.lstrip('/')}  (BD activa del .env)")
print("Salida  :", out_file)

result = subprocess.run(cmd, env=env, capture_output=True, text=True)
if result.returncode != 0:
    print("❌ pg_dump falló (rc=%s)" % result.returncode)
    print(result.stderr[:2000])
    sys.exit(1)

size = os.path.getsize(out_file)
print("✅ Backup creado:", out_file, f"({size:,} bytes)")
if result.stderr.strip():
    print("[pg_dump stderr (avisos):]", result.stderr.strip()[:500])
print("OK")
