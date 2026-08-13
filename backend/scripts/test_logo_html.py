import os
import sys
os.environ['ENVIRONMENT'] = 'test'

# Bootstrap: permitir importar el paquete `app`
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from app.services.email_service import send_solicitud_prueba_clase

CORREO = "jmirandai1985@gmail.com"

print("🚀 ENVIANDO EMAIL CON LOGO MEJORADO (HTML/CSS)")
print("=" * 70)

try:
    result = send_solicitud_prueba_clase(
        nombre="Jesús Miranda",
        correo=CORREO,
        password_temporal="TempPass123!",
        link_app="http://localhost:5173/login"
    )
    if result:
        print("✅ ENVIADO")
    else:
        print("❌ FALLÓ")
except Exception as e:
    print(f"❌ ERROR: {e}")

print("=" * 70)
print(f"Revisa: {CORREO}")
print("Logo debe verse: NEGRO con letras BLANCAS + emoticones")
