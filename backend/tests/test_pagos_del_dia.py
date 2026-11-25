"""
Cobros de planes del día: `GET /api/v1/admin/pagos-del-dia`.

Dos bloques, sin red y sin base:

1. **Contrato HTTP** (app mínima con sólo el router de admin, `get_db` sustituido
   y el servicio monkeypatcheado): sin token ⇒ 401, un ALUMNO ⇒ 403 (el guard
   real de `get_current_admin`), un admin ⇒ el resumen de SU tenant (`tenant_id`
   del token, nunca del body) y `dia` opcional validado como fecha.
2. **Reglas del servicio** con objetos de mentira: el rango del día en hora de
   Chile, la hora `HH:MM`, el estado del NEGOCIO (Activo sólo si el cobro está
   aprobado Y tiene suscripción activa) y las sumas del resumen.

Además se fija, sobre el código, que el filtro es por día chileno
(`coalesce(pagado_en, created_at)`) y por tenant: sin esa columna, un cobro de
las 21:30 de Chile se iría al día UTC siguiente.

Correr (aislado, sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_pagos_del_dia.py -q --noconftest
"""
import inspect
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import admin as api_admin                    # noqa: E402
from app.core.dependencies import get_current_admin, get_current_user  # noqa: E402
from app.db.database import get_db                            # noqa: E402
from app.services import pagos_del_dia as svc                 # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago          # noqa: E402

RUTA = "/api/v1/admin/pagos-del-dia"

ADMIN = {"usuario_id": 9, "tenant_id": 1, "rol": "administrador"}
ALUMNO = {"usuario_id": 3, "tenant_id": 1, "rol": "alumno"}


class _SesionVacia:
    """La base no se toca: el servicio está monkeypatcheado en el contrato HTTP."""


def _app(usuario):
    """App mínima: sólo el router de admin. `usuario=None` deja la auth real."""
    app = FastAPI()
    app.include_router(api_admin.router, prefix="/api/v1/admin")
    app.dependency_overrides[get_db] = lambda: _SesionVacia()
    if usuario is not None:
        app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app, raise_server_exceptions=False)


# ── Bloque 1: contrato HTTP ─────────────────────────────────────────────────
def test_sin_token_es_401():
    assert _app(None).get(RUTA).status_code == 401


def test_un_alumno_no_ve_los_pagos_del_box():
    """El guard es el REAL (`get_current_admin`): el rol del token decide."""
    respuesta = _app(ALUMNO).get(RUTA)
    assert respuesta.status_code == 403
    assert "administrador" in respuesta.json()["detail"]


def test_el_admin_recibe_el_resumen_de_su_tenant(monkeypatch):
    llamadas = []

    def falso(db, tenant_id, dia=None):
        llamadas.append({"tenant_id": tenant_id, "dia": dia})
        return {"fecha": "2026-11-21",
                "resumen": {"cantidad": 0, "total_clp": 0}, "pagos": []}

    monkeypatch.setattr(svc, "resumen_del_dia", falso)
    respuesta = _app(ADMIN).get(RUTA)

    assert respuesta.status_code == 200
    assert respuesta.json()["fecha"] == "2026-11-21"
    # `tenant_id` sale del token (1), no de ningún parámetro del request.
    assert llamadas == [{"tenant_id": 1, "dia": None}]


def test_el_dia_opcional_llega_como_fecha(monkeypatch):
    capturado = {}

    def falso(db, tenant_id, dia=None):
        capturado["dia"] = dia
        return {"fecha": dia.isoformat(), "resumen": {}, "pagos": []}

    monkeypatch.setattr(svc, "resumen_del_dia", falso)
    respuesta = _app(ADMIN).get(RUTA, params={"dia": "2026-11-01"})

    assert respuesta.status_code == 200
    assert capturado["dia"] == date(2026, 11, 1)


def test_un_dia_malformado_es_422(monkeypatch):
    def falso(db, tenant_id, dia=None):  # pragma: no cover - no debe llamarse
        raise AssertionError("no debería llegar al servicio")

    monkeypatch.setattr(svc, "resumen_del_dia", falso)
    assert _app(ADMIN).get(RUTA, params={"dia": "ayer"}).status_code == 422


