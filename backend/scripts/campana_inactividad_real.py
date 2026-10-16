"""Campaña de INACTIVIDAD **real** (envío de verdad) contra la base de TEST.

Por qué existe
--------------
`enviar_alertas_inactividad` —el job de las 09:00 CLT y
`POST /notificaciones/enviar-alertas-inactividad`— pasó a leer la asistencia **real**
(`reservas.asistio` sobre `clases.fecha`, ver `app/services/asistencia_real.py`). Con eso
cambió la AUDIENCIA: antes sólo entraba quien tuviera una fila de la tabla histórica
`asistencias` (que nadie puebla); ahora entran los que de verdad dejaron de venir (256 en la
base de prueba al 2026-10-16).

`email_service.modo_envio()` tiene un FAIL-SAFE a propósito: fuera de producción
(`ENVIRONMENT != production`) fuerza `noop` **aunque** `EMAIL_MODO=real`, para que un `.env`
cruzado no pueda mandar correo real por accidente. Este script lo desactiva de forma
EXPLÍCITA y ACOTADA —decisión del usuario (2026-10-16): la base es de prueba y las únicas
direcciones reales son 4-5 suyas— y lo compensa con guardas propias, en este orden:

  1. `ENVIRONMENT=production` + `EMAIL_MODO=real`: lo ÚNICO que habilita el envío real.
  2. La `DATABASE_URL` TIENE que ser la de TEST (`is_test_db_url`): si no, ABORTA sin mandar
     nada. Así los destinatarios son los de la base de prueba, nunca los de PROD.
  3. Login SMTP de prueba ANTES de la tanda: si la credencial o la red fallan se aborta con
     0 correos enviados. Es imprescindible porque cada envío se RECLAMA con un índice único
     (alumno, tipo, día) y un intento fallido NO se puede repetir el mismo día.
  4. `--si` es obligatorio para enviar; sin él (`--dry-run`) sólo cuenta, muestra el padrón de
     dominios y prueba el login.

Uso (PowerShell, desde backend/):
    py -3.12 scripts/campana_inactividad_real.py --dry-run       # cuenta + login SMTP
    py -3.12 scripts/campana_inactividad_real.py --si            # ENVÍA la campaña

Notas operativas
----------------
* Los links del correo (logo y CTA) salen de `FRONTEND_URL`/`BACKEND_PUBLIC_URL`. Con lo que
  dice `.env.test` apuntan a `localhost`; se pueden pisar con `--frontend-url`/`--backend-url`
  si se quiere una campaña con URLs públicas.
* El reporte final se lee de la BD (`notificaciones_enviadas` del día), no del contador en
  memoria.
"""
import argparse
import os
import sys
import time
from collections import Counter

# Bootstrap: permitir importar el paquete `app` desde cualquier directorio.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

ENV_TEST = os.path.join(BACKEND_DIR, ".env.test")


def _valor_limpio(valor: str) -> str:
    """Valor sin comillas ni comentario en línea (`...=60  # 1 hora` → `60`)."""
    v = valor.strip()
    if len(v) > 1 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    for i, ch in enumerate(v):
        if ch == "#" and i > 0 and v[i - 1] in " \t":
            return v[:i].rstrip()
    return v


