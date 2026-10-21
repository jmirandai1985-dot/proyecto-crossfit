"""
SYNC PROD -> TEST (TEST y PROD en proyectos Neon separados desde 2026-09-23).
IDEMPOTENTE: TRUNCATE + copia todos los datos desde PRODUCCIÓN.
Preserva tablas custom (transacciones_financieras) mediante backup/restore.
Incluye migraciones post-sync (requiere_coach, es_estudiante, coach_disciplinas, cobertura_emergencia).
"""
import subprocess
import psycopg2
import os
import sys
import importlib
from psycopg2.extras import execute_values

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

# OJO: el TRUNCATE de este script borra TODA la tabla usuarios, asi que los
# usuarios de prueba del seed de la suite (999/1000/1001/1010) NO sobreviven:
# despues del sync, TEST es una copia de PROD (usuarios reales incluidos).

# ── SEGURIDAD: Verificar ENVIRONMENT ──
ENV = os.environ.get("ENVIRONMENT", "")
if ENV != "test":
    print("="*60)
    print("  ERROR: ENVIRONMENT no es 'test'")
    print("  Si ejecutas esto sin ENVIRONMENT=test borraras PRODUCCION")
    print("  Abortando.")
    sys.exit(1)

os.environ["ENVIRONMENT"] = "test"

# ── URLs ──
# TEST: se obtiene de settings (carga .env.test)
_config_mod = importlib.import_module("app.core.config")
settings = _config_mod.settings
URL_TEST = settings.DATABASE_URL

# PROD: NUNCA hardcodear credenciales en el repo. Orden de resolucion:
#   1) DATABASE_URL_PROD en el entorno (override explicito, fuera de git)
#   2) DATABASE_URL de backend/.env -> desde la migracion 2026-09-23 TEST y PROD
#      viven en proyectos Neon SEPARADOS: .env.test apunta a TEST y .env apunta
#      al PROD activo, asi que ya no comparten endpoint ni sufijo de branch.
URL_PROD = os.getenv("DATABASE_URL_PROD")
if not URL_PROD:
    try:
        from dotenv import dotenv_values
        _env_prod = dotenv_values(os.path.join(BACKEND_DIR, ".env"))
        URL_PROD = (_env_prod.get("DATABASE_URL") or "").strip()
        if URL_PROD:
            print("[INFO] DATABASE_URL_PROD no estaba en el entorno: uso DATABASE_URL de backend/.env")
    except Exception as _e:
        print(f"[WARN] no se pudo leer backend/.env: {_e}")

if not URL_PROD or "postgresql://" not in URL_PROD:
    print("=" * 60)
    print("  FATAL: no encontre la URL de PRODUCCION.")
    print("  Define DATABASE_URL_PROD en el entorno o DATABASE_URL en backend/.env")
    print("=" * 60)
    sys.exit(1)

# ── SEGURIDAD: TEST tiene que ser TEST y PROD no puede ser TEST ──
# (con la config nueva, un .env mal apuntado haria que este script copiara
#  TEST sobre si mismo o, peor, tomara TEST como origen de produccion)
if not _config_mod.is_test_db_url(URL_TEST):
    print("FATAL: settings.DATABASE_URL no apunta a un endpoint TEST conocido. Abortando.")
    sys.exit(1)
if _config_mod.is_test_db_url(URL_PROD):
    print("FATAL: la URL de PRODUCCION apunta a un endpoint de TEST. Abortando.")
    sys.exit(1)
if URL_PROD == URL_TEST:
    print("FATAL: la URL de PRODUCCION es igual a la de TEST. Abortando.")
    sys.exit(1)

# ── SEGURIDAD: guard POSITIVO de PROD ──
# `is_test_db_url()` sólo responde "esto NO es TEST". Faltaba lo inverso:
# confirmar que el ORIGEN es el PROD real. Sin esto, un .env apuntado a otra
# rama o a un proyecto ajeno pasaba el filtro como "produccion" y el TRUNCATE
# de TEST copiaba los datos equivocados (o los de nadie).
# PROD_BRANCH_ID es el único lugar donde vive el endpoint de PROD (config.py).
if _config_mod.PROD_BRANCH_ID not in URL_PROD:
    print("FATAL: la URL de PRODUCCION no es el endpoint de PROD conocido "
          f"({_config_mod.PROD_BRANCH_ID}). Abortando.")
    sys.exit(1)


