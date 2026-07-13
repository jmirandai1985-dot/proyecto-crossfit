"""
CORREGIR es_open_box en disciplinas de PRODUCCION (SOLO LECTURA AL FINAL)
- Musculacion (ID=3): NO requiere coach → es_open_box=True
- Open Box (ID=4): NO requiere coach → es_open_box=True
- crossfit (ID=1), levantamiento olimpico (ID=5): requieren coach → es_open_box=False (se queda)

Ejecutar con: py -3.12 _fix_es_open_box.py
"""
from sqlalchemy import text
from app.db.database import SessionLocal
import os
os.environ["ENVIRONMENT"] = ""

db = SessionLocal()
try:
    # Verificar que estamos en PROD
    from app.core.config import settings
    db_url = settings.DATABASE_URL
    if "soft-bar" in db_url:
        print("[ERROR] Conectado a TEST. Ejecutar contra PRODUCCION.")
        exit(1)

    print("CORRIGIENDO es_open_box en PRODUCCION...")
    print("URL: %s" % db_url[:50])

    # Mostrar valores actuales
    rows = db.execute(text(
        "SELECT id, nombre, es_open_box FROM disciplinas WHERE tenant_id=1 ORDER BY id")).fetchall()
    print()
    print("VALORES ACTUALES:")
    for r in rows:
        print("  ID=%d %s: es_open_box=%s" %
              (r.id, r.nombre, str(r.es_open_box)))

    # Actualizar
    # Musculacion
    db.execute(text("UPDATE disciplinas SET es_open_box=True WHERE id=3"))
    # Open Box
    db.execute(text("UPDATE disciplinas SET es_open_box=True WHERE id=4"))
    db.commit()

    # Mostrar valores finales
    rows2 = db.execute(text(
        "SELECT id, nombre, es_open_box FROM disciplinas WHERE tenant_id=1 ORDER BY id")).fetchall()
    print()
    print("VALORES ACTUALIZADOS:")
    for r in rows2:
        coach = "NO" if r.es_open_box else "SI"
        print("  ID=%d %s: es_open_box=%s -> requiere_coach=%s" %
              (r.id, r.nombre, str(r.es_open_box), coach))

    print()
    print("OK: es_open_box corregido. Regla: requiere_coach = NOT es_open_box")

finally:
    db.close()
