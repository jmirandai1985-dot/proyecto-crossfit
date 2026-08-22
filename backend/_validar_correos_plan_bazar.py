"""
Harness FASE 1 — Correos: aprobación de plan (primera vez / renovación) + bazar.

Parte 1: checks unitarios de copy (monkeypatch de _enviar → NO envía).
Parte 2: integración HTTP (aprobación real y pedido real; envía a @test.com,
mismo patrón que los E2E previos del proyecto). Verifica notificaciones_enviadas.
"""
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from sqlalchemy import text

from app.core.config import settings
from app.core.security import get_password_hash, create_access_token
from app.db.database import SessionLocal
from app.models.plan import Plan
from app.models.producto import Producto
from app.models.suscripcion import Suscripcion
from app.models.tenant import Tenant
from app.models.usuario import Usuario, RolUsuario

BASE = "http://localhost:8000"
if "small-butterfly" not in settings.DATABASE_URL:
    print("ABORT: la BD no es small-butterfly")
    raise SystemExit(1)

resultados = []


def check(nombre, ok, esperado, real):
    resultados.append(ok)
    print(f"[{'✅' if ok else '❌'}] {nombre}  → esperado={esperado} | real={real}")


# ── Parte 1: copy unitario (sin enviar) ──────────────────────────────────────
import app.services.email_service as es
captured = {}


def fake_enviar(dest, asunto, html, alumno_id=None, tipo="", mes_referencia=None):
    captured.update(dest=dest, asunto=asunto, html=html, tipo=tipo)
    return True


es._enviar = fake_enviar

es.send_confirmacion_plan("Test Demo", "a@test.cl", "Plan Alpha 8",
                          8, "31 de julio de 2026", "http://app")
h = captured["html"].lower()
check("confirmacion_plan: tipo correcto", captured["tipo"] == "confirmacion_plan",
      "confirmacion_plan", captured["tipo"])
check("confirmacion_plan: NO dice 'renovado'", "renovado" not in h, "no", "renovado")
check("confirmacion_plan: NO dice 'extendida'", "extendida" not in h, "no", "extendida")
check("confirmacion_plan: dice 'tu plan ya está ACTIVO'", "tu plan ya está activo" in h,
      "si", "presente" if "tu plan ya está activo" in h else "ausente")
check("confirmacion_plan: incluye plan y clases", "plan alpha 8" in h and "8 clases al mes" in h,
      "si", "ok" if ("plan alpha 8" in h and "8 clases al mes" in h) else "no")

es.send_confirmacion_renovacion_plan("Test Demo", "a@test.cl", "Plan Alpha 8",
                                     8, "31 de julio de 2026", "http://app")
h2 = captured["html"].lower()
check("confirmacion_renovacion: sigue funcionando (dice 'renovado')",
      captured["tipo"] == "confirmacion_renovacion" and "renovado" in h2,
      "si", captured["tipo"])

es.send_confirmacion_pedido("Test Demo", "a@test.cl", "Cuerda Battle Rope", 2, 30000, "http://app")
h3 = captured["html"]
check("confirmacion_pedido: tipo correcto", captured["tipo"] == "confirmacion_pedido",
      "confirmacion_pedido", captured["tipo"])
check("confirmacion_pedido: producto", "Cuerda Battle Rope" in h3, "si",
      "presente" if "Cuerda Battle Rope" in h3 else "ausente")
check("confirmacion_pedido: cantidad y total",
      "Cantidad:</strong> 2" in h3 and "30,000" in h3, "si",
      "ok" if ("Cantidad:</strong> 2" in h3 and "30,000" in h3) else "no")

