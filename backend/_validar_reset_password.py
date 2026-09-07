"""Harness dirigido — flujo de restablecimiento de contraseña (TEST, polished-term).

Cubre:
- Solicitud con email existente vs inexistente → respuesta genérica IDÉNTICA.
- Token válido dentro de 1h → confirma y actualiza la contraseña.
- Token expirado → rechazado (400).
- Token ya usado → rechazado (400).
- Token inválido/inventado → rechazado (400).
- Nuevo token invalida el anterior (un solo token activo por usuario).

Seed aislado con prefijo test-reset-pw-* y cleanup exhaustivo al final.
El envío de email se mockea (spy) para capturar el token sin enviar correo.
"""
import os
import sys
import random
import uuid
import hashlib
import asyncio
from datetime import datetime, timezone, timedelta

os.environ["ENVIRONMENT"] = "test"
sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings  # noqa: E402

if "polished-term" not in settings.DATABASE_URL:
    raise SystemExit("ABORT: no es TEST")

# ── Spy sobre send_reset_password (captura el link/token, no envía correo) ──
import app.api.v1.auth as auth_mod  # noqa: E402

_capturados = []


def _spy_send(nombre, correo, link):
    _capturados.append(link)
    return True


auth_mod.send_reset_password = _spy_send

from sqlalchemy import text  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db.database import engine  # noqa: E402
from app.core.security import verify_password, get_password_hash  # noqa: E402

BASE = random.randint(8_000_000, 8_999_000)
TENANT = BASE
UID = BASE + 1
SUBDOMAIN = f"test-reset-pw-{BASE}"
CORREO = f"test_reset_{BASE}@test.com"
PWD_VIEJA = "ClaveVieja123"
PWD_NUEVA = "ClaveNueva456"

RESULTADOS = []


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def check(nombre, cond, detalle=""):
    RESULTADOS.append((nombre, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {nombre}" + (f" | {detalle}" if detalle else ""))


def cleanup():
    """Borra por marcadores del harness (idempotente, doble pasada)."""
    ids = f"({TENANT})"
    pasos = [
        f"DELETE FROM password_reset_tokens WHERE usuario_id IN "
        f"(SELECT id FROM usuarios WHERE tenant_id IN {ids} OR correo LIKE 'test_reset_%')",
        f"DELETE FROM usuarios WHERE tenant_id IN {ids} OR correo LIKE 'test_reset_%'",
        f"DELETE FROM tenants WHERE id IN {ids} OR subdomain LIKE 'test-reset-pw-%'",
    ]
    for _ in range(2):
        for sql in pasos:
            try:
                with engine.begin() as conn:
                    conn.execute(text(sql))
            except Exception as e:  # noqa: BLE001
                print("   [cleanup] aviso:", str(e)[:80])


def extraer_token(link):
    return link.split("?token=")[-1]


def seed():
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO tenants (id, nombre, subdomain, public_id, activo, created_at) "
            "VALUES (:id, :nom, :sub, :pid, TRUE, :ca)"),
            {"id": TENANT, "nom": "TEST Reset PW", "sub": SUBDOMAIN,
             "pid": str(uuid.uuid4()), "ca": fmt(now)})
        conn.execute(text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, :ph, 'alumno', TRUE, 'activo')"),
            {"id": UID, "tid": TENANT, "rut": f"TRP{UID}-K", "nom": "Usuario Reset",
             "mail": CORREO, "ph": get_password_hash(PWD_VIEJA)})
