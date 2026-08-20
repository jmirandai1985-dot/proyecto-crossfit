"""Validación FIX 2: enviar_email_solicitud_admin filtra por tenant.

Crea 2 tenants de prueba (marcados fix2-cierre-*) con un admin cada uno,
monkeypatchea email_service._enviar para capturar el destinatario, y verifica
que al registrar un alumno del tenant A el correo va al admin de A (no al de B).
Sin SMTP real. Cleanup al final.
"""
import random
import sys
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from app.db.database import engine
from app.services import email_service

BASE = random.randint(800_000, 899_999)
TENANT_A = BASE
TENANT_B = BASE + 1
UID_ADMIN_A = BASE + 10
UID_ADMIN_B = BASE + 11
CORREO_A = f"fix2_admin_a_{BASE}@test.com"
CORREO_B = f"fix2_admin_b_{BASE}@test.com"
SUB_A = f"fix2-cierre-{BASE}"
SUB_B = f"fix2-cierre-{BASE}b"


def main():
    now = datetime.now(timezone.utc)
    ca = now.strftime("%Y-%m-%d %H:%M:%S.%f")
    # seed 2 tenants + 2 admins
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:a, 'FIX2 A', :sa, TRUE, :ca), (:b, 'FIX2 B', :sb, TRUE, :ca)"),
            {"a": TENANT_A, "b": TENANT_B, "sa": SUB_A, "sb": SUB_B, "ca": ca})
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:a, :ta, 'F2A-1', 'FIX2 Admin A', :ca_mail, 'x', 'administrador', TRUE, 'activo'), "
            "(:b, :tb, 'F2B-1', 'FIX2 Admin B', :cb_mail, 'x', 'administrador', TRUE, 'activo')"),
            {"a": UID_ADMIN_A, "b": UID_ADMIN_B, "ta": TENANT_A, "tb": TENANT_B,
             "ca_mail": CORREO_A, "cb_mail": CORREO_B})

    captured = {}
    orig = email_service._enviar

    def fake_enviar(destinatario, asunto, html, alumno_id=None, tipo=""):
        captured["destinatario"] = destinatario
        return True

    try:
        email_service._enviar = fake_enviar
        # alumno del tenant A → debe ir al admin A
        email_service.enviar_email_solicitud_admin(
            {"nombre": "FIX2 Alumno A", "correo": f"fix2_alumno_a_{BASE}@test.com", "id": 1},
            tenant_id=TENANT_A)
        ok_a = captured.get("destinatario") == CORREO_A
        print(f"tenant A -> destinatario: {captured.get('destinatario')} (esperado {CORREO_A}): "
              f"{'PASS' if ok_a else 'FAIL'}")
        # alumno del tenant B → debe ir al admin B
        email_service.enviar_email_solicitud_admin(
            {"nombre": "FIX2 Alumno B", "correo": f"fix2_alumno_b_{BASE}@test.com", "id": 2},
            tenant_id=TENANT_B)
        ok_b = captured.get("destinatario") == CORREO_B
        print(f"tenant B -> destinatario: {captured.get('destinatario')} (esperado {CORREO_B}): "
              f"{'PASS' if ok_b else 'FAIL'}")
    finally:
        email_service._enviar = orig
        # cleanup de los 2 tenants
        with engine.begin() as conn:
            conn.execute(sa_text(
                "DELETE FROM usuarios WHERE tenant_id IN (:a,:b)"),
                {"a": TENANT_A, "b": TENANT_B})
            conn.execute(sa_text(
                "DELETE FROM tenants WHERE id IN (:a,:b)"),
                {"a": TENANT_A, "b": TENANT_B})
        print("[cleanup] tenants fix2 eliminados")

    ok = ok_a and ok_b
    print(f"RESULTADO: {'PASS - email scoped por tenant' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
