"""
Crea (ADITIVO) los 4 usuarios de prueba del seed histórico en la rama TEST de Neon.

IDs y datos EXACTOS de run_setup_test_db.py (mismo tenant/rol/correo/rut/peso/genero
y password 'Test1234!' hasheada con app.core.security.get_password_hash):
    999  alumno        Alumno Test        at@t.com
    1000 coach         Coach Test         ct@t.com
    1001 administrador Admin Test         admin@test.com
    1010 alumno        Alumno Admin Test  alumno_admin@test.com

⚠️ SEGURIDAD
  - SOLO INSERT sobre la tabla `usuarios`. Nunca DELETE / UPDATE / DROP / TRUNCATE.
  - Aborta si la BD activa no es un endpoint TEST conocido (is_test_db_url).
  - Aborta si alguno de los IDs ya existe con OTRO correo, o si el correo/RUT
    ya pertenece a otro usuario: NUNCA se pisa una fila existente.
  - Idempotente: si el usuario ya está creado correctamente, lo saltea.

Uso (Windows):
    cd backend
    set ENVIRONMENT=test && python scripts/seed_usuarios_prueba.py
"""
import importlib
import os
import sys

# ENVIRONMENT=test ANTES de importar config (carga .env.test).
os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

_config = importlib.import_module("app.core.config")
settings = _config.settings
SessionLocal = importlib.import_module("app.db.database").SessionLocal
Usuario = importlib.import_module("app.models.usuario").Usuario
get_password_hash = importlib.import_module("app.core.security").get_password_hash

TENANT_ID = 1
PASSWORD = "Test1234!"

# (id, rut, nombre, correo, rol, peso_kg, genero)
USUARIOS_SEED = [
    (999, "99.999.999-9", "Alumno Test", "at@t.com", "alumno", 70, "masculino"),
    (1000, "11.111.111-1", "Coach Test", "ct@t.com", "coach", None, None),
    (1001, "11.111.111-2", "Admin Test", "admin@test.com", "administrador", None, None),
    (1010, "11.111.111-3", "Alumno Admin Test", "alumno_admin@test.com", "alumno", 75, "masculino"),
]


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
        # ── 1. Chequeos previos (solo lectura) ──────────────────────────────
        ids = [u[0] for u in USUARIOS_SEED]
        correos = [u[3] for u in USUARIOS_SEED]
        ruts = [u[1] for u in USUARIOS_SEED]

        existentes = db.execute(text(
            "SELECT id, correo FROM usuarios WHERE id = ANY(:ids)"), {"ids": ids}).fetchall()
        for uid, correo in existentes:
            esperado = next(u[3] for u in USUARIOS_SEED if u[0] == uid)
            if correo != esperado:
                sys.exit(f"FATAL: id={uid} ya existe con correo '{correo}' (esperaba "
                         f"'{esperado}'). No se toca ninguna fila.")
            print(f"  [i] id={uid} ({correo}) ya existe -> se saltea.")

        conflictos = db.execute(text(
            "SELECT id, correo, rut FROM usuarios "
            "WHERE (correo = ANY(:c) OR rut = ANY(:r)) AND NOT (id = ANY(:ids))"),
            {"c": correos, "r": ruts, "ids": ids}).fetchall()
        if conflictos:
            sys.exit(f"FATAL: correo/RUT ya usado por otro usuario: {conflictos}. Abortando.")

        antes_usuarios = db.execute(text("SELECT COUNT(*) FROM usuarios")).scalar()
        print(f"\nusuarios antes: {antes_usuarios}")

        # ── 2. INSERT puntual (aditivo) ─────────────────────────────────────
        _HASH = get_password_hash(PASSWORD)
        creados = []
        for uid, rut, nombre, correo, rol, peso, genero in USUARIOS_SEED:
            if any(e[0] == uid for e in existentes):
                continue
            db.add(Usuario(
                id=uid, tenant_id=TENANT_ID, rut=rut, nombre=nombre, correo=correo,
                password_hash=_HASH, rol=rol, activo=True, estado="activo",
                acepta_correo_reactivacion=True, cambiar_password_al_login=False,
                peso_kg=peso, genero=genero,
            ))
            creados.append((uid, correo, rol))
            print(f"  [INSERT] id={uid} | {rol:<14} | {correo}")

        # La secuencia usuarios_id_seq NO se toca a propósito: sus valores quedan
        # muy por debajo de 999 (v.g. 230), así que el próximo id autoincremental
        # sigue siendo libre y no colisiona con los ids explícitos 999-1010.
        # Así este script es 100% aditivo: solo INSERTs.

        db.commit()

        # ── 3. Verificación ─────────────────────────────────────────────────
        despues = db.execute(text("SELECT COUNT(*) FROM usuarios")).scalar()
        print(f"\nusuarios despues: {despues}  (delta={despues - antes_usuarios})")

        print("\nFilas de prueba en la BD:")
        for r in db.execute(text(
            "SELECT u.id, u.tenant_id, u.rut, u.correo, u.rol, u.activo, u.estado, "
            "       u.peso_kg, u.genero, (u.password_hash LIKE '$2%') AS bcrypt, "
            "       s.creditos_disponibles "
            "FROM usuarios u LEFT JOIN suscripciones s "
            "  ON s.usuario_id = u.id AND s.estado = 'activo' "
            "WHERE u.id = ANY(:ids) ORDER BY u.id"), {"ids": ids}).fetchall():
            print(f"  id={r[0]} tenant={r[1]} rut={r[2]:<12} {r[3]:<22} {r[4]:<14} "
                  f"activo={r[5]} estado={r[6]:<7} peso={r[7]} genero={r[8]} "
                  f"bcrypt={r[9]} creditos={r[10]}")

        print(f"\n[OK] creados: {[c[0] for c in creados]}")
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