def test_la_ruta_exige_admin_por_token():
    ruta = next(r for r in api_admin.router.routes
                if getattr(r, "path", "") == "/pagos-del-dia")
    dependencias = [d.call for d in ruta.dependant.dependencies]
    assert get_current_admin in dependencias
    # El endpoint no recibe `tenant_id` ni `alumno_id`: no hay forma de pedir el
    # día de otro box por parámetro.
    nombres = set(inspect.signature(ruta.endpoint).parameters)
    assert nombres == {"dia", "db", "current_user"}


# ── Bloque 2: reglas del servicio ───────────────────────────────────────────
def _pago(**extra):
    datos = {
        "id": 12, "usuario_id": 3, "monto_clp": 40000, "estado": "aprobado",
        # 17:05 UTC = 14:05 en Chile (UTC-3 en noviembre).
        "pagado_en": datetime(2026, 11, 21, 17, 5, tzinfo=timezone.utc),
        "created_at": datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc),
    }
    datos.update(extra)
    return SimpleNamespace(**datos)


def _solicitud(**extra):
    datos = {"id": 55, "tenant_id": 1, "alumno_id": 3, "plan_id": 2}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _alumno(**extra):
    datos = {"id": 3, "nombre": "Ana Pérez"}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _plan(**extra):
    datos = {"id": 2, "nombre": "Plan Full"}
    datos.update(extra)
    return SimpleNamespace(**datos)


def _suscripcion(**extra):
    datos = {"id": 9, "pago_id": 12, "estado": "activo"}
    datos.update(extra)
    return SimpleNamespace(**datos)


def test_rango_del_dia_usa_los_bordes_de_chile():
    dia, inicio, fin = svc.rango_del_dia(date(2026, 11, 21))

    assert dia == date(2026, 11, 21)
    assert inicio == datetime(2026, 11, 21, 0, 0, 0, tzinfo=SANTIAGO)
    assert fin == datetime(2026, 11, 21, 23, 59, 59, tzinfo=SANTIAGO)
    assert inicio < fin


def test_rango_del_dia_por_defecto_es_hoy_en_chile():
    dia, inicio, fin = svc.rango_del_dia()

    assert dia == hoy_santiago()
    assert inicio.date() == fin.date() == dia
    # Un día completo, no una ventana móvil de 24 h corridas.
    assert (fin - inicio).total_seconds() < 24 * 3600


def test_hora_chile_convierte_utc_a_santiago():
    assert svc.hora_chile(
        datetime(2026, 1, 15, 2, 30, tzinfo=timezone.utc)) == "23:30"  # UTC-3
    assert svc.hora_chile(None) is None


def test_valor_estado_acepta_el_enum_de_suscripcion():
    """`str(EstadoSuscripcion.activo)` no sirve en py3.11+: se lee `.value`."""
    class _Estado:
        value = "activo"

    assert svc.valor_estado(_Estado()) == "activo"
    assert svc.valor_estado("vencido") == "vencido"
    assert svc.valor_estado(None) == ""


def test_pago_aprobado_con_suscripcion_activa_es_activo():
    fila = svc.serializar_pago(
        _pago(), _solicitud(), _alumno(), _plan(), _suscripcion())

    assert fila["estado"] == "activo"
    assert fila["estado_pago"] == "aprobado"
    assert fila["monto_clp"] == 40000
    assert fila["plan"] == "Plan Full"
    assert fila["nombre"] == "Ana Pérez"
    assert fila["hora"] == "14:05"
    assert fila["suscripcion_id"] == 9
    assert fila["solicitud_id"] == 55


def test_pago_aprobado_sin_suscripcion_es_pendiente_de_activar():
    """El caso del webhook perdido: la plata existe y el plan no."""
    fila = svc.serializar_pago(
        _pago(), _solicitud(estado="expirada"), _alumno(), _plan(), None)

    assert fila["estado"] == "pendiente"
    assert fila["estado_pago"] == "aprobado"


def test_suscripcion_vencida_no_cuenta_como_activa():
    fila = svc.serializar_pago(
        _pago(), _solicitud(), _alumno(), _plan(),
        _suscripcion(estado="vencido"))

    assert fila["estado"] == "pendiente"


