"""Diagnostico Fecha Registro: created_at en la BD activa para alumnos."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import create_engine, text  # noqa: E402
from app.core.config import settings  # noqa: E402

e = create_engine(settings.DATABASE_URL)
with e.connect() as c:
    rows = c.execute(text(
        "SELECT id, nombre, correo, rol, activo, estado, created_at "
        "FROM usuarios WHERE rol='alumno' ORDER BY id")).fetchall()
    print('total alumnos:', len(rows))
    for r in rows:
        print(f"id={r.id} activo={r.activo} estado={r.estado} "
              f"created_at={r.created_at} nombre={r.nombre[:40]!r}")

    n_null = c.execute(text(
        "SELECT COUNT(*) FROM usuarios WHERE created_at IS NULL")).scalar()
    print('usuarios con created_at NULL (todos los roles):', n_null)

    # Columnas reales de la tabla usuarios
    cols = [r[0] for r in c.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='usuarios' "
        "ORDER BY ordinal_position")).fetchall()]
    print('columnas usuarios:', ', '.join(cols))

print()
print("=== TEST SERIALIZACION UsuarioListItem (lo que devuelve GET /usuarios) ===")
from app.db.database import SessionLocal  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.schemas.usuario import UsuarioListItem  # noqa: E402

db = SessionLocal()
try:
    u = db.query(Usuario).filter(Usuario.rol == 'alumno').first()
    print("usuario test:", u.id, u.nombre)
    item = UsuarioListItem.model_validate(u)
    print("model_dump(by_alias=True):", item.model_dump(by_alias=True))
    print("model_dump_json(by_alias=True):", item.model_dump_json(by_alias=True))
    print("campo fechaRegistro:", getattr(item, "fechaRegistro", "NO EXISTE"))
finally:
    db.close()

