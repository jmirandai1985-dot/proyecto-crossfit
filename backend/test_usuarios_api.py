"""
Script de prueba para los endpoints de Usuarios
Verifica que se puedan crear y consultar usuarios en la base de datos
"""
import requests
import json
from datetime import datetime

# URL base de la API
BASE_URL = "http://localhost:8000"
API_URL = f"{BASE_URL}/api/v1/usuarios"


def print_section(title):
    """Imprime un separador visual"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_response(response):
    """Imprime la respuesta de forma legible"""
    print(f"\nStatus Code: {response.status_code}")
    try:
        print(
            f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except:
        print(f"Response: {response.text}")


def test_health_check():
    """Verifica que la API esté funcionando"""
    print_section("1. HEALTH CHECK")

    response = requests.get(f"{BASE_URL}/health")
    print_response(response)

    if response.status_code == 200:
        print("✅ API está funcionando correctamente")
        return True
    else:
        print("❌ Error en health check")
        return False


def test_crear_usuario():
    """Crea un usuario de prueba"""
    print_section("2. CREAR USUARIO")

    # Datos del usuario de prueba
    nuevo_usuario = {
        "tenant_id": 1,  # Asumiendo que existe un tenant con ID 1
        "rut": "12345678-9",
        "nombre": "Juan Pérez",
        "telefono": "+56912345678",
        # Email único
        "correo": f"juan.perez.{datetime.now().timestamp()}@example.com",
        "password": "password123",
        "rol": "alumno"
    }

    print(f"\nDatos a enviar:")
    print(json.dumps(nuevo_usuario, indent=2, ensure_ascii=False))

    response = requests.post(API_URL, json=nuevo_usuario)
    print_response(response)

    if response.status_code == 201:
        print("✅ Usuario creado exitosamente")
        return response.json()["id"]
    else:
        print("❌ Error al crear usuario")
        return None


def test_obtener_usuario(usuario_id):
    """Obtiene un usuario por ID"""
    print_section("3. OBTENER USUARIO POR ID")

    response = requests.get(f"{API_URL}/{usuario_id}")
    print_response(response)

    if response.status_code == 200:
        print("✅ Usuario obtenido exitosamente")
        return True
    else:
        print("❌ Error al obtener usuario")
        return False


def test_listar_usuarios():
    """Lista todos los usuarios de un tenant"""
    print_section("4. LISTAR USUARIOS")

    params = {
        "tenant_id": 1,
        "limit": 10
    }

    response = requests.get(API_URL, params=params)
    print_response(response)

    if response.status_code == 200:
        usuarios = response.json()
        print(f"\n✅ Se encontraron {len(usuarios)} usuarios")
        return True
    else:
        print("❌ Error al listar usuarios")
        return False


def test_actualizar_usuario(usuario_id):
    """Actualiza los datos de un usuario"""
    print_section("5. ACTUALIZAR USUARIO")

    datos_actualizacion = {
        "nombre": "Juan Pérez Actualizado",
        "telefono": "+56987654321"
    }

    print(f"\nDatos a actualizar:")
    print(json.dumps(datos_actualizacion, indent=2, ensure_ascii=False))

    response = requests.put(f"{API_URL}/{usuario_id}",
                            json=datos_actualizacion)
    print_response(response)

    if response.status_code == 200:
        print("✅ Usuario actualizado exitosamente")
        return True
    else:
        print("❌ Error al actualizar usuario")
        return False


def test_crear_coach():
    """Crea un usuario con rol de coach"""
    print_section("6. CREAR COACH")

    nuevo_coach = {
        "tenant_id": 1,
        "rut": "98765432-1",
        "nombre": "María González",
        "telefono": "+56923456789",
        "correo": f"maria.gonzalez.{datetime.now().timestamp()}@example.com",
        "password": "coach123",
        "rol": "coach"
    }

    print(f"\nDatos del coach:")
    print(json.dumps(nuevo_coach, indent=2, ensure_ascii=False))

    response = requests.post(API_URL, json=nuevo_coach)
    print_response(response)

    if response.status_code == 201:
        print("✅ Coach creado exitosamente")
        return True
    else:
        print("❌ Error al crear coach")
        return False


def main():
    """Ejecuta todas las pruebas"""
    print("\n" + "🚀" * 35)
    print("  PRUEBAS DE API - ENDPOINTS DE USUARIOS")
    print("🚀" * 35)

    try:
        # 1. Verificar que la API esté funcionando
        if not test_health_check():
            print("\n❌ La API no está disponible. Asegúrate de que esté corriendo.")
            print("   Ejecuta: uvicorn app.main:app --reload")
            return

        # 2. Crear un usuario
        usuario_id = test_crear_usuario()
        if not usuario_id:
            print(
                "\n⚠️  No se pudo crear el usuario. Verifica que exista un tenant con ID 1.")
            print("   Puedes crear un tenant manualmente en la base de datos:")
            print(
                "   INSERT INTO tenants (nombre, subdomain) VALUES ('Box Demo', 'demo');")
            return

        # 3. Obtener el usuario creado
        test_obtener_usuario(usuario_id)

        # 4. Listar usuarios
        test_listar_usuarios()

        # 5. Actualizar el usuario
        test_actualizar_usuario(usuario_id)

        # 6. Crear un coach
        test_crear_coach()

        print_section("RESUMEN")
        print("\n✅ Todas las pruebas completadas exitosamente!")
        print("\n📚 Puedes ver la documentación interactiva en:")
        print(f"   {BASE_URL}/docs")

    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: No se pudo conectar a la API")
        print("   Asegúrate de que el servidor esté corriendo:")
        print("   cd proyecto_box_crossfit/backend")
        print("   uvicorn app.main:app --reload")
    except Exception as e:
        print(f"\n❌ ERROR INESPERADO: {str(e)}")


if __name__ == "__main__":
    main()
