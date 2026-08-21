"""Diagnóstico SOLO LECTURA: qué columnas de las migraciones alembic 001-006 ya
existen en la BD activa (para evaluar si aplicar alembic upgrade sería seguro)."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import create_engine, text  # noqa: E402
from app.core.config import settings  # noqa: E402

engine = create_engine(settings.DATABASE_URL)

checks = [
    ("001", "planes", "genero"),
    ("002", "historial_rm", "repeticiones"),
    ("002", "historial_rm", "series"),
    ("002", "historial_rm", "minutos"),
    ("002", "historial_rm", "vueltas"),
    ("002", "historial_rm", "km"),
    ("002", "historial_rm", "calorias"),
    ("003", "planes", "requiere_certificado_estudiante"),
    ("004", "solicitudes_planes", "certificado_estudiante_url"),
    ("005", "usuarios", "estatura_cm"),
    ("006", "wods", "calentamiento"),
    ("006", "wods", "fuerza_habilidad"),
    ("006", "wods", "wod_principal"),
    ("006", "wods", "tipo_metcon"),
]

with engine.connect() as c:
    for mig, tabla, col in checks:
        n = c.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:col"),
            {"t": tabla, "col": col}).scalar()
        print(f"  mig {mig}: {tabla}.{col:35s} -> "
              f"{'EXISTE ya (conflicto si alembic lo vuelve a crear)' if n else 'NO existe (lo crearía alembic)'}")

    print("\nTabla alembic_version en BD:", end=" ")
    try:
        v = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print("existe, versión =", v)
    except Exception:
        print("NO existe (alembic nunca aplicado/stamped en esta BD)")

print("\nDiagnóstico completado (solo lectura).")
