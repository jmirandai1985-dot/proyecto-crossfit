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
    send_confirmacion_renovacion_plan,
    ULTIMO_ERROR_SMTP,
)

CORREO = "jmirandai1985@gmail.com"

print("🔑 Sender real:", "urban.training.box.2026@gmail.com")
print("📤 Destinatario:", CORREO)
print("🚀 REENVIANDO 6 EMAILS (verbose)")
print("=" * 70)


def _verbose(nombre, ok):
    estado = "✅ ENVIADO" if ok else "❌ FALLIDO"
    error = f" | ULTIMO_ERROR_SMTP={ULTIMO_ERROR_SMTP}" if not ok and ULTIMO_ERROR_SMTP else ""
    print(f"  {estado}: {nombre}{error}")


print("\n📧 EMAIL 1: Solicitud Clase Prueba")
try:
    ok = send_solicitud_prueba_clase(
        nombre="Jesús Miranda",
        correo=CORREO,
        password_temporal="TempPass123!",
        link_app="http://localhost:5173/login"
    )
    _verbose("solicitud_prueba_clase", ok)
except Exception as e:
    print(f"❌ Error: {e}")

print("\n📧 EMAIL 2: Bienvenida Activación")
try:
    ok = send_bienvenida_activacion(
        nombre="Jesús Miranda",
        correo=CORREO,
        password="FinalPass123!",
        plan_nombre="Plan CrossFit Pro",
        cantidad_clases=16,
        fecha_vigencia="11 de septiembre de 2026",
        link_app="http://localhost:5173/dashboard"
    )
    _verbose("bienvenida_activacion", ok)
except Exception as e:
    print(f"❌ Error: {e}")

print("\n📧 EMAIL 3: Renovación Plan")
try:
    ok = send_renovacion_plan(
        nombre="Jesús Miranda",
        correo=CORREO,
        fecha_vencimiento="11 de septiembre de 2026",
        link_renovar="http://localhost:5173/planes"
    )
    _verbose("renovacion_plan", ok)
except Exception as e:
    print(f"❌ Error: {e}")

print("\n📧 EMAIL 4: Alerta Inactividad")
try:
    ok = send_alerta_inactividad(
        nombre="Jesús Miranda",
        correo=CORREO
    )
    _verbose("alerta_inactividad", ok)
except Exception as e:
    print(f"❌ Error: {e}")

print("\n📧 EMAIL 5: Alerta Urgencia")
try:
    ok = send_alerta_urgencia_renovacion(
        nombre="Jesús Miranda",
        correo=CORREO
    )
    _verbose("alerta_urgencia_renovacion", ok)
except Exception as e:
    print(f"❌ Error: {e}")

print("\n📧 EMAIL 6: Confirmación Renovación")
try:
    ok = send_confirmacion_renovacion_plan(
        nombre="Jesús Miranda",
        correo=CORREO,
        plan_nombre="Plan CrossFit Pro",
        cantidad_clases=16,
        fecha_vigencia="11 de octubre de 2026",
        link_app="http://localhost:5173/dashboard"
    )
    _verbose("confirmacion_renovacion_plan", ok)
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 70)
print("✅ TEST COMPLETADO — Revisa jmirandai1985@gmail.com")