def _solo_host(url: str) -> str:
    """Host de la URL, sin usuario ni password (nunca imprimir credenciales)."""
    return url.split("@")[-1].split("/")[0] if "@" in url else url[:40]


print("="*60)
print(f"BD de TEST : {_solo_host(URL_TEST)}")
print(f"BD de PROD : {_solo_host(URL_PROD)}")
print("="*60)

# ── CONECTAR ──
c_prod = psycopg2.connect(URL_PROD)
c_test = psycopg2.connect(URL_TEST)
c_test.autocommit = True
cur_prod = c_prod.cursor()
cur_test = c_test.cursor()


# ── 0. GUARDRAIL: comparar la revisión de Alembic de TEST vs PROD ───────────
# El sync copia DATOS, no esquema, y nunca toca `alembic_version`. Pero si TEST
# quedó con una revisión incompatible respecto de PROD, cualquier `alembic upgrade`
# posterior se comporta raro (pasó el 2026-09-26: TEST con esquema 036 y stamp 035).
# Se compara ANTES de truncar nada usando el grafo de migraciones (ScriptDirectory),
# porque no toda diferencia es un problema: TEST ADELANTE de PROD es el flujo normal
# mientras se desarrolla una migración.
def _alembic_version(cur, etiqueta):
    """Revisión de alembic_version (None si el SELECT falla o la tabla está vacía)."""
    try:
        cur.execute("SELECT version_num FROM alembic_version")
        fila = cur.fetchone()
        return fila[0] if fila else None
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] no se pudo leer alembic_version en {etiqueta}: {type(e).__name__}")
        return None


def _comparar_versiones_alembic(ver_test, ver_prod):
    """(estado, detalle) = igual | adelante | atras | distintas. Función pura aparte."""
    try:
        from alembic.config import Config as _AlembicConfig
        from alembic.script import ScriptDirectory

        from app.core.alembic_orden import comparar_revisiones

        _cfg = _AlembicConfig(os.path.join(BACKEND_DIR, "alembic.ini"))
        _cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
        _script_dir = ScriptDirectory.from_config(_cfg)  # sólo lee alembic/versions
    except Exception as e:  # noqa: BLE001
        return "distintas", f"no se pudo leer el script directory de Alembic: {type(e).__name__}"
    return comparar_revisiones(_script_dir, ver_test, ver_prod)


ver_test = _alembic_version(cur_test, "TEST")
ver_prod = _alembic_version(cur_prod, "PROD")
estado, detalle = _comparar_versiones_alembic(ver_test, ver_prod)
print(f"Version Alembic  TEST: {ver_test}")
print(f"Version Alembic  PROD: {ver_prod}")
print(f"Comparacion Alembic: {estado} -> {detalle}")

if estado == "igual":
    print("[OK] TEST y PROD están en la misma revisión de Alembic")
elif estado == "adelante":
    # Flujo normal: se está desarrollando una migración en TEST antes de aplicarla
    # a PROD. Sólo se avisa (no bloquea el sync, que copia datos, no esquema).
    print("[WARN] TEST va ADELANTE de PROD en Alembic (normal mientras se desarrolla")
    print("       una migración sin aplicar a PROD). Se continúa con el sync.")
else:
    print("=" * 60)
    print(f"  ABORTADO: revisión de Alembic incompatible ({estado})")
    print(f"    TEST: {ver_test}")
    print(f"    PROD: {ver_prod}")
    print(f"    {detalle}")
    print("  TEST no puede quedar ATRÁS de PROD ni en otra rama de migraciones.")
    print("  Cómo resolverlo:")
    print("    1) python run_setup_test_db.py   (reconstruye el esquema y hace")
    print("       'alembic stamp head' automáticamente), o")
    print("    2) ENVIRONMENT=test python -m alembic stamp <revision de PROD>")
    print("       (sólo si el esquema de TEST ya está al día)")
    print("=" * 60)
    sys.exit(1)

# ── 1. RESPALDAR tablas custom ──
print("\n[BACKUP] Respaldo transacciones_financieras...")
try:
    cur_test.execute(
        "SELECT id, tenant_id, tipo, categoria, monto, descripcion, referencia_tipo, referencia_id, fecha, created_at FROM transacciones_financieras ORDER BY id")
    backup_tx = cur_test.fetchall()
    print(f"  {len(backup_tx)} transacciones respaldadas")
