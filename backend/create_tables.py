"""
Script para crear SOLO la tabla asistencias
Ignora tablas y ENUMs que ya existen en Neon
"""
import psycopg2
from app.core.config import settings
DATABASE_URL = settings.DATABASE_URL


# DATABASE_URL ahora se obtiene de settings


def create_tables():
    print("=" * 60)
    print("CREANDO TABLA ASISTENCIAS EN NEON POSTGRESQL")
    print("=" * 60)

    try:
        print("\n⏳ Conectando a la base de datos...")
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        print("✅ Conexión establecida")

        # Crear tabla asistencias — IF NOT EXISTS evita el error
        print("\n🔨 Creando tabla asistencias...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asistencias (
                id          SERIAL PRIMARY KEY,
                tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                fecha       DATE NOT NULL,
                clase       VARCHAR(100) DEFAULT 'WOD',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        print("✅ Tabla asistencias lista")

        # Crear índices para búsquedas rápidas
        print("\n🔨 Creando índices...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_asistencias_tenant
            ON asistencias(tenant_id);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_asistencias_usuario
            ON asistencias(usuario_id);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_asistencias_fecha
            ON asistencias(fecha);
        """)
        print("✅ Índices listos")

        # Verificar tablas actuales
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        print(f"\n📋 Tablas en BD ({len(tables)}):")
        for table in tables:
            print(f"   ✓ {table[0]}")

        cursor.close()
        conn.close()

        print("\n" + "=" * 60)
        print("✨ LISTO — Puedes correr el servidor")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {str(e)}")
        return False


if __name__ == "__main__":
    create_tables()
