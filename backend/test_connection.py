"""
Script de prueba de conexión a la base de datos Neon
Ejecutar con: python test_connection.py
"""
import sys
from sqlalchemy import create_engine, text
from app.core.config import settings


def test_database_connection():
    """
    Prueba la conexión a la base de datos PostgreSQL en Neon
    """
    print("=" * 60)
    print("PRUEBA DE CONEXIÓN A BASE DE DATOS NEON")
    print("=" * 60)
    print(f"\n📊 Aplicación: {settings.APP_NAME} v{settings.APP_VERSION}")
    print(
        f"🔗 Conectando a: {settings.DATABASE_URL.split('@')[1].split('/')[0]}...")
    print(
        f"🗄️  Base de datos: {settings.DATABASE_URL.split('/')[-1].split('?')[0]}")

    try:
        # Crear motor de base de datos
        engine = create_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True
        )

        # Intentar conectar y ejecutar una consulta simple
        with engine.connect() as connection:
            # Verificar versión de PostgreSQL
            result = connection.execute(text("SELECT version()"))
            version = result.fetchone()[0]

            print("\n✅ CONEXIÓN EXITOSA!")
            print(f"\n📌 Versión de PostgreSQL:")
            print(f"   {version.split(',')[0]}")

            # Verificar si existen tablas
            result = connection.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))
            tables = result.fetchall()

            if tables:
                print(
                    f"\n📋 Tablas existentes en la base de datos ({len(tables)}):")
                for table in tables:
                    print(f"   - {table[0]}")
            else:
                print("\n⚠️  No se encontraron tablas en la base de datos.")
                print("   Las tablas se crearán cuando ejecutes los modelos.")

            # Verificar tipos ENUM personalizados
            result = connection.execute(text("""
                SELECT typname 
                FROM pg_type 
                WHERE typtype = 'e'
                ORDER BY typname
            """))
            enums = result.fetchall()

            if enums:
                print(f"\n🏷️  Tipos ENUM personalizados ({len(enums)}):")
                for enum in enums:
                    print(f"   - {enum[0]}")

        print("\n" + "=" * 60)
        print("✨ PRUEBA COMPLETADA EXITOSAMENTE")
        print("=" * 60)
        return True

    except Exception as e:
        print("\n❌ ERROR DE CONEXIÓN!")
        print(f"\n🔴 Detalles del error:")
        print(f"   {type(e).__name__}: {str(e)}")
        print("\n💡 Posibles soluciones:")
        print("   1. Verifica que la cadena DATABASE_URL en .env sea correcta")
        print("   2. Asegúrate de que tu IP esté permitida en Neon")
        print("   3. Verifica tu conexión a internet")
        print("   4. Confirma que las credenciales sean válidas")
        print("\n" + "=" * 60)
        return False


if __name__ == "__main__":
    success = test_database_connection()
    sys.exit(0 if success else 1)