def test_cobro_pendiente_es_pendiente_aunque_haya_suscripcion():
    fila = svc.serializar_pago(
        _pago(estado="pendiente", pagado_en=None), _solicitud(),
        _alumno(), _plan(), _suscripcion())

    assert fila["estado"] == "pendiente"
    # Sin `pagado_en` la hora sale del `created_at` (16:00 UTC = 13:00 Chile).
    assert fila["hora"] == "13:00"


def test_sin_alumno_y_sin_plan_no_se_inventan_datos():
    fila = svc.serializar_pago(
        _pago(usuario_id=77), None, None, None, None)

    assert fila["nombre"] == "Alumno #77"
    assert fila["plan"] == "Sin plan"
    assert fila["solicitud_id"] is None
    assert fila["estado"] == "pendiente"


class _Consulta:
    def __init__(self, filas):
        self.filas = filas

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.filas)


class _SesionFalsa:
    """Sesión de mentira: devuelve las filas dadas, en ese orden."""

    def __init__(self, filas):
        self.filas = filas
        self.modelos = []

    def query(self, *modelos):
        self.modelos.append(modelos)
        return _Consulta(self.filas)


def test_resumen_del_dia_suma_y_cuenta_los_pendientes(monkeypatch):
    filas = [
        (_pago(id=1, monto_clp=40000), _solicitud(id=55), _alumno(), _plan()),
        (_pago(id=2, monto_clp=30000, estado="pendiente", pagado_en=None),
         _solicitud(id=56), _alumno(), _plan()),
    ]
    sesion = _SesionFalsa(filas)
    pedidos = []
    monkeypatch.setattr(
        svc, "suscripciones_por_pago",
        lambda db, tenant_id, ids: (pedidos.append((tenant_id, list(ids)))
                                    or {1: _suscripcion()}))

    resumen = svc.resumen_del_dia(sesion, 1, dia=date(2026, 11, 21))

    assert resumen["fecha"] == "2026-11-21"
    assert resumen["resumen"] == {
        "cantidad": 2, "total_clp": 70000, "pendientes_activar": 1}
    assert [p["pago_id"] for p in resumen["pagos"]] == [1, 2]
    assert [p["estado"] for p in resumen["pagos"]] == ["activo", "pendiente"]
    # Las suscripciones se buscan SÓLO de esos pagos y del mismo box.
    assert pedidos == [(1, [1, 2])]


def test_el_total_de_la_tarjeta_es_la_suma_de_los_cobros_listados(monkeypatch):
    """Los dos cobros de prueba de hoy: 25.000 (membresía) + 15.000 (Bazar) = 40.000.

    Es el valor que pinta "Ingresos de hoy": sale de `resumen.total_clp`, la MISMA
    cifra que muestra el encabezado de "Pagos del día", y tiene que ser igual a la
    suma de los montos de la lista (nunca un total de otra fuente, como la caja de
    `transacciones_financieras`).
    """
    filas = [
        (_pago(id=8, monto_clp=25000, concepto="membresia"),
         _solicitud(id=55), _alumno(), _plan()),
        (_pago(id=9, monto_clp=15000, concepto="bazar", referencia_id=77),
         None, _alumno(), None),
    ]
    monkeypatch.setattr(
        svc, "suscripciones_por_pago",
        lambda db, tenant_id, ids: {8: _suscripcion(pago_id=8)})
    monkeypatch.setattr(
        svc, "productos_por_pedido",
        lambda db, tenant_id, ids: {77: "Camiseta · Talla M"})

    resumen = svc.resumen_del_dia(
        _SesionFalsa(filas), 1, dia=date(2026, 11, 21))

    assert resumen["resumen"]["cantidad"] == 2
    assert resumen["resumen"]["total_clp"] == 40000
    assert resumen["resumen"]["total_clp"] == sum(
        p["monto_clp"] for p in resumen["pagos"])
    assert [p["origen"] for p in resumen["pagos"]] == ["membresia", "bazar"]