except Exception as e:
    print(f"  No hay datos para respaldar: {e}")
    backup_tx = []

# ── 2. TRUNCATE CASCADE TEST ──
print("\nTRUNCATE CASCADE TEST...")
cur_test.execute("""
    TRUNCATE TABLE
        tenants, usuarios, movimientos, disciplinas, planes, horarios,
        clases, reservas, asistencias, historial_rm, notificaciones, productos, pedidos,
        suscripciones, coach_disciplinas, cobertura_emergencia, wods, wod_movimientos,
        horarios_coach, producto_imagenes, notificaciones_enviadas, beneficios,
        solicitudes_planes, avisos_marketing, codigos_referido, promociones_referidos,
        promociones_referidos_detectadas, referidos_aplicados, invitaciones,
        creditos_referido, churn_gestion, retencion_alumnos, hitos_alumno,
        configuracion_negocio, configuracion_referidos,
        -- se vacian a proposito: NO se copian de PROD (ver nota antes de TABLAS)
        auditoria, password_reset_tokens,
        daily_kpis, monthly_kpis, ml_modelos, predictions_churn, predictions_forecast,
        segmentacion_alumnos, student_segments,
        transacciones_financieras
    CASCADE
""")
print("TEST limpia")

# Parche 2026-09-07: NO dropear columnas que PROD ya incluye al copiar *.
# El schema de TEST lo reconstruye run_setup_test_db.py desde los modelos actuales,
# asi que basta con alinear TEST a PROD (ADD IF NOT EXISTS, idempotente).
cur_test.execute("ALTER TABLE disciplinas ADD COLUMN IF NOT EXISTS requiere_coach BOOLEAN NOT NULL DEFAULT true")
cur_test.execute("ALTER TABLE planes ADD COLUMN IF NOT EXISTS es_estudiante BOOLEAN NOT NULL DEFAULT false")
cur_test.execute("ALTER TABLE planes ADD COLUMN IF NOT EXISTS requiere_certificado_estudiante BOOLEAN NOT NULL DEFAULT false")

# ── 3. COPIAR PROD→TEST (tablas estándar) ──
# ORDEN = orden topologico de FK: la hija necesita el padre ya copiado.
# Ojo: este bucle atrapa las excepciones por tabla (imprime "ERROR" y sigue) y la
# conexion de TEST va con autocommit, asi que una falla a mitad de tabla deja una
# copia PARCIAL. El bloque VERIFICACION compara filas TEST vs PROD y el script
# termina con exit 1 si algo quedo distinto.
#
# Caso real que motivo este orden (2026-10-21): `clases.wod_id` referencia `wods`.
# Con `wods` fuera de la lista, el INSERT de `clases` abortaba en la primera fila
# con wod_id (8 filas de PROD apuntan a wods.id=30) y arrastraba a `reservas` y
# `asistencias` por FK. Por eso wods/wod_movimientos van ANTES de clases.
#
# `wods.estado`: varchar(20) en PROD vs enum `estadowod` en TEST. Hoy el unico
# valor de PROD es 'publicado', que existe en el enum, y Postgres castea el
# parametro al tipo de la columna destino. Si algun dia aparece un valor que no
# esta en el enum, la tabla falla y se ve como ERROR + exit 1 en la verificacion.
#
# NO se copian (quedan vacias a proposito):
#   auditoria                  -> log de operaciones; ademas `detalle` es json en
#                                 TEST y jsonb en PROD (riesgo de desajuste).
#   password_reset_tokens      -> tokens de seguridad efimeros, no viajan a TEST.
#   daily_kpis, monthly_kpis, segmentacion_alumnos, student_segments,
#   predictions_churn, predictions_forecast
#                              -> derivados/ML, recalculables desde los datos base.
#   ml_modelos                 -> apunta a artefactos .pkl que TEST no tiene.
#   horarios_base              -> no existe en el esquema de TEST.
print("\nCopiando PROD->TEST...")
TABLAS = [
    # --- base ---
    ("tenants", None),
    ("movimientos", "id, tenant_id, nombre, descripcion, categoria, activo, created_at, updated_at"),
    ("disciplinas", None),
    ("planes", None),
    ("horarios", None),
    ("usuarios", None),
    # --- configuracion ---
    ("configuracion_negocio", None),
    ("configuracion_referidos", None),
    # --- WODs y coaches (ANTES de clases: clases.wod_id -> wods) ---
    ("wods", None),
    ("wod_movimientos", None),
    ("coach_disciplinas", None),
    ("horarios_coach", None),
    # --- catalogo ---
    ("productos", None),
    ("producto_imagenes", None),
    # --- agenda y asistencia ---
    ("suscripciones", None),
    ("clases", None),
    ("asistencias", None),
    ("reservas", None),
    ("cobertura_emergencia", None),
    ("historial_rm", None),
    ("notificaciones", None),
    # --- notificaciones / beneficios / planes (beneficios.notificacion_id) ---
    ("notificaciones_enviadas", None),
    ("beneficios", None),
    ("solicitudes_planes", None),
    # --- tienda ---
    ("pedidos", None),
    ("avisos_marketing", None),
    # --- referidos (creditos_referido al final: depende de 3 tablas) ---
    ("codigos_referido", None),
    ("promociones_referidos", None),
    ("promociones_referidos_detectadas", None),
    ("referidos_aplicados", None),
    ("invitaciones", None),
    ("creditos_referido", None),
    # --- seguimiento ---
    ("churn_gestion", None),
    ("retencion_alumnos", None),
    ("hitos_alumno", None),
]

