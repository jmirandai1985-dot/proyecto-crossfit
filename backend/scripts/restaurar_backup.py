"""
Restaura un dump SQL completo (pg_dump --clean --if-exists) en la BD TEST.

Por defecto usa:  backend/backups/neon_backup_full_20260923_135804.sql
Conexión: settings.DIRECT_URL (host SIN "-pooler"; Neon recomienda la conexión
directa para operaciones masivas). Fallback: settings.DATABASE_URL.

⚠️ SEGURIDAD (por qué es seguro correrlo)
  - MODO TEST (por defecto): aborta si la BD activa NO es un endpoint TEST conocido
    (`is_test_db_url`): es IMPOSIBLE que toque PROD por accidente.
  - MODO PROD (--prod --confirmo-host=<host>): para migrar PROD a un proyecto Neon nuevo.
    Exige ENVIRONMENT=production, que el destino NO sea un endpoint TEST y que el host
    se confirme a mano en la línea de comandos.
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
import pathlib
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


def sanitizar_dump(dump: str) -> str:
    """Devuelve una copia del dump SIN las sentencias de ACL/owner.

    Los dumps hechos sin --no-owner/--no-privileges (p. ej. el cron
    maintenance/backup_neon.py) traen ALTER DEFAULT PRIVILEGES y ALTER ... OWNER TO
    de roles INTERNOS de Neon (cloud_admin / neon_superuser) que neondb_owner no
    puede ejecutar: con ON_ERROR_STOP abortarian el restore completo.
    """
    origen = pathlib.Path(dump)
    destino = origen.with_name(origen.name + ".sanitizado.sql")
    saltando = False
    n = 0
    with open(origen, encoding="utf-8", newline="") as fin,          open(destino, "w", encoding="utf-8", newline="") as fout:
        for ln in fin:
            if saltando:
                if ln.rstrip("\r\n").rstrip().endswith(";"):
                    saltando = False
                continue
            t = ln.lstrip()
            omitir = (t.startswith("ALTER DEFAULT PRIVILEGES")
                      or t.startswith("GRANT ")
                      or t.startswith("REVOKE ")
                      or (t.startswith("ALTER ") and " OWNER TO " in t))
            if omitir:
                n += 1
                if not t.rstrip("\r\n").rstrip().endswith(";"):
                    saltando = True
                continue
            fout.write(ln)
    print(f"[sanitizar] sentencias de ACL/owner omitidas: {n} -> {destino.name}")
    return str(destino)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    dump = args[0] if args else DUMP_DEFAULT
    destino_prod = "--prod" in flags
    confirmo = next((f.split("=", 1)[1] for f in flags
                     if f.startswith("--confirmo-host=")), "")

    url = settings.DIRECT_URL or settings.DATABASE_URL
    host = url.split("@")[-1].split("/")[0]

    print("=" * 70)
    print(f"BD destino (host): {host}")
    print(f"Dump a restaurar : {dump}")
    print(f"Modo             : {'PROD (explícito)' if destino_prod else 'TEST (por defecto)'}")

    if not os.path.exists(dump):
        sys.exit(f"FATAL: no existe el dump {dump}")

    if destino_prod:
        # Modo PROD: exige intención explícita. Tres condiciones JUNTAS:
        #   1) ENVIRONMENT=production (o sea: se cargó backend/.env, no .env.test)
        #   2) el destino NO es un endpoint TEST conocido
        #   3) --confirmo-host=<host> coincide EXACTO con el host de DIRECT_URL
        if os.getenv("ENVIRONMENT") != "production":
            sys.exit("FATAL modo PROD: definí ENVIRONMENT=production (backend/.env).")
        if is_test_db_url(settings.DATABASE_URL):
            sys.exit("FATAL modo PROD: el destino es un endpoint TEST. Usá el modo por defecto.")
        if confirmo != host:
            sys.exit(f"FATAL modo PROD: agregá --confirmo-host={host} para confirmar el destino.")
        print("Guard PROD OK: ENVIRONMENT=production + host confirmado a mano.")
    else:
        # Modo por defecto (TEST): sólo endpoints TEST conocidos.
        if not is_test_db_url(settings.DATABASE_URL):
            sys.exit("FATAL: la BD activa NO es un endpoint TEST conocido. "
                     "Para restaurar PROD usá --prod --confirmo-host=<host>.")
        print("Guard TEST OK: endpoint TEST conocido.")
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
    # Los dumps sin --no-owner/--no-privileges traen ACL de roles internos de Neon
    # (cloud_admin/neon_superuser) que neondb_owner no puede aplicar: se omiten.
    dump_saneado = sanitizar_dump(dump)

    cmd = [psql_cmd(), "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", dump_saneado]
    print("\nEjecutando psql (ON_ERROR_STOP=1, single transaction)...")
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    print(f"returncode={res.returncode}")
    if res.stdout.strip():
        print("[stdout]", res.stdout.strip()[-1500:])
    if res.stderr.strip():
        print("[stderr]", res.stderr.strip()[-1500:])
    if res.returncode != 0:
        sys.exit("FATAL: el restore falló (ver stderr). NO se aplicó nada (single transaction).")
    try:
        os.remove(dump_saneado)
        print(f"[sanitizar] copia temporal eliminada: {os.path.basename(dump_saneado)}")
    except OSError:
        pass

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
