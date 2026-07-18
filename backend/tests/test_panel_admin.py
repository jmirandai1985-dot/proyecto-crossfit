"""
Test del Panel de Administracion — Suite de integracion.
Cubre: validacion de rol admin, flujo de aprobacion/rechazo de solicitudes,
endpoint de reportes del dashboard, y flujo de compra del bazar.

Sigue el mismo patron que test_panel_coach.py.
Usa usuario admin (id=1001) creado por run_setup_test_db.py.
"""
import pytest
import requests
from datetime import date, timedelta

from tests.conftest import BASE, ALUMNO_ID, TENANT_ID, HOY, HOY_STR

ADMIN_ID = 1001
COACH_ID = 1000


# ── Estado compartido entre tests ──
class Shared:
    solicitud_id = None
    producto_id = None


# ===================================================================
# BLOQUE 1 — VALIDACION DE ROL ADMIN (tests 1-4)
# ===================================================================

def test_a01_aprobar_solicitud_con_usuario_invalido():
    """[1] Verificar que un coach NO puede aprobar solicitudes (seguridad)."""
    r = requests.put(f"{BASE}/solicitudes/99999/aprobar",
                     params={"admin_id": COACH_ID})
    assert r.status_code == 403, \
        f"Coach no debe poder aprobar: status {r.status_code}"
    data = r.json()
    assert "administrador" in data.get("detail", "").lower(), \
        "Debe indicar que se requiere rol admin"
    print(f"  [OK] Coach rechazado (403) - Seguridad funciona")


def test_a02_crear_solicitud_para_test():
    """[2] Crear solicitud de prueba para testear aprobacion admin."""
    r_solicitud = requests.post(f"{BASE}/solicitudes/solicitar", json={
        "tenant_id": TENANT_ID,
        "alumno_id": ALUMNO_ID,
        "plan_id": 1,
        "voucher_url": None,
        "certificado_estudiante_url": None
    })
    if r_solicitud.status_code == 201:
        Shared.solicitud_id = r_solicitud.json().get("id")
    else:
        r_list = requests.get(f"{BASE}/solicitudes/pendientes",
                              params={"tenant_id": TENANT_ID})
        solicitudes = r_list.json()
        if solicitudes:
            Shared.solicitud_id = solicitudes[0]["id"]
    assert Shared.solicitud_id is not None, "Debe haber una solicitud"
    print(f"  Solicitud: id={Shared.solicitud_id}")


def test_a03_admin_puede_aprobar():
    """[3] Admin (id=1001, rol=administrador) SI puede aprobar."""
    assert Shared.solicitud_id is not None
    r = requests.put(f"{BASE}/solicitudes/{Shared.solicitud_id}/aprobar",
                     params={"admin_id": ADMIN_ID})
    assert r.status_code == 200, \
        f"Admin debe poder aprobar: {r.status_code}"
    print(f"  [OK] Admin aprobo solicitud {Shared.solicitud_id}")


def test_a04_rechazar_con_coach_devuelve_403():
    """[4] Verificar que rechazar con coach tambien da 403."""
    r = requests.put(f"{BASE}/solicitudes/1/rechazar",
                     params={"admin_id": COACH_ID, "motivo": "test"})
    assert r.status_code == 403, \
        f"Coach no debe poder rechazar: {r.status_code}"
    print(f"  [OK] Coach rechazado al rechazar (403)")


# ===================================================================
# BLOQUE 2 — REPORTES Y LISTADOS (tests 5-6)
# ===================================================================

def test_a05_reportes_dashboard():
    """[5] GET /reportes/ — Endpoint de stats del Dashboard con datos reales."""
    r = requests.get(f"{BASE}/reportes/",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    campos = ["alumnosActivos", "membresiasMensuales", "ingresoMensual",
              "asistenciaPromedio", "clasesImpartidas"]
    for campo in campos:
        assert campo in data, f"Falta campo '{campo}'"
        # Verificar que son enteros (datos reales, no strings)
        assert isinstance(data[campo], (int, float)
                          ), f"{campo} debe ser numerico"
    print(f"  [OK] Reportes dashboard: {len(campos)} campos numericos reales")


def test_a06_listar_planes():
    """[6] GET /planes — Listar planes funciona."""
    r = requests.get(f"{BASE}/planes",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert isinstance(data, list)
    print(f"  [OK] Planes listados: {len(data)} encontrados")


# ===================================================================
# BLOQUE 3 — BAZAR: FLUJO DE COMPRA CON STOCK (tests 7-9)
# ===================================================================

def test_a07_crear_producto_con_stock():
    """[7] POST /productos — Crear producto con stock inicial=5."""
    from io import BytesIO
    # Usar multipart/form-data ya que crear_producto espera Form params
    payload = {
        "nombre": "Camiseta Test",
        "precio": 15000,
        "stock": 5,
        "tenant_id": TENANT_ID,
        "activo": True
    }
    r = requests.post(f"{BASE}/productos", params=payload)
    assert r.status_code in (
        200, 201), f"Status {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert data.get("id"), "Debe devolver un id"
    Shared.producto_id = data["id"]
    assert data.get(
        "stock") == 5, f"Stock inicial debe ser 5, obtenido: {data.get('stock')}"
    print(f"  [OK] Producto creado: id={Shared.producto_id}, stock=5")


def test_a08_comprar_2_unidades_stock_baja_a_3():
    """[8] POST /pedidos — Comprar 2 unidades, verificar stock baja a 3."""
    assert Shared.producto_id is not None, "Primero debe crear producto"

    # Crear pedido de 2 unidades
    pedido = {
        "tenant_id": TENANT_ID,
        "alumno_id": ALUMNO_ID,
        "producto_id": Shared.producto_id,
        "cantidad": 2,
        "estado": "pendiente"
    }
    r = requests.post(f"{BASE}/pedidos", json=pedido)
    assert r.status_code in (
        200, 201), f"Status {r.status_code}: {r.text[:200]}"
    pedido_data = r.json()
    assert pedido_data.get("id"), "Debe devolver un id de pedido"
    assert pedido_data.get(
        "total") == 30000, f"Total debe ser 30000 (2x15000), obtenido: {pedido_data.get('total')}"
    print(
        f"  [OK] Pedido creado: id={pedido_data['id']}, total={pedido_data['total']}")

    # Verificar stock bajo a 3
    r2 = requests.get(f"{BASE}/productos/{Shared.producto_id}",
                      params={"tenant_id": TENANT_ID})
    assert r2.status_code == 200
    producto = r2.json()
    assert producto["stock"] == 3, f"Stock debe ser 3, obtenido: {producto['stock']}"
    print(f"  [OK] Stock bajo de 5 a 3 correctamente")


def test_a09_compra_excede_stock_rechazada():
    """[9] Intentar comprar 10 unidades (solo quedan 3) — debe ser rechazado."""
    assert Shared.producto_id is not None, "Primero debe crear producto"

    pedido = {
        "tenant_id": TENANT_ID,
        "alumno_id": ALUMNO_ID,
        "producto_id": Shared.producto_id,
        "cantidad": 10,
        "estado": "pendiente"
    }
    r = requests.post(f"{BASE}/pedidos", json=pedido)
    assert r.status_code == 400, \
        f"Stock insuficiente deberia dar 400, status: {r.status_code}, body: {r.text[:200]}"
    data = r.json()
    assert "stock" in data.get("detail", "").lower(), \
        f"Debe mencionar stock insuficiente: {data.get('detail', '')}"
    print(f"  [OK] Compra de 10 rechazada (400) - stock insuficiente")