fallos = []
for tabla, columnas in TABLAS:
    cols = columnas or "*"
    try:
        cur_prod.execute(f"SELECT {cols} FROM {tabla}")
        rows = cur_prod.fetchall()
        if not rows:
            continue
        col_names = [desc[0] for desc in cur_prod.description]
        cols_str = ",".join(col_names)
        # En lotes: 24.752 asistencias una por una contra el pooler tardan minutos.
        execute_values(cur_test, f"INSERT INTO {tabla} ({cols_str}) VALUES %s",
                       rows, page_size=1000)
        print(f"  {tabla}: {len(rows)}")
    except Exception as e:
        print(f"  {tabla}: ERROR {e}")
        fallos.append((tabla, str(e)))

c_test.commit()

# ── 3b. RESINCRONIZAR SECUENCIAS SERIAL (fix: auto-generacion de clases despues del sync) ──
# Al copiar IDs explicitos desde PROD, las secuencias SERIAL de TEST quedan sin
# sincronizar. Si luego la app intenta insertar (ej. auto-generar clases para
# fechas recientes), choca con IDs ya existentes (UniqueViolation).
# Se resuelve de forma generica con pg_get_serial_sequence() por tabla copiada,
# asi no hay que mantener un dict a mano cada vez que se agrega una tabla.
print("\n[RESYNC SECUENCIAS]...")
for tabla, _columnas in TABLAS:
    try:
        cur_test.execute("SELECT pg_get_serial_sequence(%s, 'id')", (f"public.{tabla}",))
        seq = cur_test.fetchone()[0]
        if not seq:
            continue  # tabla sin id serial
        # setval con COALESCE: si la tabla esta vacia, MAX(id) es NULL -> 1
        cur_test.execute(
            f'SELECT setval(%s::regclass, COALESCE((SELECT MAX(id)+1 FROM "{tabla}"), 1), false)',
            (seq,))
        c_test.commit()
        print(f"  [OK] {tabla} -> {seq}")
    except Exception:
        # Ignorar secuencias/tablas que no existen en este schema
        pass