# ── El filtro, en el código del servicio ────────────────────────────────────
def test_el_filtro_es_por_dia_chileno_y_por_tenant():
    fuente = (BACKEND / "app" / "services" / "pagos_del_dia.py").read_text(
        encoding="utf-8")

    assert "func.coalesce(Pago.pagado_en, Pago.created_at)" in fuente, (
        "un `pendiente` no tiene pagado_en: sin el coalesce desaparece del día")
    assert "Pago.tenant_id == tenant_id" in fuente
    assert "Pago.estado.in_(ESTADOS_DEL_DIA)" in fuente
    assert "SolicitudPlan.tenant_id == Pago.tenant_id" in fuente, (
        "la solicitud del join no puede ser de otro box")
    assert "Pago.concepto.in_(CONCEPTOS_DEL_DIA)" in fuente, (
        "la lista del día incluye membresías Y compras del Bazar: las dos viven en `pagos`")


# ── Correo, origen y canal de pago (lo que pide la tarjeta "Ingresos de hoy") ─
def test_serializar_pago_incluye_correo_origen_y_canal():
    fila = svc.serializar_pago(
        _pago(metodo_pago="visa"), _solicitud(),
        _alumno(correo="ana@box.cl"), _plan(), _suscripcion())

    assert fila["correo"] == "ana@box.cl"
    assert fila["origen"] == "membresia"
    assert fila["origen_detalle"] == "Plan Full"
    assert fila["producto"] == "Plan Full"
    assert fila["canal"] == "Mercado Pago"
    assert fila["canal_detalle"] == "visa"
    assert fila["estado_pago"] == "aprobado"


def test_un_cobro_del_bazar_usa_el_producto_y_no_espera_suscripcion():
    fila = svc.serializar_pago(
        _pago(concepto="bazar", referencia_id=77), None, _alumno(), None, None,
        origen_detalle="Camiseta M")

    assert fila["origen"] == "bazar"
    assert fila["producto"] == "Camiseta M"
    assert fila["origen_detalle"] == "Camiseta M"
    assert fila["plan"] == "Camiseta M"
    # Un cobro aprobado del Bazar no tiene plan que activar: ya está "activo".
    assert fila["estado"] == "activo"


def test_el_medio_de_pago_sale_del_tipo_pago_de_mercadopago():
    """`pagos.tipo_pago` (payment_type_id) distingue crédito / débito / transferencia."""
    credito = svc.serializar_pago(
        _pago(tipo_pago="credit_card"), _solicitud(), _alumno(), _plan(), _suscripcion())
    debito = svc.serializar_pago(
        _pago(tipo_pago="debit_card"), _solicitud(), _alumno(), _plan(), _suscripcion())
    banco = svc.serializar_pago(
        _pago(tipo_pago="bank_transfer"), _solicitud(), _alumno(), _plan(), _suscripcion())

    assert credito["tipo_cobro"] == "Tarjeta de crédito"
    assert credito["tipo_cobro_clave"] == "tarjeta_credito"
    assert debito["tipo_cobro"] == "Tarjeta de débito"
    assert debito["tipo_cobro_clave"] == "tarjeta_debito"
    assert banco["tipo_cobro"] == "Transferencia"
    assert banco["tipo_cobro_clave"] == "transferencia"


def test_sin_tipo_de_pago_no_se_inventa_el_medio():
    """Sin `tipo_pago` se muestra el canal REAL (Mercado Pago), nunca un crédito supuesto."""
    fila = svc.serializar_pago(
        _pago(tipo_pago=None), _solicitud(), _alumno(), _plan(), _suscripcion())

    assert fila["tipo_cobro"] == "Mercado Pago"
    assert fila["tipo_cobro_clave"] == "canal"


def test_el_producto_del_bazar_lleva_la_talla_cuando_existe():
    assert svc.texto_producto("Camiseta", "M") == "Camiseta · Talla M"
    assert svc.texto_producto("Camiseta", None) == "Camiseta"
    assert svc.texto_producto(None, "M") is None
    assert svc.texto_producto("  ", "M") is None


def test_sin_alumno_el_correo_es_null_no_un_texto_inventado():
    fila = svc.serializar_pago(_pago(usuario_id=77), None, None, None, None)

    assert fila["correo"] is None
    assert fila["canal"] == "Mercado Pago"
    assert fila["canal_detalle"] is None