def _cargar_env_test() -> None:
    """Inyecta `.env.test` en el entorno del proceso ANTES de importar settings.

    Los valores del sistema tienen prioridad sobre el `env_file` de pydantic-settings: así,
    aunque con `ENVIRONMENT=production` la app cargue `backend/.env`, la conexión, el SMTP y
    las URLs salen de `.env.test` (= la base y el box de prueba).
    """
    with open(ENV_TEST, encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            clave, sep, valor = linea.partition("=")
            if not sep:
                continue
            os.environ[clave.strip()] = _valor_limpio(valor)


def _preparar_entorno(args) -> None:
    """Deja el proceso en (base TEST + SMTP real), el único combo que queremos acá."""
    _cargar_env_test()
    os.environ["ENVIRONMENT"] = "production"     # ← desactiva el fail-safe (ver docstring)
    os.environ["EMAIL_MODO"] = "real"
    if args.frontend_url:
        os.environ["FRONTEND_URL"] = args.frontend_url
    if args.backend_url:
        os.environ["BACKEND_PUBLIC_URL"] = args.backend_url


def _probar_smtp(usuario: str, clave: str) -> tuple:
    """Login real contra Gmail (sin mandar correo). Devuelve `(ok, detalle)`."""
    import smtplib
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(usuario, clave)
        return True, "login OK"
    except Exception as e:  # noqa: BLE001 (se reporta tal cual al operador)
        return False, f"{type(e).__name__}: {e}"


def _candidatos(db, tenant_id: int, umbral_dias: int) -> tuple:
    """El padrón que va a recorrer la campaña, con los MISMOS filtros que el job.

    Sólo lectura: la selección se copia del job (`enviar_alertas_inactividad`) y el dedupe
    usa su propio `_ya_enviado`, pero NO se reclama ningún envío (eso lo hace la corrida
    real). Sirve para ver el padrón antes de disparar.
    """
    from datetime import timedelta

    from sqlalchemy import text

    from app.services.alertas_email_service import _ya_enviado
    from app.services.asistencia_real import sql_cte_asistencias
    from app.utils.santiago import hoy_santiago

    rows = db.execute(text(f"""
        WITH {sql_cte_asistencias()}
        SELECT u.id, u.nombre, u.correo,
               (SELECT MAX(a.fecha) FROM asistencias a WHERE a.usuario_id = u.id) AS ultima
        FROM usuarios u
        WHERE u.tenant_id = :tid
          AND u.rol = 'alumno'
          AND u.estado = 'activo'
    """), {"tid": tenant_id}).fetchall()

    limite = hoy_santiago() - timedelta(days=umbral_dias)
    dentro = [r for r in rows if r.ultima is not None and r.ultima <= limite]
    ya = [r for r in dentro if _ya_enviado(db, r.id, "inactividad", dias=umbral_dias)]
    return dentro, ya, len(rows)


def _reporte_bd(db, hoy, tipo: str = "inactividad") -> dict:
    """Evidencia final leída de la BD: cuántas filas por estado y por qué fallaron."""
    from sqlalchemy import text
    por_estado = db.execute(text("""
        SELECT estado, COUNT(*) FROM notificaciones_enviadas
         WHERE tipo = :tipo AND dia_chile = :dia
         GROUP BY estado ORDER BY 2 DESC
    """), {"tipo": tipo, "dia": hoy}).fetchall()
    motivos = db.execute(text("""
        SELECT detalle_error, COUNT(*) FROM notificaciones_enviadas
         WHERE tipo = :tipo AND dia_chile = :dia AND estado = 'fallido'
         GROUP BY detalle_error ORDER BY 2 DESC LIMIT 10
    """), {"tipo": tipo, "dia": hoy}).fetchall()
    return {"por_estado": [(r[0], r[1]) for r in por_estado],
            "motivos_fallo": [(str(r[0])[:120], r[1]) for r in motivos]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Campaña de inactividad REAL contra la base de TEST (SMTP real).")
    parser.add_argument("--dry-run", action="store_true",
                        help="sólo cuenta el padrón y prueba el SMTP; NO manda ni reclama nada")
    parser.add_argument("--si", action="store_true",
                        help="confirma el envío masivo (obligatorio para mandar de verdad)")
    parser.add_argument("--tenant", type=int, default=1)
    parser.add_argument("--umbral", type=int, default=7,
                        help="días sin asistencia para entrar en la campaña (default 7)")
    parser.add_argument("--frontend-url", default="",
                        help="pisa FRONTEND_URL (links del correo)")
    parser.add_argument("--backend-url", default="",
                        help="pisa BACKEND_PUBLIC_URL (logo del correo)")
    args = parser.parse_args()

    _preparar_entorno(args)

    from app.core.config import is_test_db_url, settings
    from app.services.email_service import MODO_REAL, ULTIMO_ERROR_SMTP, modo_envio

    print("=" * 78)
    print("CAMPAÑA DE INACTIVIDAD — envío REAL contra la base de TEST")
    print("=" * 78)
    print("  ENVIRONMENT          :", os.environ.get("ENVIRONMENT"))
    print("  EMAIL_MODO           :", settings.EMAIL_MODO)
    print("  modo_envio() efectivo:", modo_envio())
    print("  FRONTEND_URL         :", settings.FRONTEND_URL)
    print("  BACKEND_PUBLIC_URL   :", settings.BACKEND_PUBLIC_URL)
    anfitrion = settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "?"
    print("  DATABASE_URL (host)  :", anfitrion)

    # ── GUARDA 1: la base tiene que ser TEST ─────────────────────────────────
    if not is_test_db_url(settings.DATABASE_URL):
        print("\nABORTA: la DATABASE_URL no es una rama de TEST conocida "
              "(no se manda ningún correo).")
        return 2

    # ── GUARDA 2: el envío tiene que estar en modo real ──────────────────────
    if modo_envio() != MODO_REAL:
        print(f"\nABORTA: modo_envio()={modo_envio()!r} (se esperaba 'real').")
        return 2

    # ── GUARDA 3: credenciales SMTP presentes y con login válido ─────────────
    usuario = (settings.GMAIL_SMTP_USER or "").strip()
    clave = (settings.GMAIL_SMTP_APP_PASSWORD or "").strip()
    if not usuario or not clave:
        print("\nABORTA: GMAIL_SMTP_USER / GMAIL_SMTP_APP_PASSWORD vacíos.")
        return 2
    print(f"\nSMTP: probando login como {usuario} ...")
    ok_smtp, detalle = _probar_smtp(usuario, clave)
    print("SMTP:", detalle)
    if not ok_smtp:
        print("ABORTA: sin login SMTP no se manda nada (y un intento fallido "
              "consumiría el día: ver docstring).")
        return 3


    # ── Padrón (sólo lectura) ───────────────────────────────────────────────
    from app.db.database import SessionLocal
    from app.utils.santiago import hoy_santiago

    db = SessionLocal()
    try:
        candidatos, ya, total_alumnos = _candidatos(db, args.tenant, args.umbral)
        dominios = Counter((r.correo or "?").split("@")[-1].lower() for r in candidatos)
        print("\n" + "-" * 78)
        print(f"alumnos activos del tenant {args.tenant}: {total_alumnos}")
        print(f"candidatos ({args.umbral}+ días sin asistencia): {len(candidatos)}")
        print(f"de esos, ya contactados en los últimos {args.umbral} días: {len(ya)}")
        print(f"a enviar en esta corrida: {len(candidatos) - len(ya)}")
        print("dominios de los destinatarios:")
        for dom, n in dominios.most_common():
            print(f"   {dom:<32} {n}")
        print("-" * 78)
    finally:
        db.close()

    if args.dry_run or not args.si:
        print("\n[sin envío] pasá --si para disparar la campaña de verdad.")
        return 0

    # ── Corrida real ────────────────────────────────────────────────────────
    from app.services.alertas_email_service import enviar_alertas_inactividad

    print(f"\nENVIANDO campaña... ({time.strftime('%H:%M:%S')})", flush=True)
    inicio = time.time()
    db = SessionLocal()
    try:
        resultado = enviar_alertas_inactividad(db, tenant_id=args.tenant,
                                              umbral_dias=args.umbral)
    finally:
        db.close()
    segundos = time.time() - inicio

    db = SessionLocal()
    try:
        evidencia = _reporte_bd(db, hoy_santiago())
    finally:
        db.close()

    print("\n" + "=" * 78)
    print("RESULTADO DE LA CAMPAÑA")
    print("=" * 78)
    print(f"  candidatos            : {resultado['candidatos']}")
    print(f"  deduplicados          : {resultado['deduplicados']}")
    print(f"  ENVIADOS              : {resultado['enviados']}")
    print(f"  fallidos              : {resultado['fallidos']}")
    print(f"  duración              : {segundos:.1f}s")
    print(f"  notificaciones_enviadas (hoy, tipo=inactividad): {evidencia['por_estado']}")
    if evidencia["motivos_fallo"]:
        print("  motivos de fallo (top):")
        for motivo, n in evidencia["motivos_fallo"]:
            print(f"     {n:>4}  {motivo}")
    if resultado["detalle_fallidos"]:
        print(f"  primeros 10 fallidos  : {resultado['detalle_fallidos'][:10]}")
    if ULTIMO_ERROR_SMTP:
        print("  último error SMTP     :", ULTIMO_ERROR_SMTP)
    return 0 if not resultado["fallidos"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
