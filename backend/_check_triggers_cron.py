"""Auditoría SOLO LECTURA: triggers, event triggers, rules, extensions, pg_cron y
conexiones activas en la BD activa (settings.DATABASE_URL). No modifica nada."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import create_engine, text  # noqa: E402
from app.core.config import settings  # noqa: E402

engine = create_engine(settings.DATABASE_URL)


def q(sql):
    with engine.connect() as c:
        return c.execute(text(sql)).fetchall()


def sec(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


sec("EXTENSIONES INSTALADAS")
rows = q("SELECT extname, extversion FROM pg_extension ORDER BY extname")
print(" - (ninguna)" if not rows else "")
for r in rows:
    print(" -", r[0], r[1])

sec("TRIGGERS EN SCHEMA public (excluye internos de FK)")
rows = q("""
SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid)
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname
""")
print(" - (ninguno)" if not rows else "")
for r in rows:
    print(f" - {r[0]} . {r[1]}\n     {r[2]}")

sec("TRIGGERS sobre 'tenants' y 'usuarios' (incluye internos)")
rows = q("""
SELECT c.relname, t.tgname, t.tgenabled, t.tgisinternal, pg_get_triggerdef(t.oid)
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname IN ('tenants', 'usuarios')
ORDER BY c.relname, t.tgname
""")
print(" - (ninguno)" if not rows else "")
for r in rows:
    print(f" - {r[0]} . {r[1]}  enabled={r[2]} internal={r[3]}\n     {r[4]}")

sec("EVENT TRIGGERS (globales)")
rows = q("SELECT evtname, evtevent, evtenabled FROM pg_event_trigger")
print(" - (ninguno)" if not rows else "")
for r in rows:
    print(" -", r)

sec("RULES sobre 'tenants' y 'usuarios'")
rows = q("""
SELECT c.relname, r.rulename, r.ev_type
FROM pg_rewrite r
JOIN pg_class c ON c.oid = r.ev_class
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname IN ('tenants', 'usuarios')
ORDER BY c.relname, r.rulename
""")
print(" - (ninguno)" if not rows else "")
for r in rows:
    print(" -", r)

sec("pg_cron JOBS (si la extensión existe)")
try:
    rows = q("SELECT jobid, schedule, command, active FROM cron.job ORDER BY jobid")
    print(" - (sin jobs definidos)" if not rows else "")
    for r in rows:
        print(" - jobid=%s active=%s schedule=%s command=%s" % (r[0], r[3], r[1], r[2]))
except Exception as e:
    print(f" - pg_cron NO instalado ({type(e).__name__})")

sec("OTRAS CONEXIONES ACTIVAS AHORA")
rows = q("""
SELECT pid, usename, application_name, state
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
ORDER BY pid
""")
print(" - (solo esta sesión)" if not rows else "")
for r in rows:
    print(" -", r)

print("\nAuditoría completada (solo lectura).")
