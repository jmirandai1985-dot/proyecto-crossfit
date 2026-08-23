"""Harness E2E FASE 4 — Alerta de stock bajo con ENVÍO REAL a jmirandai1985@gmail.com.

Requisitos:
- BD TEST (small-butterfly) vía ENVIRONMENT=test.
- SMTP real configurado en .env.test (urban.training.box.2026@gmail.com).

Flujo:
1) Usar un tenant de prueba aislado (creado y limpiado por el harness) con un
   admin ACTIVO cuyo correo = jmirandai1985@gmail.com (destino del correo real).
2) Producto con stock_minimo=5.
3) Compra 1: stock 6 -> 4 (cruza umbral) -> correo REAL + alerta_stock_enviada=True.
4) Compra 2: stock 4 -> 3 (sigue bajo umbral) -> NO duplica correo.
5) Admin repone stock a 20 (PUT) -> alerta_stock_enviada=False.
6) Compra 3: stock 20 -> 4 (cruza umbral) -> correo REAL de nuevo.
7) Limpieza total del tenant de prueba.
"""
import os
import sys
import asyncio
import random
import uuid
from datetime import datetime, timezone, timedelta

os.environ["ENVIRONMENT"] = "test"
sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings  # noqa: E402

if "small-butterfly" not in settings.DATABASE_URL:
    raise SystemExit("ABORT: no es TEST")

from sqlalchemy import text  # noqa: E402

from app.db.database import SessionLocal, engine  # noqa: E402
from app.models.pedido import Pedido  # noqa: E402
from app.models.producto import Producto  # noqa: E402
from app.models.usuario import Usuario, RolUsuario  # noqa: E402
from app.schemas.pedido import PedidoCreate  # noqa: E402
from app.schemas.producto import ProductoUpdate  # noqa: E402
from app.api.v1.pedidos import crear_pedido  # noqa: E402
from app.api.v1.productos import actualizar_producto  # noqa: E402

# ── Instrumentar SIN mockear el envío: contamos llamadas reales a
#    send_alerta_stock_bajo (que envia por SMTP real) y registramos el resultado.
import app.services.email_service as ems  # noqa: E402

_llamadas = {"alerta_stock_bajo": 0, "resultados": []}
_real_send_alerta = ems.send_alerta_stock_bajo


def _spy_alerta(*args, **kwargs):
    _llamadas["alerta_stock_bajo"] += 1
    ok = _real_send_alerta(*args, **kwargs)
    _llamadas["resultados"].append((args, ok))
    print(f"   [REAL send_alerta_stock_bajo] args={args} resultado={ok}")
    return ok


ems.send_alerta_stock_bajo = _spy_alerta

# ── Tenant de prueba aislado ──
BASE = random.randint(9_000_000, 9_999_000)
TENANT = BASE
ADMIN_ID = BASE + 1
ALUMNO_ID = BASE + 2
PLAN_ID = BASE + 3
SUB_ID = BASE + 4
SUBDOMAIN = f"test-stock-bajo-{BASE}"
DESTINO_CORREO = "jmirandai1985@gmail.com"

