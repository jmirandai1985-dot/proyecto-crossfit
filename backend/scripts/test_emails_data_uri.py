import os
import sys
os.environ['ENVIRONMENT'] = 'test'

# Bootstrap: permitir importar el paquete `app`
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from app.services.email_service import (
    send_solicitud_prueba_clase,
    send_bienvenida_activacion,
    send_renovacion_plan,
    send_alerta_inactividad,
    send_alerta_urgencia_renovacion,
    send_confirmacion_renovacion_plan
)

CORREO = "jmirandai1985@gmail.com"

print("🚀 Enviando 6 EMAILS CON LOGO DATA URI")
print("=" * 70)


def _check(nombre, ok):
    print(f"  {'✅' if ok else '⚠️'} {nombre}: {'Enviado' if ok else 'Falló'}")


# EMAIL 1
print("\n📧 EMAIL 1: Solicitud Clase Prueba")
try:
    result = send_solicitud_prueba_clase(
        nombre="Jesús Miranda",
        correo=CORREO,
        password_temporal="TempPass123!",
        link_app="http://localhost:5173/login"
    )
    _check("solicitud_prueba_clase", result)
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 2
print("\n📧 EMAIL 2: Bienvenida Activación")
try:
    result = send_bienvenida_activacion(
        nombre="Jesús Miranda",
        correo=CORREO,
        password="FinalPass123!",
        plan_nombre="Plan CrossFit Pro",
        cantidad_clases=16,
        fecha_vigencia="11 de septiembre de 2026",
        link_app="http://localhost:5173/dashboard"
    )
    _check("bienvenida_activacion", result)
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 3
print("\n📧 EMAIL 3: Renovación Plan")
try:
    result = send_renovacion_plan(
        nombre="Jesús Miranda",
        correo=CORREO,
        fecha_vencimiento="11 de septiembre de 2026",
        link_renovar="http://localhost:5173/planes"
    )
    _check("renovacion_plan", result)
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 4
print("\n📧 EMAIL 4: Alerta Inactividad")
try:
    result = send_alerta_inactividad(
        nombre="Jesús Miranda",
        correo=CORREO
    )
    _check("alerta_inactividad", result)
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 5
print("\n📧 EMAIL 5: Alerta Urgencia")
try:
    result = send_alerta_urgencia_renovacion(
        nombre="Jesús Miranda",
        correo=CORREO
    )
    _check("alerta_urgencia_renovacion", result)
except Exception as e:
    print(f"❌ Error: {e}")

# EMAIL 6
print("\n📧 EMAIL 6: Confirmación Renovación")
try:
    result = send_confirmacion_renovacion_plan(
        nombre="Jesús Miranda",
        correo=CORREO,
        plan_nombre="Plan CrossFit Pro",
        cantidad_clases=16,
        fecha_vigencia="11 de octubre de 2026",
        link_app="http://localhost:5173/dashboard"
    )
    _check("confirmacion_renovacion_plan", result)
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 70)
print("✅ TEST COMPLETADO")
print("Revisa: jmirandai1985@gmail.com")
print("Logo debe estar INLINE (embebido en HTML), NO en datos adjuntos")
