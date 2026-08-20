"""Overrides desarrollo TEST (small-butterfly): activa coach jesus, asigna crossfit, clase de hoy."""
import os
import sys
import importlib
from datetime import date, timedelta
from sqlalchemy import text

if os.environ.get("ENVIRONMENT", "") != "test":
    print("ERROR: solo con ENVIRONMENT=test")
    sys.exit(1)
os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

settings = importlib.import_module("app.core.config").settings
if "small-butterfly" not in settings.DATABASE_URL:
    print("ERROR: URL no es small-butterfly")
    sys.exit(1)
SessionLocal = importlib.import_module("app.db.database").SessionLocal

print("=== APLICANDO OVERRIDES TEST (small-butterfly) ===")
db = SessionLocal()
try:
    r = db.execute(text("UPDATE usuarios SET activo=true WHERE id=7"))
    db.commit()
    print(f"[OK] usuarios.activo=True id=7 (filas: {r.rowcount})")
except Exception as e:
    db.rollback()
    print(f"[ERROR] usuario: {e}")

# Upsert coach_disciplinas para TODAS las disciplinas del coach 7
for disc_id in (1, 6):  # crossfit + Clase Intensiva Sabado
    try:
        ex = db.execute(text(
            "SELECT id FROM coach_disciplinas WHERE tenant_id=1 AND coach_id=7 AND disciplina_id=:d"
        ), {"d": disc_id}).first()
        if ex:
            db.execute(
                text("UPDATE coach_disciplinas SET activo=true WHERE id=:i"), {"i": ex[0]})
            print(f"[OK] coach_disciplinas reactivada id={ex[0]} (7->{disc_id})")
        else:
            db.execute(text(
                "INSERT INTO coach_disciplinas (tenant_id,coach_id,disciplina_id,activo) VALUES (1,7,:d,true)"
            ), {"d": disc_id})
            print(f"[OK] coach_disciplinas creada (7->{disc_id})")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[ERROR] coach_disciplinas disc {disc_id}: {e}")

try:
    # Auto-generar clases [hoy, hoy+6] (misma funcion que GET /clases)
    from app.services.generar_clases import generar_clases_para_rango
    hoy = date.today()
    resultado = generar_clases_para_rango(db, 1, hoy, hoy + timedelta(days=6))
    print(f"[OK] clases auto-generadas: {resultado.get('creadas', 0)} creadas")
    # Buscar clase crossfit hoy mas cercana a 19:00 y asignar coach 7
    f = db.execute(text("""
        SELECT id, hora_inicio FROM clases
        WHERE tenant_id=1 AND disciplina_id=1 AND fecha=:f
        ORDER BY ABS(EXTRACT(HOUR FROM hora_inicio)-19) ASC, hora_inicio ASC LIMIT 1
    """), {"f": hoy}).first()
    if f:
        db.execute(
            text("UPDATE clases SET coach_id=7 WHERE id=:i"), {"i": f[0]})
        db.commit()
        print(f"[OK] clase id={f[0]} hora={f[1]} -> coach_id=7")
    else:
        print("[WARN] sin clase crossfit hoy tras generacion")
except Exception as e:
    db.rollback()
    print(f"[ERROR] clase: {e}")
finally:
    db.close()
print("=== OVERRIDES APLICADOS ===")
