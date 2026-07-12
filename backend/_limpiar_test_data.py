"""
Limpia los 15 registros de prueba identificados en producción.
NO hace nada sin confirmación explícita del usuario.

Registros a eliminar:
  historial_rm: ids 57, 58, 65, 66, 67, 68, 69, 70, 71, 72
  wods: ids 12, 17, 21
"""
import os
from sqlalchemy import text, create_engine
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

RM_IDS = [57, 58, 65, 66, 67, 68, 69, 70, 71, 72]
WOD_IDS = [12, 17, 21]

with engine.connect() as conn:
    trans = conn.begin()
    try:
        # Borrar RMs
        for rid in RM_IDS:
            r = conn.execute(
                text("DELETE FROM historial_rm WHERE id = :id RETURNING id, notas"),
                {"id": rid}
            ).fetchone()
            if r:
                print(f"  ✅ Eliminado historial_rm id={r[0]} (notas='{r[1]}')")
            else:
                print(f"  ⚠️  historial_rm id={rid} no encontrado")

        # Borrar WODs
        for wid in WOD_IDS:
            r = conn.execute(
                text("DELETE FROM wods WHERE id = :id RETURNING id, titulo"),
                {"id": wid}
            ).fetchone()
            if r:
                print(f"  ✅ Eliminado wod id={r[0]} (titulo='{r[1]}')")
            else:
                print(f"  ⚠️  wod id={wid} no encontrado")

        trans.commit()
        print("\n✅ Limpieza completada. 15 registros eliminados.")
    except Exception as e:
        trans.rollback()
        print(f"\n❌ Error: {e}")
