"""Prueba del correo de INACTIVIDAD: el que cambia de AUDIENCIA con la fuente real de asistencia.

Por qué existe
--------------
`enviar_alertas_inactividad` (el job del scheduler y `POST /notificaciones/enviar-alertas-inactividad`)
pasó a leer la asistencia **real** (`reservas.asistio` sobre `clases.fecha`, ver
`app/services/asistencia_real.py`). Antes leía la tabla histórica `asistencias`, que NO la puebla
nadie, así que la campaña sólo podía alcanzar a quien tuviera una fila de seed. Como la audiencia
AHORA es la buena (gente que de verdad dejó de venir), hay que probar el template y el transporte
con una dirección controlada ANTES de disparar el envío masivo.

Uso (siempre con un destinatario EXPLÍCITO: este script NO dispara la campaña)

    cd backend
    py -3.12 scripts/alertas_inactividad_test.py --correo mi-correo@gmail.com
    # envío REAL: el modo de `.env.test` es `noop` a propósito, así que hay que pedirlo
    $env:EMAIL_MODO='real'; py -3.12 scripts/alertas_inactividad_test.py --correo mi-correo@gmail.com

La otra mitad de la prueba (`QUIÉN` entra) necesita la base TEST:

    py -3.12 _demo_seed_alertas.py          # siembra el caso "Inactivo 7+" con tu correo real
    py -3.12 -c "from app.db.database import SessionLocal; from app.services.alertas_email_service import enviar_alertas_inactividad as f; db=SessionLocal(); print(f(db)); db.close()"

⚠️ El segundo comando dispara la campaña de TODOS los ausentes de +7 días de ese box. Con la base
de prueba actual eso puede ser mucha gente: por eso `EMAIL_MODO=noop` (simulacro) o una base TEST
son la forma segura de correrlo.
"""
import argparse
import os
import sys

os.environ['ENVIRONMENT'] = 'test'   # misma convención que los demás scripts de scripts/

# Bootstrap: permitir importar el paquete `app` desde cualquier directorio.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from app.core.config import settings                              # noqa: E402
from app.services.email_service import (ULTIMO_ERROR_SMTP,        # noqa: E402
                                       send_alerta_inactividad)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manda UN correo de inactividad a una dirección controlada (prueba del "
                    "template y del transporte; NO dispara la campaña).")
    parser.add_argument("--correo", required=True,
                        help="destinatario de la prueba: usá tu propio correo")
    parser.add_argument("--nombre", default="Alumno de prueba")
    args = parser.parse_args()

    print("=" * 60)
    print("correo de inactividad (send_alerta_inactividad)")
    print("  EMAIL_MODO          :", settings.EMAIL_MODO)
    print("  SMTP configurado    :",
          bool(settings.GMAIL_SMTP_USER and settings.GMAIL_SMTP_APP_PASSWORD))
    print("  destinatario        :", args.correo)
    print("=" * 60)
    if settings.EMAIL_MODO != "real":
        print("AVISO: EMAIL_MODO != 'real': el correo NO sale (queda simulado).")
        print("       Para el envío real:  $env:EMAIL_MODO='real'; py -3.12 "
              "scripts/alertas_inactividad_test.py --correo <tu correo>")

    # registrar=False: no escribe en `notificaciones_enviadas` (es una PRUEBA, no una campaña).
    ok = send_alerta_inactividad(args.nombre, args.correo, registrar=False)
    etiqueta = "ENVIADO" if ok else "FALLÓ"
    if ok and settings.EMAIL_MODO != "real":
        etiqueta = f"SIMULADO (no salió ningún correo: EMAIL_MODO={settings.EMAIL_MODO})"
    print("resultado            :", etiqueta)
    if ULTIMO_ERROR_SMTP:
        print("último error SMTP    :", ULTIMO_ERROR_SMTP)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