# ── Parte 2: integración HTTP ─────────────────────────────────────────────────
db = SessionLocal()
tenant_id = None
ids = {}
try:
    t = Tenant(nombre="TEST CORREOS PLAN/BAZAR",
               subdomain=f"sub-correos-{uuid.uuid4().hex[:6]}",
               public_id=str(uuid.uuid4()), activo=True)
    db.add(t)
    db.flush()
    tenant_id = t.id

    def nuevo(nombre, correo, clave, rol=RolUsuario.alumno, con_sub=False):
        u = Usuario(tenant_id=t.id, rut=f"12{uuid.uuid4().hex[:6]}-K", nombre=nombre,
                    correo=correo, password_hash=get_password_hash(clave), rol=rol,
                    activo=True, estado="activo")
        db.add(u)
        db.flush()
        return u

    admin = nuevo("Admin Test", f"admin{uuid.uuid4().hex[:4]}@test.cl", "AdminDemo123!",
                  rol=RolUsuario.administrador)
    alumnoA = nuevo("Alumno Correo A", f"alumnoa{uuid.uuid4().hex[:4]}@test.cl", "Demo123456!")
    alumnoB = nuevo("Alumno Correo B", f"alumnob{uuid.uuid4().hex[:4]}@test.cl", "Demo123456!")
    ids["admin"] = admin.id
    ids["A"] = alumnoA.id
    ids["B"] = alumnoB.id

    plan = Plan(tenant_id=t.id, nombre="Plan Pago 8", creditos=8, es_ilimitado=False,
                es_estudiante=False, precio_clp=30000, duracion_dias=30, activo=True)
    db.add(plan)
    db.flush()
    ids["plan"] = plan.id

    # Alumno B ya tiene una suscripción activa previa → su aprobación será "renovación".
    ahora = datetime.now(timezone.utc)
    db.add(Suscripcion(tenant_id=t.id, usuario_id=alumnoB.id, plan_id=plan.id,
                       estado="activo", creditos_totales=8, creditos_disponibles=8,
                       fecha_inicio=ahora,
                       fecha_expiracion=datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)))
    db.commit()

    prod = Producto(tenant_id=t.id, nombre="Cuerda Battle Rope", precio=15000, stock=50)
    db.add(prod)
    db.commit()
    ids["producto"] = prod.id

    def mint(user_id, rol):
        return create_access_token(
            {"usuario_id": user_id, "tenant_id": tenant_id, "rol": rol})

    tok_admin = mint(admin.id, "administrador")
    tok_a = mint(alumnoA.id, "alumno")
    tok_b = mint(alumnoB.id, "alumno")
    check("tokens mintados (admin/A/B)", all([tok_admin, tok_a, tok_b]), "si",
          "ok" if all([tok_admin, tok_a, tok_b]) else "no")

    def crear_solicitud(tok, alumno_id):
        return requests.post(f"{BASE}/api/v1/solicitudes/solicitar",
                             headers={"Authorization": f"Bearer {tok}"},
                             json={"tenant_id": tenant_id, "alumno_id": alumno_id,
                                   "plan_id": plan.id, "voucher_url": "/static/uploads/fake.png"},
                             timeout=10)

    def aprobar(tok, sol_id):
        return requests.put(f"{BASE}/api/v1/solicitudes/{sol_id}/aprobar",
                            headers={"Authorization": f"Bearer {tok}"}, timeout=10)

    def notif_por_tipo(alumno_id, tipo):
        n = db.execute(text(
            "SELECT count(*) FROM notificaciones_enviadas "
            "WHERE alumno_id = :a AND tipo = :t"), {"a": alumno_id, "t": tipo}).scalar()
        return n

    # A (primera vez): crear solicitud + aprobar
    r_sol_a = crear_solicitud(tok_a, alumnoA.id)
    check("solicitud A creada (201)", r_sol_a.status_code == 201, 201, r_sol_a.status_code)
    sol_a = r_sol_a.json().get("id") if r_sol_a.status_code == 201 else None
    if sol_a:
        r_ap_a = aprobar(tok_admin, sol_a)
        check("aprobar solicitud A (200)", r_ap_a.status_code == 200, 200, r_ap_a.status_code)
    db.expire_all()
    check("A → notificación 'confirmacion_plan' (primera vez)",
          notif_por_tipo(alumnoA.id, "confirmacion_plan") >= 1,
          ">=1", notif_por_tipo(alumnoA.id, "confirmacion_plan"))
    check("A → NO 'confirmacion_renovacion'",
          notif_por_tipo(alumnoA.id, "confirmacion_renovacion") == 0,
          0, notif_por_tipo(alumnoA.id, "confirmacion_renovacion"))

    # B (renovación): ya tiene suscripción previa
    r_sol_b = crear_solicitud(tok_b, alumnoB.id)
    check("solicitud B creada (201)", r_sol_b.status_code == 201, 201, r_sol_b.status_code)
    sol_b = r_sol_b.json().get("id") if r_sol_b.status_code == 201 else None
    if sol_b:
        r_ap_b = aprobar(tok_admin, sol_b)
        check("aprobar solicitud B (200)", r_ap_b.status_code == 200, 200, r_ap_b.status_code)
    db.expire_all()
    check("B → notificación 'confirmacion_renovacion'",
          notif_por_tipo(alumnoB.id, "confirmacion_renovacion") >= 1,
          ">=1", notif_por_tipo(alumnoB.id, "confirmacion_renovacion"))

    # Bazar: alumno A (ya con plan activo → full access) compra un producto
    r_ped = requests.post(f"{BASE}/api/v1/pedidos",
                          headers={"Authorization": f"Bearer {tok_a}"},
                          json={"producto_id": prod.id, "cantidad": 2,
                                "tenant_id": tenant_id, "alumno_id": alumnoA.id}, timeout=10)
    check("pedido A creado (201)", r_ped.status_code == 201, 201, r_ped.status_code)
    db.expire_all()
    check("A → notificación 'confirmacion_pedido' (bazar)",
          notif_por_tipo(alumnoA.id, "confirmacion_pedido") >= 1,
          ">=1", notif_por_tipo(alumnoA.id, "confirmacion_pedido"))
finally:
    if tenant_id is not None:
        try:
            for tabla in ("solicitudes_planes", "pedidos", "transacciones_financieras",
                          "suscripciones", "notificaciones_enviadas",
                          "usuarios", "planes", "productos"):
                try:
                    db.rollback()
                    db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"), {"t": tenant_id})
                    db.commit()
                except Exception:
                    db.rollback()
            db.rollback()
            db.execute(text(
                "DELETE FROM notificaciones WHERE alumno_id IN "
                "(SELECT id FROM usuarios WHERE tenant_id = :t)"), {"t": tenant_id})
            db.commit()
            db.rollback()
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
            db.commit()
            print(f"  [cleanup] OK — tenant {tenant_id} eliminado")
        except Exception as e:
            db.rollback()
            print(f"  [cleanup] FALLO: {e}")
    db.close()

total = len(resultados)
aprobados = sum(resultados)
print("=" * 60)
print(f"RESULTADO: {aprobados}/{total} checks aprobados "
      f"({'✅ OK' if aprobados == total else '❌ revisar'})")
print("=" * 60)
raise SystemExit(0 if aprobados == total else 2)