async def run():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        # 1) Solicitud con email existente → 200 genérico + token creado (spy)
        _capturados.clear()
        r1 = await c.post("/api/v1/auth/reset-password-request", json={"correo": CORREO})
        check("request email EXISTENTE → 200", r1.status_code == 200, f"status={r1.status_code}")
        cuerpo1 = r1.json()
        check("mensaje genérico anti-enumeración", str(cuerpo1.get("mensaje", "")).startswith("Si el correo existe"), str(cuerpo1))
        check("se generó 1 link (spy)", len(_capturados) == 1, f"links={len(_capturados)}")
        token_valido = extraer_token(_capturados[0]) if _capturados else ""

        # 2) Solicitud con email INEXISTENTE → misma respuesta genérica, sin token
        _capturados.clear()
        r2 = await c.post("/api/v1/auth/reset-password-request", json={"correo": "no_existe@test.com"})
        check("request email INEXISTENTE → 200", r2.status_code == 200, f"status={r2.status_code}")
        check("respuesta IDÉNTICA (anti user-enumeration)", r2.json() == cuerpo1, str(r2.json()))
        check("no genera link para email inexistente", len(_capturados) == 0, f"links={len(_capturados)}")

        # 3) Confirm con token válido → 200 y contraseña actualizada
        r3 = await c.post("/api/v1/auth/reset-password-confirm",
                          json={"token": token_valido, "nueva_password": PWD_NUEVA})
        check("confirm token VÁLIDO → 200", r3.status_code == 200, f"status={r3.status_code}")
        with engine.connect() as conn:
            ph = conn.execute(text("SELECT password_hash FROM usuarios WHERE id=:id"), {"id": UID}).scalar()
        check("contraseña nueva funciona", bool(ph) and verify_password(PWD_NUEVA, ph))
        check("contraseña vieja ya no sirve", not verify_password(PWD_VIEJA, ph))

        # 4) Reuso del token (ya usado) → 400
        r4 = await c.post("/api/v1/auth/reset-password-confirm",
                          json={"token": token_valido, "nueva_password": "OtraClave789"})
        check("token YA USADO rechazado → 400", r4.status_code == 400, f"status={r4.status_code}")

        # 5) Token inválido/inventado → 400
        r5 = await c.post("/api/v1/auth/reset-password-confirm",
                          json={"token": "inventado-token-xyz", "nueva_password": "OtraClave789"})
        check("token INVÁLIDO rechazado → 400", r5.status_code == 400, f"status={r5.status_code}")

        # 6) Nuevo token invalida el anterior
        _capturados.clear()
        await c.post("/api/v1/auth/reset-password-request", json={"correo": CORREO})
        token_a = extraer_token(_capturados[0]) if _capturados else ""
        _capturados.clear()
        await c.post("/api/v1/auth/reset-password-request", json={"correo": CORREO})
        token_b = extraer_token(_capturados[0]) if _capturados else ""
        r6a = await c.post("/api/v1/auth/reset-password-confirm",
                           json={"token": token_a, "nueva_password": "OtraClave789"})
        check("token A invalidado por nuevo request → 400", r6a.status_code == 400, f"status={r6a.status_code}")
        r6b = await c.post("/api/v1/auth/reset-password-confirm",
                           json={"token": token_b, "nueva_password": "OtraClave789"})
        check("token B (el más reciente) funciona → 200", r6b.status_code == 200, f"status={r6b.status_code}")

        # 7) Token expirado → 400 (insert directo con expires_at en el pasado)
        tok_exp = "token-expirado-test"
        now = datetime.now(timezone.utc)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO password_reset_tokens (usuario_id, token_hash, expires_at, created_at) "
                "VALUES (:uid, :th, :exp, :ca)"),
                {"uid": UID, "th": hashlib.sha256(tok_exp.encode()).hexdigest(),
                 "exp": now - timedelta(hours=2), "ca": fmt(now)})
        r7 = await c.post("/api/v1/auth/reset-password-confirm",
                          json={"token": tok_exp, "nueva_password": "OtraClave789"})
        check("token EXPIRADO rechazado → 400", r7.status_code == 400, f"status={r7.status_code}")

    print("=" * 72)
    aprobados = sum(1 for _, cond in RESULTADOS if cond)
    print(f"RESULTADO: {aprobados}/{len(RESULTADOS)} checks aprobados")
    print("=" * 72)
    return 0 if aprobados == len(RESULTADOS) else 1
def main():
    cleanup()
    rc = 1
    try:
        seed()
        rc = asyncio.run(run())
    except Exception as e:  # noqa: BLE001
        print("ERROR durante la ejecución:", str(e)[:500])
    finally:
        cleanup()
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
