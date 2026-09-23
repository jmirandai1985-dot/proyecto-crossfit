"""
Datos de APOYO (aditivos) para que los usuarios de prueba funcionen igual que con el seed.

Copia EXACTA de lo que crea run_setup_test_db.py para esos IDs:
  - paso 8b: coach_disciplinas -> coach 1000 asignado a disciplina 1 (CrossFit)
  - paso 7 : suscripciones     -> alumno 999, plan 1, 50 creditos, estado 'activo'
             (fecha_inicio = ahora - 10 dias, fecha_expiracion = ahora + 20 dias)

⚠️ SEGURIDAD
  - SOLO INSERT sobre `coach_disciplinas` y `suscripciones`.
    Nunca DELETE / UPDATE / DROP / TRUNCATE.
  - Aborta si la BD activa no es un endpoint TEST conocido (is_test_db_url).
  - Aborta si faltan los usuarios 999/1000 (correr antes seed_usuarios_prueba.py).
  - Idempotente: si la fila ya existe, la saltea (no duplica).
  - No toca datos de ningun otro alumno/coach/plan.

Uso (Windows):
    cd backend
    set ENVIRONMENT=test && python scripts/seed_apoyo_usuarios_prueba.py
"""
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone

# ENVIRONMENT=test ANTES de importar config (carga .env.test).
os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

_config = importlib.import_module("app.core.config")
settings = _config.settings
SessionLocal = importlib.import_module("app.db.database").SessionLocal
CoachDisciplina = importlib.import_module("app.models.coach_disciplina").CoachDisciplina
Suscripcion = importlib.import_module("app.models.suscripcion").Suscripcion

TENANT_ID = 1
ALUMNO_ID = 999
COACH_ID = 1000
DISCIPLINA_ID = 1     # crossfit
PLAN_ID = 1
CREDITOS = 50


def main():
    host = settings.DATABASE_URL.split("@")[-1].split("/")[0]
    print("=" * 68)
    print(f"BD activa (host): {host}")
    if not _config.is_test_db_url(settings.DATABASE_URL):
        sys.exit("FATAL: la BD activa NO es un endpoint TEST conocido. Abortando.")
    print("Guard OK: endpoint TEST conocido.")
    print("=" * 68)

    db = SessionLocal()
    try:
        # ── 1. Requisito: los usuarios de prueba deben existir ───────────────
        faltan = [uid for uid in (ALUMNO_ID, COACH_ID)
                  if not db.execute(text("SELECT 1 FROM usuarios WHERE id = :i"),
                                    {"i": uid}).first()]
        if faltan:
            sys.exit(f"FATAL: faltan usuarios {faltan}. Correr primero "
                     "scripts/seed_usuarios_prueba.py")

        # ── 2. Chequeos previos (solo lectura) ───────────────────────────────
        ya_cd = db.execute(text(
            "SELECT id FROM coach_disciplinas WHERE tenant_id = :t AND coach_id = :c "
            "AND disciplina_id = :d"), {"t": TENANT_ID, "c": COACH_ID, "d": DISCIPLINA_ID}).first()
        ya_sus = db.execute(text(
            "SELECT id FROM suscripciones WHERE usuario_id = :u AND estado = 'activo'"),
            {"u": ALUMNO_ID}).first()

        cd_antes = db.execute(text("SELECT COUNT(*) FROM coach_disciplinas")).scalar()
        sus_antes = db.execute(text("SELECT COUNT(*) FROM suscripciones")).scalar()
        print(f"\ncoach_disciplinas antes: {cd_antes}   suscripciones antes: {sus_antes}")
        print(f"  coach 1000 -> disciplina 1 ya existe? {bool(ya_cd)}")
        print(f"  alumno 999 con suscripcion activa ya existe? {bool(ya_sus)}")

        # ── 3. INSERTs aditivos ──────────────────────────────────────────────
        if ya_cd:
            print("  [SKIP] coach_disciplinas ya estaba.")
        else:
            db.add(CoachDisciplina(tenant_id=TENANT_ID, coach_id=COACH_ID,
                                   disciplina_id=DISCIPLINA_ID, activo=True))
            print(f"  [INSERT] coach_disciplinas: coach {COACH_ID} -> disciplina {DISCIPLINA_ID}")

        if ya_sus:
            print("  [SKIP] suscripcion activa de 999 ya estaba.")
        else:
            ahora = datetime.now(timezone.utc)
            db.add(Suscripcion(
                tenant_id=TENANT_ID, usuario_id=ALUMNO_ID, plan_id=PLAN_ID,
                fecha_inicio=ahora - timedelta(days=10),
                fecha_expiracion=ahora + timedelta(days=20),
                creditos_disponibles=CREDITOS, estado="activo",
            ))
            print(f"  [INSERT] suscripciones: usuario {ALUMNO_ID} plan {PLAN_ID} "
                  f"({CREDITOS} creditos, activo)")

        db.commit()

        # ── 4. Verificación ──────────────────────────────────────────────────
        cd_despues = db.execute(text("SELECT COUNT(*) FROM coach_disciplinas")).scalar()
        sus_despues = db.execute(text("SELECT COUNT(*) FROM suscripciones")).scalar()
        print(f"\ncoach_disciplinas despues: {cd_despues} (delta={cd_despues - cd_antes})")
        print(f"suscripciones despues:     {sus_despues} (delta={sus_despues - sus_antes})")

        print("\nFilas de apoyo:")
        for r in db.execute(text(
                "SELECT id, tenant_id, coach_id, disciplina_id, activo "
                "FROM coach_disciplinas WHERE coach_id = :c ORDER BY id"),
                {"c": COACH_ID}).fetchall():
            print(f"  coach_disciplinas id={r[0]} tenant={r[1]} coach={r[2]} "
                  f"disc={r[3]} activo={r[4]}")
        for r in db.execute(text(
                "SELECT id, tenant_id, usuario_id, plan_id, estado, creditos_disponibles, "
                "       fecha_inicio::date, fecha_expiracion::date "
                "FROM suscripciones WHERE usuario_id = :u ORDER BY id"),
                {"u": ALUMNO_ID}).fetchall():
            print(f"  suscripcion id={r[0]} tenant={r[1]} usuario={r[2]} plan={r[3]} "
                  f"estado={r[4]} creditos={r[5]} {r[6]} -> {r[7]}")
        print("\n[OK] datos de apoyo listos")
    except SystemExit:
        db.rollback()
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
