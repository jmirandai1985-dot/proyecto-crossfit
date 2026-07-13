"""
Script simple de prueba de conexión a Neon PostgreSQL
Ejecutar con: python test_db_simple.py
"""
import psycopg2
from urllib.parse import urlparse
from app.core.config import settings
DATABASE_URL = settings.DATABASE_URL


# Cadena de conexión
# DATABASE_URL ahora se obtiene de settings


def test_connection():
    print("=" * 60)
    print("PRUEBA DE CONEXIÓN A NEON POSTGRESQL")
    print("=" * 60)

    # Parsear URL para mostrar info
    parsed = urlparse(DATABASE_URL)
    print(f"\n🔗 Host: {parsed.hostname}")
    print(f"🗄️  Base de datos: {parsed.path[1:]}")
    print(f"👤 Usuario: {parsed.username}")

    try:
        # Conectar a la base de datos
        print("\n⏳ Conectando...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Verificar versión
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]

        print("\n✅ CONEXIÓN EXITOSA!")
        print(f"\n📌 Versión PostgreSQL:")
        print(f"   {version.split(',')[0]}")

        # Verificar tablas existentes
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()

        if tables:
            print(f"\n📋 Tablas existentes ({len(tables)}):")
            for table in tables:
                print(f"   - {table[0]}")
        else:
            print("\n⚠️  No hay tablas creadas aún.")
            print("   Las tablas se crearán a continuación.")

        # Verificar tipos ENUM
        cursor.execute("""
            SELECT typname 
            FROM pg_type 
            WHERE typtype = 'e'
            ORDER BY typname
        """)
        enums = cursor.fetchall()

        if enums:
            print(f"\n🏷️  Tipos ENUM ({len(enums)}):")
            for enum in enums:
                print(f"   - {enum[0]}")

        cursor.close()
        conn.close()

        print("\n" + "=" * 60)
        print("✨ PRUEBA COMPLETADA EXITOSAMENTE")
        print("=" * 60)
        return True

    except Exception as e:
        print("\n❌ ERROR DE CONEXIÓN!")
        print(f"\n🔴 {type(e).__name__}: {str(e)}")
        print("\n💡 Verifica:")
        print("   1. La cadena de conexión es correcta")
        print("   2. Tu conexión a internet funciona")
        print("   3. Las credenciales son válidas")
        print("\n" + "=" * 60)
        return False


if __name__ == "__main__":
    test_connection()
