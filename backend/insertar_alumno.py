"""
Script para insertar directamente el usuario alumno@urbantraining.cl en la BD.
Bypasa la validación de la API (min_length=6 en password) usando bcrypt directo.
"""
from datetime import datetime
import psycopg2
import bcrypt
import sys
import os
from app.core.config import settings
# URL se obtiene de settings.DATABASE_URL


# Agregar el directorio backend al path para importar módulos del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ── Configuración de conexión ──────────────────────────────────────────────
DATABASE_URL = (
    settings.DATABASE_URL.split("@")[0] + "@" + settings.DATABASE_URL.split("@")[1].split("/")[0]
    "@ep-withered-silence-acly7gq5-pooler.sa-east-1.aws.neon.tech"
    "/neondb?sslmode=require&channel_binding=require"
)

# ── Datos del usuario a insertar ───────────────────────────────────────────
CORREO = "alumno@urbantraining.cl"
PASSWORD = "123"
ROL = "alumno"
TENANT_ID = 1
NOMBRE = "Alumno Demo"
RUT = "11111111-1"   # RUT genérico; se cambia si ya existe
TELEFONO = None


def hash_password(password: str) -> str:
    """Genera hash bcrypt de la contraseña."""
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def main():
    # Parsear la URL para psycopg2
    # Formato: postgresql://user:pass@host/dbname?params
    url = DATABASE_URL
    url = url.replace("postgresql://", "")
    userinfo, rest = url.split("@", 1)
    user, password_db = userinfo.split(":", 1)
    hostpart, dbpart = rest.split("/", 1)
    dbname = dbpart.split("?")[0]
    host = hostpart

    conn = psycopg2.connect(
        host=host,
        dbname=dbname,
        user=user,
        password=password_db,
        sslmode="require",
    )
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 1. Verificar si el correo ya existe
        cur.execute(
            "SELECT id, correo, rol, activo FROM usuarios WHERE correo = %s AND tenant_id = %s",
            (CORREO, TENANT_ID),
        )
        existing = cur.fetchone()
        if existing:
            print(f"⚠️  El usuario '{CORREO}' ya existe en la BD:")
            print(
                f"   id={existing[0]}, correo={existing[1]}, rol={existing[2]}, activo={existing[3]}")
            print("✅ No se necesita insertar. El usuario ya está disponible.")
            return

        # 2. Verificar si el RUT ya existe; si es así, usar uno alternativo
        rut_a_usar = RUT
        cur.execute(
            "SELECT id FROM usuarios WHERE rut = %s AND tenant_id = %s",
            (rut_a_usar, TENANT_ID),
        )
        if cur.fetchone():
            # Generar un RUT alternativo único
            for i in range(2, 100):
                rut_alt = f"1111111{i}-{i % 10}"
                cur.execute(
                    "SELECT id FROM usuarios WHERE rut = %s AND tenant_id = %s",
                    (rut_alt, TENANT_ID),
                )
                if not cur.fetchone():
                    rut_a_usar = rut_alt
                    break
            print(
                f"ℹ️  RUT {RUT} ya existe. Usando RUT alternativo: {rut_a_usar}")

        # 3. Generar hash de la contraseña "123"
        password_hash = hash_password(PASSWORD)
        print(f"🔐 Hash generado para '{PASSWORD}': {password_hash[:30]}...")

        # 4. Insertar el usuario
        cur.execute(
            """
            INSERT INTO usuarios (tenant_id, rut, nombre, telefono, correo, password_hash, rol, activo, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, correo, rol, activo, created_at
            """,
            (
                TENANT_ID,
                rut_a_usar,
                NOMBRE,
                TELEFONO,
                CORREO,
                password_hash,
                ROL,
                True,
                datetime.utcnow(),
            ),
        )
        row = cur.fetchone()
        conn.commit()

        print("\n✅ Usuario insertado exitosamente:")
        print(f"   id        : {row[0]}")
        print(f"   correo    : {row[1]}")
        print(f"   rol       : {row[2]}")
        print(f"   activo    : {row[3]}")
        print(f"   created_at: {row[4]}")
        print(f"   rut       : {rut_a_usar}")
        print(f"   tenant_id : {TENANT_ID}")
        print(f"\n🔑 Credenciales de acceso:")
        print(f"   correo   : {CORREO}")
        print(f"   password : {PASSWORD}")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error al insertar usuario: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
