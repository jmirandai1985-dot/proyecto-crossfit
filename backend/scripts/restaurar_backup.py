"""
Restaura un dump SQL completo (pg_dump --clean --if-exists) en la BD TEST.

Por defecto usa:  backend/backups/neon_backup_full_20260923_135804.sql
Conexión: settings.DIRECT_URL (host SIN "-pooler"; Neon recomienda la conexión
directa para operaciones masivas). Fallback: settings.DATABASE_URL.

⚠️ SEGURIDAD (por qué es seguro correrlo)
  - Aborta si la BD activa NO es un endpoint TEST conocido (`is_test_db_url`):
    es IMPOSIBLE que toque PROD por accidente.
  - Aborta si el esquema `public` de destino NO está vacío: el dump trae
    `DROP TABLE IF EXISTS` (pg_dump --clean), y no queremos pisar datos vivos.
  - Credenciales por variables de entorno de psql (PGHOST/PGPASSWORD/...),
    nunca en la línea de comandos.
  - `-v ON_ERROR_STOP=1 --single-transaction`: si algo falla, no queda un
    restore a medias.

Uso (Windows):
    cd backend
    set ENVIRONMENT=test && python scripts/restaurar_backup.py [ruta\\al\\dump.sql]
"""
import os
import subprocess
import sys
from urllib.parse import urlparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

import psycopg2  # noqa: E402
from app.core.config import is_test_db_url, settings  # noqa: E402

PSQL_DEFAULT = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"
DUMP_DEFAULT = os.path.join(
    "backups", "neon_backup_full_20260923_135804.sql")

TABLAS_CLAVE = ["clases", "asistencias", "transacciones_financieras",
                "predictions_churn", "suscripciones", "usuarios", "planes",
                "movimientos", "horarios", "segmentacion_alumnos"]


def psql_cmd():
    if os.path.exists(PSQL_DEFAULT):
        return PSQL_DEFAULT
    return "psql"   # debe estar en el PATH


def main():
    dump = sys.argv[1] if len(sys.argv) > 1 else DUMP_DEFAULT
    url = settings.DIRECT_URL or settings.DATABASE_URL
    host = url.split("@")[-1].split("/")[0]

    print("=" * 70)
    print(f"BD destino (host): {host}")
    print(f"Dump a restaurar : {dump}")

    if not is_test_db_url(settings.DATABASE_URL):
        sys.exit("FATAL: la BD activa NO es un endpoint TEST conocido. Abortando (PROD intocable).")
    if not os.path.exists(dump):
        sys.exit(f"FATAL: no existe el dump {dump}")
    print("Guard OK: endpoint TEST conocido + dump presente.")
    print("=" * 70)

    # ── Pre-check: el destino debe estar VACÍO (el dump hace DROP TABLE) ──────
    with psycopg2.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select count(*) from information_schema.tables
                where table_schema = 'public'
            """)
            n = cur.fetchone()[0]
    print(f"tablas en public ANTES del restore: {n}")
    if n > 0:
        sys.exit("FATAL: el esquema public NO está vacío. Restaurar acá borraría datos "
                 "existentes (el dump trae DROP TABLE IF EXISTS). Abortando.")

    # ── Restore con psql ─────────────────────────────────────────────────────
    p = urlparse(url)
    env = dict(os.environ)
    env.update({
        "PGHOST": p.hostname,
        "PGPORT": str(p.port or 5432),
        "PGUSER": p.username,
        "PGPASSWORD": p.password,
        "PGDATABASE": p.path.lstrip("/"),
        "PGSSLMODE": "require",
    })
    cmd = [psql_cmd(), "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", dump]
    print("\nEjecutando psql (ON_ERROR_STOP=1, single transaction)...")
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    print(f"returncode={res.returncode}")
    if res.stdout.strip():
        print("[stdout]", res.stdout.strip()[-1500:])
    if res.stderr.strip():
        print("[stderr]", res.stderr.strip()[-1500:])
    if res.returncode != 0:
        sys.exit("FATAL: el restore falló (ver stderr). NO se aplicó nada (single transaction).")

    # ── Verificación post-restore ────────────────────────────────────────────
    with psycopg2.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("""select count(*) from information_schema.tables
                           where table_schema = 'public'""")
            print(f"\ntablas en public DESPUES del restore: {cur.fetchone()[0]}")
            for t in TABLAS_CLAVE:
                cur.execute(f'select count(*) from public."{t}"')
                print(f"  {t} = {cur.fetchone()[0]}")
            cur.execute("select version_num from alembic_version")
            print("  alembic_version =", cur.fetchall())


if __name__ == "__main__":
    main()
