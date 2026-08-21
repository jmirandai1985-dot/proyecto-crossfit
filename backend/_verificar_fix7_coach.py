"""Verificación FIX 7 coach_disciplinas: validar coach/disciplina del tenant.

Datos TEST_VALIDACION_FIXCD + cleanup. Casos:
  - POST asignación con coach_id inexistente -> 404, sin fila creada.
  - POST asignación con coach de OTRO tenant -> 404.
  - POST asignación con disciplina inexistente -> 404.
  - POST asignación válida -> 201.
  - PUT /reemplazar con coach inexistente -> 404.
"""
import os
import sys
import random
from datetime import datetime, timezone

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["SENTRY_DSN"] = ""

from sqlalchemy import text as sa_text  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.database import engine  # noqa: E402

BASE = random.randint(8_000_000, 8_999_000)
TENANT_A = BASE
TENANT_B = BASE + 1
UID_COACH_A = BASE + 100
UID_ADMIN_A = BASE + 101
UID_COACH_B = BASE + 102   # pertenece a TENANT_B
DISC_A = BASE + 200

SUB_A = f"test-validacion-fixcd-{BASE}"
SUB_B = f"test-validacion-fixcd-{BASE}b"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def token(uid, rol, tid):
    return create_access_token({
        "usuario_id": uid, "tenant_id": tid, "rol": rol,
        "correo": f"u{uid}@fix.cl", "nombre": f"u{uid}",
    })


def seed():
    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            [{"id": TENANT_A, "nom": "FIXCD Tenant A", "sub": SUB_A, "ca": now()},
             {"id": TENANT_B, "nom": "FIXCD Tenant B", "sub": SUB_B, "ca": now()}])
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [
                {"id": UID_COACH_A, "tid": TENANT_A, "rut": "TV000301", "nom": "FIXCD CoachA",
                 "mail": f"test_validacion_fixcd_coacha_{BASE}@test.com", "rol": "coach"},
                {"id": UID_ADMIN_A, "tid": TENANT_A, "rut": "TV000302", "nom": "FIXCD AdminA",
                 "mail": f"test_validacion_fixcd_admina_{BASE}@test.com", "rol": "administrador"},
                {"id": UID_COACH_B, "tid": TENANT_B, "rut": "TV000303", "nom": "FIXCD CoachB",
                 "mail": f"test_validacion_fixcd_coachb_{BASE}@test.com", "rol": "coach"},
            ])
        conn.execute(sa_text(
            "INSERT INTO disciplinas (id, tenant_id, nombre, activo, requiere_coach) "
            "VALUES (:id, :tid, :nom, TRUE, TRUE)"),
            {"id": DISC_A, "tid": TENANT_A, "nom": "FIXCD Disc A"})


def cleanup():
    for tid in (TENANT_A, TENANT_B):
        tl = str(tid)
        sub = ("(SELECT id FROM usuarios WHERE correo LIKE 'test_validacion_fixcd_%' "
               f"OR rut LIKE 'TV%' OR tenant_id IN ({tl}))")
        pasos = [
            ("coach_disciplinas", f"DELETE FROM coach_disciplinas WHERE tenant_id IN ({tl})"),
            ("disciplinas", f"DELETE FROM disciplinas WHERE tenant_id IN ({tl})"),
            ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tl}) OR correo LIKE 'test_validacion_fixcd_%'"),
            ("tenants", f"DELETE FROM tenants WHERE id IN ({tl}) OR subdomain LIKE 'test-validacion-fixcd-%'"),
        ]
        for tabla, sql in pasos:
            try:
                with engine.begin() as c:
                    c.execute(sa_text(sql))
            except Exception as e:
                print(f"  cleanup {tabla}: {type(e).__name__}: {str(e)[:120]}")


def check(nombre, ok, detalle=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {nombre}  {detalle}")
    return ok


def main():
    from httpx import ASGITransport, AsyncClient
    import asyncio

    async def run():
        results = []
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            hA = {"Authorization": f"Bearer {token(UID_ADMIN_A, 'administrador', TENANT_A)}"}

            # FIX 7: coach inexistente
            r = await c.post("/api/v1/coach-disciplinas", json={
                "tenant_id": TENANT_A, "coach_id": 99999999, "disciplina_id": DISC_A}, headers=hA)
            results.append(check("FIX7: POST asignación con coach inexistente -> 404",
                                 r.status_code == 404, f"got {r.status_code} {r.text[:80]}"))

            # FIX 7: coach de OTRO tenant
            r = await c.post("/api/v1/coach-disciplinas", json={
                "tenant_id": TENANT_A, "coach_id": UID_COACH_B, "disciplina_id": DISC_A}, headers=hA)
            results.append(check("FIX7: POST asignación con coach de otro tenant -> 404",
                                 r.status_code == 404, f"got {r.status_code} {r.text[:80]}"))

            # FIX 7: disciplina inexistente
            r = await c.post("/api/v1/coach-disciplinas", json={
                "tenant_id": TENANT_A, "coach_id": UID_COACH_A, "disciplina_id": 99999999}, headers=hA)
            results.append(check("FIX7: POST asignación con disciplina inexistente -> 404",
                                 r.status_code == 404, f"got {r.status_code} {r.text[:80]}"))

            # FIX 7: caso válido
            r = await c.post("/api/v1/coach-disciplinas", json={
                "tenant_id": TENANT_A, "coach_id": UID_COACH_A, "disciplina_id": DISC_A}, headers=hA)
            results.append(check("FIX7: POST asignación válida -> 201",
                                 r.status_code == 201, f"got {r.status_code}"))

            # FIX 7: reemplazar con coach inexistente
            r = await c.put("/api/v1/coach-disciplinas/reemplazar", json={
                "tenant_id": TENANT_A, "coach_id": 99999999, "disciplina_ids": [DISC_A]}, headers=hA)
            results.append(check("FIX7: PUT /reemplazar con coach inexistente -> 404",
                                 r.status_code == 404, f"got {r.status_code} {r.text[:80]}"))

        # DB: no deben existir filas con coach_id inválido
        with engine.connect() as conn:
            n = conn.execute(sa_text(
                "SELECT COUNT(*) FROM coach_disciplinas "
                "WHERE coach_id=99999999 OR (tenant_id=:t AND coach_id NOT IN "
                "(SELECT id FROM usuarios WHERE tenant_id=:t))"),
                {"t": TENANT_A}).scalar()
            results.append(check("FIX7: sin filas inválidas en coach_disciplinas",
                                 n == 0, f"filas invalidas={n}"))

        return results

    results = asyncio.run(run())
    passed = sum(1 for r in results if r)
    print(f"\nRESULTADO FIX 7: {passed}/{len(results)} PASS")
    return passed == len(results)


if __name__ == "__main__":
    seed()
    try:
        ok = main()
    finally:
        print("[cleanup] ...")
        cleanup()
    sys.exit(0 if ok else 1)