# ── 4. RESTAURAR tablas custom ──
print("\n[RESTORE] Restaurando transacciones_financieras...")
if backup_tx:
    for row in backup_tx:
        try:
            cur_test.execute("""
                INSERT INTO transacciones_financieras (id, tenant_id, tipo, categoria, monto, descripcion, referencia_tipo, referencia_id, fecha, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, row)
        except Exception as e:
            print(f"  Error restaurando id={row[0]}: {e}")
    c_test.commit()
    print(f"  {len(backup_tx)} transacciones restauradas")
else:
    print("  Sin datos para restaurar (tabla estaba vacía)")

# ── 5. MIGRACIONES POST-SYNC (antes eran _apply_migrations_post_sync.py) ──
print("\n[MIGRACIONES POST-SYNC]...")

# 5a. requiere_coach on disciplinas
cur_test.execute(
    "ALTER TABLE disciplinas ADD COLUMN IF NOT EXISTS requiere_coach BOOLEAN NOT NULL DEFAULT true")
cur_test.execute(
    "UPDATE disciplinas SET requiere_coach=true WHERE nombre IN ('crossfit','Gap','Levantamiento Olimpico') OR nombre LIKE '%Clase Intensiva%'")
cur_test.execute(
    "UPDATE disciplinas SET requiere_coach=false WHERE nombre IN ('Musculacion','Open Box')")
print("[OK] requiere_coach")

# 5b. es_estudiante on planes
cur_test.execute(
    "ALTER TABLE planes ADD COLUMN IF NOT EXISTS es_estudiante BOOLEAN NOT NULL DEFAULT false")
cur_test.execute(
    "UPDATE planes SET es_estudiante=true WHERE nombre IN ('Girly','Aesthetic','Influencer','Brocoli','Diddy Kong','Donkey Kong')")
print("[OK] es_estudiante")

# 5c. coach_disciplinas table
cur_test.execute("""
    CREATE TABLE IF NOT EXISTS coach_disciplinas (
        id SERIAL PRIMARY KEY,
        tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        coach_id INT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        disciplina_id INT NOT NULL REFERENCES disciplinas(id) ON DELETE CASCADE,
        activo BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
""")
# Sin INSERT de relleno: coach_disciplinas ahora se copia de PROD en el bloque 3,
# asi que TEST queda espejo exacto. Este CREATE TABLE IF NOT EXISTS es solo una
# red de seguridad para el caso de un TEST reconstruido a mano.
print("[OK] coach_disciplinas table")

# 5d. cobertura_emergencia table
cur_test.execute("""
    CREATE TABLE IF NOT EXISTS cobertura_emergencia (
        id SERIAL PRIMARY KEY,
        tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        coach_id INT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        clase_id INT NOT NULL REFERENCES clases(id) ON DELETE CASCADE,
        disciplina_id INT NOT NULL REFERENCES disciplinas(id) ON DELETE CASCADE,
        accion VARCHAR(50) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
""")
print("[OK] cobertura_emergencia table")

c_test.commit()
print("[OK] Migraciones post-sync aplicadas")

# ── 6. VERIFICACION ──
print("\nVERIFICACION (filas TEST vs PROD):")
fallos_copiados = []
for tabla, _columnas in TABLAS:
    try:
        cur_test.execute(f'SELECT COUNT(*) FROM "{tabla}"')
        n_test = cur_test.fetchone()[0]
        cur_prod.execute(f'SELECT COUNT(*) FROM "{tabla}"')
        n_prod = cur_prod.fetchone()[0]
        if n_test == n_prod:
            print(f"  {tabla}: {n_test} OK")
        else:
            fallos_copiados.append((tabla, n_test, n_prod))
            print(f"  {tabla}: {n_test} (PROD {n_prod}) DIFIERE")
    except Exception as e:
        print(f"  {tabla}: ERROR {e}")
        fallos.append((tabla, f"verificacion: {e}"))

try:
    cur_test.execute("SELECT COUNT(*) FROM transacciones_financieras")
    print(f"  transacciones_financieras: {cur_test.fetchone()[0]} (preservadas de TEST)")
except Exception:
    print("  transacciones_financieras: 0")

cur_prod.close()
c_prod.close()
cur_test.close()
c_test.close()

if fallos or fallos_copiados:
    print("\n" + "=" * 60)
    print("  [FALLO] sync INCOMPLETO: TEST NO es copia fiel de PROD")
    for tabla, err in fallos:
        print(f"    - {tabla}: {err}")
    for tabla, n_test, n_prod in fallos_copiados:
        print(f"    - {tabla}: TEST={n_test} PROD={n_prod}")
    print("  Revisar el error y volver a correr el sync (es idempotente).")
    print("=" * 60)
    sys.exit(1)

print("\nSYNC COMPLETE")

# 7. OVERRIDES DE DESARROLLO (solo TEST)
print("\n[OVERRIDES] Aplicando overrides de desarrollo en TEST...")
ret = subprocess.call(
    [sys.executable, os.path.join(
        BACKEND_DIR, "scripts", "aplicar_overrides_test.py")],
    env={**os.environ, "ENVIRONMENT": "test"}
)
print(f"[OVERRIDES] Exit: {ret}")
