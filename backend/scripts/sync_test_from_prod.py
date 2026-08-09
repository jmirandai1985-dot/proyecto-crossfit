"""
SYNC PROD -> TEST (lingering-shape).
IDEMPOTENTE: TRUNCATE + copia todos los datos desde PRODUCCIÃ“N.
Preserva tablas custom (transacciones_financieras) mediante backup/restore.
Incluye migraciones post-sync (requiere_coach, es_estudiante, coach_disciplinas, cobertura_emergencia).
"""
import subprocess
import psycopg2
import os
import sys
import importlib

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

# â”€â”€ SEGURIDAD: Verificar ENVIRONMENT â”€â”€
ENV = os.environ.get("ENVIRONMENT", "")
if ENV != "test":
    print("="*60)
    print("  ERROR: ENVIRONMENT no es 'test'")
    print("  Si ejecutas esto sin ENVIRONMENT=test borraras PRODUCCION")
    print("  Abortando.")
    sys.exit(1)

os.environ["ENVIRONMENT"] = "test"

# â”€â”€ URLs â”€â”€
# TEST: se obtiene de settings (carga .env.test)
settings = importlib.import_module("app.core.config").settings
URL_TEST = settings.DATABASE_URL

# PROD: hardcodeada desde .env (withered-silence)
URL_PROD = "postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


print("="*60)
print(f"BD de TEST: {URL_TEST[:100]}...")
print(f"lingering-shape (DIRECT): {'lingering-shape' in URL_TEST}")
print("="*60)

# â”€â”€ CONECTAR â”€â”€
c_prod = psycopg2.connect(URL_PROD)
c_test = psycopg2.connect(URL_TEST)
c_test.autocommit = True
cur_prod = c_prod.cursor()
cur_test = c_test.cursor()

# â”€â”€ 1. RESPALDAR tablas custom â”€â”€
print("\n[BACKUP] Respaldo transacciones_financieras...")
try:
    cur_test.execute(
        "SELECT id, tenant_id, tipo, categoria, monto, descripcion, referencia_tipo, referencia_id, fecha, created_at FROM transacciones_financieras ORDER BY id")
    backup_tx = cur_test.fetchall()
    print(f"  {len(backup_tx)} transacciones respaldadas")
except Exception as e:
    print(f"  No hay datos para respaldar: {e}")
    backup_tx = []

# â”€â”€ 2. TRUNCATE CASCADE TEST â”€â”€
print("\nTRUNCATE CASCADE TEST...")
cur_test.execute("""
    TRUNCATE TABLE
        tenants, usuarios, movimientos, disciplinas, planes, horarios,
        clases, reservas, historial_rm, notificaciones, productos, pedidos,
        suscripciones, coach_disciplinas, cobertura_emergencia, wods, wod_movimientos,
        transacciones_financieras
    CASCADE
""")
print("TEST limpia")

cur_test.execute("ALTER TABLE disciplinas DROP COLUMN IF EXISTS requiere_coach")
cur_test.execute("ALTER TABLE planes DROP COLUMN IF EXISTS es_estudiante")
cur_test.execute("ALTER TABLE planes ADD COLUMN IF NOT EXISTS requiere_certificado_estudiante BOOLEAN NOT NULL DEFAULT false")

# â”€â”€ 3. COPIAR PRODâ†’TEST (tablas estÃ¡ndar) â”€â”€
print("\nCopiando PROD->TEST...")
TABLAS = [
    ("tenants", None),
    ("movimientos", "id, tenant_id, nombre, descripcion, categoria, activo, created_at, updated_at"),
    ("disciplinas", None),
    ("planes", None),
    ("horarios", None),
    ("usuarios", None),
    ("suscripciones", None),
    ("productos", None),
    ("clases", None),
    ("reservas", None),
    ("historial_rm", None),
    ("notificaciones", None),
]

for tabla, columnas in TABLAS:
    cols = columnas or "*"
    try:
        cur_prod.execute(f"SELECT {cols} FROM {tabla}")
        rows = cur_prod.fetchall()
        if not rows:
            continue
        col_names = [desc[0] for desc in cur_prod.description]
        placeholders = ",".join(["%s"] * len(col_names))
        cols_str = ",".join(col_names)
        for row in rows:
            cur_test.execute(
                f"INSERT INTO {tabla} ({cols_str}) VALUES ({placeholders})", row)
        print(f"  {tabla}: {len(rows)}")
    except Exception as e:
        print(f"  {tabla}: ERROR {e}")

c_test.commit()

# â”€â”€ 4. RESTAURAR tablas custom â”€â”€
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
    print("  Sin datos para restaurar (tabla estaba vacÃ­a)")

# â”€â”€ 5. MIGRACIONES POST-SYNC (antes eran _apply_migrations_post_sync.py) â”€â”€
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
cur_test.execute("INSERT INTO coach_disciplinas (tenant_id, coach_id, disciplina_id) SELECT 1, id, 1 FROM usuarios WHERE rol='coach' AND tenant_id=1 AND activo=true AND NOT EXISTS (SELECT 1 FROM coach_disciplinas cd WHERE cd.coach_id=usuarios.id AND cd.disciplina_id=1)")
print("[OK] coach_disciplinas table + inserts")

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

# â”€â”€ 6. VERIFICACION â”€â”€
print("\nVERIFICACION:")
for tabla in ["tenants", "movimientos", "disciplinas", "planes", "horarios",
              "usuarios", "suscripciones", "productos", "clases", "reservas",
              "historial_rm", "notificaciones"]:
    try:
        cur_test.execute(f"SELECT COUNT(*) FROM {tabla}")
        print(f"  {tabla}: {cur_test.fetchone()[0]}")
    except:
        print(f"  {tabla}: ERROR")

try:
    cur_test.execute("SELECT COUNT(*) FROM transacciones_financieras")
    print(f"  transacciones_financieras: {cur_test.fetchone()[0]}")
except:
    print(f"  transacciones_financieras: 0")

cur_prod.close()
c_prod.close()
cur_test.close()
c_test.close()

print("\nSYNC COMPLETE")

# 7. OVERRIDES DE DESARROLLO (solo TEST)
print("\n[OVERRIDES] Aplicando overrides de desarrollo en TEST...")
ret = subprocess.call(
    [sys.executable, os.path.join(
        BACKEND_DIR, "scripts", "aplicar_overrides_test.py")],
    env={**os.environ, "ENVIRONMENT": "test"}
)
print(f"[OVERRIDES] Exit: {ret}")
