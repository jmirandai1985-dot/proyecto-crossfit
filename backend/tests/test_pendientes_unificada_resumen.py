"""`GET /admin/pendientes/resumen`: los números de las cuatro pestañas y del menú.

Por qué existe (Tanda 4): la pantalla unificada `/admin/pendientes` muestra CUATRO
colas (solicitudes de plan, pedidos del Bazar, registros de alumnos y premios de
referidos) y sus badges —igual que el menú lateral, la campana y el Dashboard— salen
de este único endpoint. Si un contador no filtrara por tenant, o contara filas YA
resueltas, el badge diría 3 y la lista mostraría 2: el admin dejaría de confiar en
el número.

Este test llama a la FUNCIÓN del endpoint con una sesión real (sin HTTP, así corre
sin uvicorn) y comprueba, en un box TEMPORAL que se borra al final:

  A. El contrato exacto: 4 enteros + `total` = suma, con una fila ABIERTA y una
     CERRADA de cada cola (sólo cuenta la abierta).
  B. Aislamiento: el resumen de OTRO tenant no ve nada del box (todo en 0).
  C. El estado `pendiente_activacion` se cuenta sólo para ALUMNOS (un coach
     pendiente no es "registro de alumno" en la pestaña).

Correr (aislado, sin uvicorn):
    cd backend && py -3.12 -m pytest tests/test_pendientes_unificada_resumen.py -q --noconftest
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.api.v1.admin import resumen_pendientes

PREFIJO = "pendientes-resumen-test"
TENANT_INEXISTENTE = 10 ** 9          # ningún box del seed usa este id


@pytest.fixture(scope="module")
def db():
    from app.db.database import SessionLocal
    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.close()


def _contexto(tenant_id):
    """`current_user` como lo arma `get_current_admin` (acá sólo importa el tenant)."""
    return {"usuario_id": 1, "tenant_id": tenant_id, "rol": "administrador",
            "correo": "pendientes@test.local"}


def _borrar_box(db, tenant):
    """Borra el box temporal de la hoja al tronco.

    Cada DELETE va en su propio savepoint: si una FK inesperada rechaza uno, el resto
    se limpia igual y lo que quedó se reporta como warning VISIBLE (no un residuo
    silencioso en la BD de TEST).
    """
    import warnings

    # `promociones_referidos_detectadas` NO tiene `tenant_id` (cuelga de la promoción)
    # y va AL FINAL: si la FK ya cascadeó al borrar la promoción, la subconsulta no
    # encuentra nada y el DELETE es un no-op; si la FK NO cascadea, borra por promo.
    sql_por_tabla = {
        "promociones_referidos_detectadas":
            "DELETE FROM promociones_referidos_detectadas WHERE promocion_id IN "
            "(SELECT id FROM promociones_referidos WHERE tenant_id = :t)",
    }
    tablas = ["promociones_referidos", "pedidos", "solicitudes_planes", "productos",
              "planes", "usuarios", "promociones_referidos_detectadas"]
    for _ in range(3):
        for tabla in list(tablas):
            sql = sql_por_tabla.get(
                tabla, f"DELETE FROM {tabla} WHERE tenant_id = :t")
            try:
                with db.begin_nested():
                    db.execute(text(sql), {"t": tenant})
            except Exception:
                continue
            tablas.remove(tabla)
        if not tablas:
            break
    try:
        with db.begin_nested():
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
    except Exception:
        tablas.append("tenants")
    if tablas:
        warnings.warn(f"[residuo] box {tenant} de {PREFIJO}: quedaron {tablas}",
                      stacklevel=2)
    db.commit()


def _sincronizar_secuencias(db, tablas):
    """Pone cada secuencia en MAX(id)+1 (mismo patrón que `scripts/sync_test_from_prod.py`).

    TEST se rellena con dumps de PRODUCCIÓN, que traen los `id` explícitos: la secuencia
    se queda atrás y el siguiente INSERT choca con la PK (`duplicate key ... pkey`). No es
    un problema de este test sino del box, pero un test no puede depender de que nadie haya
    corrido un sync a mitad de la corrida: se sincroniza antes de insertar.
    """
    for tabla in tablas:
        db.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {tabla}), 0) + 1, false)"))


@pytest.fixture(scope="module")
def box(db, request):
    """Box temporal con UNA fila abierta + UNA cerrada en cada una de las 4 colas."""
    from app.models.pedido import Pedido
    from app.models.plan import Plan
    from app.models.producto import Producto
    from app.models.referidos import (EstadoPromocionDetectada,
                                      PromocionReferidos,
                                      PromocionReferidosDetectada, TipoPremio)
    from app.models.solicitud_plan import SolicitudPlan
    from app.models.usuario import RolUsuario

    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alta = datetime.now(timezone.utc)
    datos = {"ids": {}}

    tenant = db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
        VALUES (:n, :s, :pub, true, :alta) RETURNING id"""),
        {"n": f"Box {PREFIJO} {sufijo}", "s": f"{PREFIJO}-{sufijo}",
         "pub": str(uuid.uuid4()), "alta": alta}).scalar()
    datos["tenant_id"] = tenant
    # Si una inserción de abajo falla, el `finally` de la fixture NO corre (nunca se
    # llegó al `yield`): el finalizer sí, así el box no queda en TEST.
    request.addfinalizer(lambda: _borrar_box(db, tenant))

    # Las secuencias pueden venir atrasadas de un dump de PROD (ver docstring del helper).
    _sincronizar_secuencias(db, ["planes", "productos", "promociones_referidos",
                                 "promociones_referidos_detectadas"])

    def usuario(nombre, rol, estado):
        # `activo` es derivado de `estado`: la CHECK `ck_usuarios_activo_estado`
        # (migración 034) exige `activo = (estado = 'activo')`, así que un alumno
        # en `pendiente_activacion` va con activo=false.
        return db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, :n, :c, 'x', :rol, :activo, :estado, :alta) RETURNING id"""),
            {"t": tenant, "r": f"{sufijo[-6:]}-{uuid.uuid4().hex[:4]}", "n": nombre,
             "c": f"{PREFIJO}.{uuid.uuid4().hex[:10]}@test.local",
             "rol": getattr(rol, "value", rol), "estado": estado,
             "activo": estado == "activo", "alta": alta}).scalar()

    # Registros: 1 alumno esperando activación (+1 activo y +1 coach pendiente que NO cuentan).
    pendiente = usuario("Alumno Pendiente TEST", RolUsuario.alumno, "pendiente_activacion")
    activo = usuario("Alumno Activo TEST", RolUsuario.alumno, "activo")
    usuario("Coach Pendiente TEST", RolUsuario.coach, "pendiente_activacion")

    plan = Plan(tenant_id=tenant, nombre=f"Plan {sufijo}", precio_clp=20000)
    producto = Producto(tenant_id=tenant, nombre=f"Producto {sufijo}", precio=5000, stock=5)
    db.add_all([plan, producto])
    db.flush()

    # Solicitudes: 1 `pending` (+1 `approved`, que ya no es trabajo del admin).
    db.add_all([
        SolicitudPlan(tenant_id=tenant, alumno_id=pendiente, plan_id=plan.id,
                      estado="pending"),
        SolicitudPlan(tenant_id=tenant, alumno_id=activo, plan_id=plan.id,
                      estado="approved"),
    ])
    # Pedidos: 1 `pendiente` (+1 `entregado`).
    db.add_all([
        Pedido(tenant_id=tenant, alumno_id=activo, producto_id=producto.id,
               cantidad=1, total=5000, estado="pendiente"),
        Pedido(tenant_id=tenant, alumno_id=activo, producto_id=producto.id,
               cantidad=1, total=5000, estado="entregado"),
    ])
    # Premios: 1 umbral por confirmar (+1 ya confirmado).
    promo = PromocionReferidos(tenant_id=tenant, nombre=f"Promo {sufijo}",
                               umbral_referidos_convertidos=3,
                               tipo_premio=TipoPremio.mes_gratis)
    db.add(promo)
    db.flush()
    for estado, alumno, periodo in (
            (EstadoPromocionDetectada.pendiente_confirmacion, activo, "2026-10"),
            (EstadoPromocionDetectada.confirmado, pendiente, "2026-09")):
        db.add(PromocionReferidosDetectada(
            promocion_id=promo.id, usuario_id=alumno, periodo_cumplido=periodo,
            nombre_promocion=promo.nombre, umbral_referidos_convertidos=3,
            tipo_premio=TipoPremio.mes_gratis, estado=estado))
    db.commit()

    datos["ids"] = {"alumno_pendiente": pendiente, "promo": promo.id}
    datos["db"] = db
    try:
        yield datos
    finally:
        db.rollback()
        _borrar_box(db, tenant)


# ── A. Contrato: 4 contadores, sólo las filas ABIERTAS ───────────────────────
def test_a_el_resumen_cuenta_solo_las_filas_abiertas_de_cada_cola(box):
    resumen = resumen_pendientes(box["db"], _contexto(box["tenant_id"]))

    assert resumen == {"solicitudes": 1, "pedidos": 1, "registros": 1,
                       "premios": 1, "total": 4}, (
        "el box tiene UNA fila abierta y UNA cerrada por cola: sólo cuenta la abierta")
    assert all(isinstance(valor, int) for valor in resumen.values()), (
        "el front pinta estos valores directo en el badge: enteros, no Decimal")


# ── B. Aislamiento entre boxes ───────────────────────────────────────────────
def test_b_otro_box_no_ve_los_pendientes_ajenos(box):
    resumen = resumen_pendientes(box["db"], _contexto(TENANT_INEXISTENTE))

    assert resumen == {"solicitudes": 0, "pedidos": 0, "registros": 0,
                       "premios": 0, "total": 0}, (
        "los cuatro COUNT filtran por el tenant del token: un box sin datos ve ceros")


# ── C. Registros = ALUMNOS, no cualquier usuario pendiente ───────────────────
def test_c_un_coach_pendiente_no_es_un_registro_de_alumno(box):
    pendientes = box["db"].execute(text(
        "SELECT count(*) FROM usuarios "
        "WHERE tenant_id = :t AND estado = 'pendiente_activacion'"),
        {"t": box["tenant_id"]}).scalar()
    assert pendientes == 2, "el fixture deja un ALUMNO y un COACH por activar"

    resumen = resumen_pendientes(box["db"], _contexto(box["tenant_id"]))
    assert resumen["registros"] == 1, (
        "la pestaña Registros es de alumnos: el coach pendiente no se cuenta")


