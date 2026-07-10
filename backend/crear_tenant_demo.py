"""
Script para crear un tenant de demostración
Necesario para poder probar los endpoints de usuarios
"""
from app.core.config import settings
import psycopg2
from pathlib import Path
import sys

# Agregar el directorio backend al path para importar settings
sys.path.insert(0, str(Path(__file__).parent))


def crear_tenant_demo():
    """Crea un tenant de demostración si no existe"""
    print("=" * 60)
    print("CREACIÓN DE TENANT DE DEMOSTRACIÓN")
    print("=" * 60)

    try:
        # Conectar a la base de datos
        print("\n⏳ Conectando a la base de datos...")
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        print("✅ Conexión establecida")

        # Verificar si ya existe un tenant
        cursor.execute("SELECT id, nombre, subdomain FROM tenants LIMIT 1")
        existing_tenant = cursor.fetchone()

        if existing_tenant:
            print(f"\n✅ Ya existe un tenant en la base de datos:")
            print(f"   ID: {existing_tenant[0]}")
            print(f"   Nombre: {existing_tenant[1]}")
            print(f"   Subdomain: {existing_tenant[2]}")
        else:
            # Crear tenant de demostración
            print("\n🔨 Creando tenant de demostración...")
            cursor.execute("""
                INSERT INTO tenants (nombre, subdomain, activo)
                VALUES ('Box Demo', 'demo', TRUE)
                RETURNING id, nombre, subdomain
            """)

            tenant = cursor.fetchone()
            print(f"\n✅ Tenant creado exitosamente:")
            print(f"   ID: {tenant[0]}")
            print(f"   Nombre: {tenant[1]}")
            print(f"   Subdomain: {tenant[2]}")

        cursor.close()
        conn.close()

        print("\n" + "=" * 60)
        print("✨ TENANT LISTO PARA USAR")
        print("=" * 60)
        print("\nAhora puedes ejecutar el script de prueba:")
        print("   python test_usuarios_api.py")

        return True

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False


if __name__ == "__main__":
    crear_tenant_demo()
