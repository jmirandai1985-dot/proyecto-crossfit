import os
import sys
os.environ['ENVIRONMENT'] = 'test'

# Bootstrap: permitir importar el paquete `app` (misma convencion que
# los demas scripts de backend/scripts/). El script se puede ejecutar
# desde cualquier directorio:  python scripts/enviar_emails_test.py
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from app.services.email_service import (
    send_solicitud_prueba_clase,
    send_bienvenida_activacion,
    send_renovacion_plan,
    send_vencimiento_inminente
)

CORREO_TEST = "jesusmiranda26@gmail.com"

print("🚀 Enviando emails de prueba a:", CORREO_TEST)
print("=" * 60)

# EMAIL 1: Solicitud de Clase de Prueba (Lead nuevo)
print("\n📧 Email 1: Solicitud Clase de Prueba")
try:
    send_solicitud_prueba_clase(
        nombre="Test Lead Jesús",
        correo=CORREO_TEST
    )
    print("✅ Enviado: solicitud_prueba_clase")
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 2: Bienvenida + Activación (Pago validado)
# NOTA: el parámetro real se llama `password` (no `password_provisional`)
print("\n📧 Email 2: Bienvenida + Credenciales")
try:
    send_bienvenida_activacion(
        nombre="Test Alumno Jesús",
        correo=CORREO_TEST,
        password="TestPass123!",
        link_app="http://localhost:5173/login"
    )
    print("✅ Enviado: bienvenida_activacion")
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 3: Renovación Plan (Vencimiento próximo)
# NOTA: la firma real es send_renovacion_plan(nombre, correo, fecha_vencimiento)
# (no acepta `link_renovar`; el CTA de renovación ya está fijo en la plantilla)
print("\n📧 Email 3: Renovación Plan")
try:
    send_renovacion_plan(
        nombre="Test Alumno Jesús",
        correo=CORREO_TEST,
        fecha_vencimiento="2026-08-18"
    )
    print("✅ Enviado: renovacion_plan")
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 4: Vencimiento Inminente (Último día)
print("\n📧 Email 4: Vencimiento Inminente")
try:
    send_vencimiento_inminente(
        nombre="Test Alumno Jesús",
        correo=CORREO_TEST
    )
    print("✅ Enviado: vencimiento_inminente")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 60)
print("✅ TEST COMPLETADO")
print("Revisa tu correo: jesusmiranda26@gmail.com")
