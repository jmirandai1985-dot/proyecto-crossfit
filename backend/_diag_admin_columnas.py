"""Solo lectura: columnas reales de planes, solicitudes_planes y cobertura_emergencia."""
from app.core.config import settings
from sqlalchemy import create_engine, text

e = create_engine(settings.DATABASE_URL)
c = e.connect()
for tabla in ("planes", "solicitudes_planes", "cobertura_emergencia", "notificaciones_enviadas"):
    rows = c.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :t ORDER BY ordinal_position"
    ), {"t": tabla}).fetchall()
    print(f"{tabla}: {[r[0] for r in rows]}")
c.close()