db = SessionLocal()
pedidos_creados = []
producto_id = None


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def cleanup():
    """Limpieza por marcadores del tenant de prueba (idempotente, doble pasada)."""
    tids = f"({TENANT})"
    pasos = [
        ("pedidos", f"DELETE FROM pedidos WHERE tenant_id IN {tids}"),
        ("productos", f"DELETE FROM productos WHERE tenant_id IN {tids}"),
        ("suscripciones", f"DELETE FROM suscripciones WHERE tenant_id IN {tids}"),
        ("planes", f"DELETE FROM planes WHERE tenant_id IN {tids}"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN {tids}"),
        ("tenants", f"DELETE FROM tenants WHERE id IN {tids}"),
    ]
    for _ in range(2):
        for tabla, sql in pasos:
            try:
                with engine.begin() as conn:
                    conn.execute(text(sql))
            except Exception as e:
                print(f"   [cleanup] {tabla}: {str(e)[:100]}")
    print("[cleanup] OK - tenant de prueba eliminado")

try:
    cleanup()  # eliminar leftovers de corridas previas

    now = datetime.now(timezone.utc)

    # ── Seed del tenant de prueba (SQL crudo, mismo patrón que _fase1_validation_pg) ──
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO tenants (id, nombre, subdomain, public_id, activo, created_at) "
            "VALUES (:id, :nom, :sub, :pid, TRUE, :ca)"),
            {"id": TENANT, "nom": "TEST Stock Bajo E2E", "sub": SUBDOMAIN,
             "pid": str(uuid.uuid4()), "ca": fmt(now)})
        conn.execute(text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, "
            "rol, activo, estado) VALUES (:id, :tid, :rut, :nom, :correo, 'x', :rol, TRUE, 'activo')"),
            [{"id": ADMIN_ID, "tid": TENANT, "rut": f"TSB{ADMIN_ID}-K",
              "nom": "Admin Stock Bajo", "correo": DESTINO_CORREO, "rol": "administrador"},
             {"id": ALUMNO_ID, "tid": TENANT, "rut": f"TSB{ALUMNO_ID}-K",
              "nom": "Alumno Stock Bajo", "correo": f"alumno_stock_bajo_{BASE}@test.cl", "rol": "alumno"}])
        conn.execute(text(
            "INSERT INTO planes (id, tenant_id, nombre, creditos, es_ilimitado, "
            "precio_clp, duracion_dias, activo) VALUES (:id, :tid, 'Plan E2E Stock', 8, FALSE, 30000, 30, TRUE)"),
            {"id": PLAN_ID, "tid": TENANT})
        conn.execute(text(
            "INSERT INTO suscripciones (id, tenant_id, usuario_id, plan_id, estado, "
            "creditos_totales, creditos_disponibles, fecha_inicio, fecha_expiracion, "
            "puede_comprar_emergencia) VALUES (:id, :tid, :uid, :pid, 'activo', 8, 8, :fi, :fe, TRUE)"),
            {"id": SUB_ID, "tid": TENANT, "uid": ALUMNO_ID, "pid": PLAN_ID,
             "fi": fmt(now), "fe": fmt(now + timedelta(days=30))})

    print(f"Tenant de prueba creado: id={TENANT} subdomain={SUBDOMAIN}")
    print(f"Admin destinatario real: {DESTINO_CORREO}")

    admin = db.query(Usuario).get(ADMIN_ID)
    alumno = db.query(Usuario).get(ALUMNO_ID)
    current_user = {"tenant_id": TENANT, "usuario_id": ADMIN_ID,
                    "rol": "administrador", "nombre": admin.nombre,
                    "correo": admin.correo}

    # ── 1) Producto con stock_minimo=5, stock inicial 6 ──
    producto = Producto(tenant_id=TENANT, nombre="Proteina E2E Stock Bajo",
                        descripcion="harness fase 4", precio=15000.0,
                        stock=6, stock_minimo=5, activo=True)
    db.add(producto)
    db.commit()
    db.refresh(producto)
    producto_id = producto.id
    print(f"\n1) Producto creado: stock=6 stock_minimo=5 flag={producto.alerta_stock_enviada}")

    # ── 2) Compra 1: cantidad 2 -> stock 4 (cruza umbral) -> correo REAL ──
    p = crear_pedido(PedidoCreate(producto_id=producto_id, cantidad=2,
                                  alumno_id=ALUMNO_ID, tenant_id=TENANT,
                                  estado="pendiente"), db, current_user)
    pedidos_creados.append(p.id)
    db.refresh(producto)
    print(f"2) Tras compra 1: stock={producto.stock} flag={producto.alerta_stock_enviada}")
    assert producto.stock == 4, f"stock esperado 4, real {producto.stock}"
    assert producto.alerta_stock_enviada is True, "flag debe quedar True tras 1er cruce"
    assert _llamadas["alerta_stock_bajo"] == 1, "debe haberse disparado 1 correo real"
    assert _llamadas["resultados"][0][1] is True, "el correo real debió enviarse OK"


    # ── 3) Compra 2: cantidad 1 -> stock 3 (sigue bajo umbral) -> NO duplica ──
    p2 = crear_pedido(PedidoCreate(producto_id=producto_id, cantidad=1,
                                   alumno_id=ALUMNO_ID, tenant_id=TENANT,
                                   estado="pendiente"), db, current_user)
    pedidos_creados.append(p2.id)
    db.refresh(producto)
    print(f"3) Tras compra 2: stock={producto.stock} flag={producto.alerta_stock_enviada}")
    assert producto.stock == 3
    assert _llamadas["alerta_stock_bajo"] == 1, "NO debe duplicarse el correo (dedupe por flag)"

    # ── 4) Admin repone: PUT stock=20 -> flag a False ──
    actualizar_producto(producto_id, ProductoUpdate(stock=20), None, db, current_user)
    db.refresh(producto)
    print(f"4) Tras reponer stock=20: flag={producto.alerta_stock_enviada}")
    assert producto.stock == 20
    assert producto.alerta_stock_enviada is False, "flag debe resetearse al reponer por encima del umbral"

    # ── 5) Compra 3: cantidad 16 -> stock 4 (cruza umbral) -> correo REAL de nuevo ──
    p3 = crear_pedido(PedidoCreate(producto_id=producto_id, cantidad=16,
                                   alumno_id=ALUMNO_ID, tenant_id=TENANT,
                                   estado="pendiente"), db, current_user)
    pedidos_creados.append(p3.id)
    db.refresh(producto)
    print(f"5) Tras compra 3: stock={producto.stock} flag={producto.alerta_stock_enviada}")
    assert producto.stock == 4
    assert producto.alerta_stock_enviada is True
    assert _llamadas["alerta_stock_bajo"] == 2, "debe dispararse el 2º correo real tras el reset"
    assert _llamadas["resultados"][1][1] is True, "el 2º correo real debió enviarse OK"

    print("\n" + "=" * 72)
    print("RESULTADO: OK - Fase 4 E2E con envío REAL validado")
    print(f"  Correos reales enviados a {DESTINO_CORREO}: {_llamadas['alerta_stock_bajo']} (1º y 3º compra)")
    print("  Dedupe sin duplicados: OK | Reset por reposición: OK | Re-disparo: OK")
    print("=" * 72)
    sys.exit(0)
finally:
    # ── Limpieza ──
    try:
        cleanup()
    except Exception as e:
        print("Limpieza con avisos:", e)
    db.close()

