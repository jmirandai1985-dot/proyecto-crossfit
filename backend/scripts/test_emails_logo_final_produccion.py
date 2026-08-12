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

print("🚀 REENVIANDO 6 EMAILS CON LOGO FINAL MEJORADO")
print("=" * 70)
print("Logo: Borde naranja, 3 líneas, TU BOX DE ÉLITE")
print("=" * 70)

emails = [
    ("📧 Email 1: Solicitud Clase Prueba",
     lambda: send_solicitud_prueba_clase("Jesús Miranda", CORREO, "TempPass123!", "http://localhost:5173/login")),

    ("📧 Email 2: Bienvenida Activación",
     lambda: send_bienvenida_activacion("Jesús Miranda", CORREO, "FinalPass123!", "Plan CrossFit Pro", 16, "11 de septiembre de 2026", "http://localhost:5173/dashboard")),

    ("📧 Email 3: Renovación Plan",
     lambda: send_renovacion_plan("Jesús Miranda", CORREO, "11 de septiembre de 2026", "http://localhost:5173/planes")),

    ("📧 Email 4: Alerta Inactividad",
     lambda: send_alerta_inactividad("Jesús Miranda", CORREO)),

    ("📧 Email 5: Alerta Urgencia",
     lambda: send_alerta_urgencia_renovacion("Jesús Miranda", CORREO)),

    ("📧 Email 6: Confirmación Renovación",
     lambda: send_confirmacion_renovacion_plan("Jesús Miranda", CORREO, "Plan CrossFit Pro", 16, "11 de octubre de 2026", "http://localhost:5173/dashboard"))
]

enviados = 0
errores = 0

for nombre, func in emails:
    print(f"\n{nombre}")
    try:
        result = func()
        if result:
            print("✅ ENVIADO")
            enviados += 1
        else:
            print("❌ FALLÓ")
            errores += 1
    except Exception as e:
        print(f"❌ ERROR: {e}")
        errores += 1

print("\n" + "=" * 70)
print(f"RESULTADO: {enviados}/6 enviados, {errores} errores")
print("=" * 70)
print(f"Logo: Borde naranja + URBAN/TRAINING/BOX + TU BOX DE ÉLITE")
print(f"Revisa: {CORREO}")
