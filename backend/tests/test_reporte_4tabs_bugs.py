"""Bugs de datos del reporte Excel 4 pestañas (MoM/YoY/YTD/ARPU).

  * Bug 1: en YTD las columnas de dinero eran {3,4}; debían ser {2,3} (la
    columna 4 es "Variación", texto). Se verifica el `number_format` de las
    celdas. Se corrigió el mismo error en "Por plan" del ARPU ({3,5,6}->{2,4,5}).
  * Bug 2: "Por plan" contaba TODA la historia; ahora sólo suscripciones
    VIGENTES HOY (`sql_suscripcion_vigente`).
  * Bug 3: con el mes en curso, MoM compara "lo que va del mes" contra el
    MISMO tramo del mes anterior (día N vs día N), no contra el mes completo.

Genera el reporte con `crear_reporte_ventas_mensual_bytes` y lee las celdas
con openpyxl. Contra la rama TEST (escribe y limpia).

    cd backend && py -3.12 -m pytest tests/test_reporte_4tabs_bugs.py -q --noconftest
"""
import sys
import uuid
from datetime import date, datetime, time as _time, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import reportes_service as rep          # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago     # noqa: E402


@pytest.fixture()
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    session = SessionLocal()
    yield session
    session.close()


def _sufijo():
    return f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


def _mediodia(d):
    """Instante tz-aware (mediodía de Chile) para una columna timestamptz."""
    return datetime.combine(d, _time(12, 0), tzinfo=SANTIAGO)


def _crear_tenant(db):
    sufijo = _sufijo()
    return db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
        VALUES (:n, :s, :pub, true, now()) RETURNING id
    """), {"n": f"Box Rep {sufijo}", "s": f"box-rep-{sufijo}",
           "pub": str(uuid.uuid4())}).scalar()


def _crear_usuario(db, tenant_id):
    sufijo = _sufijo()
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, :n, :c, 'x', 'alumno', true, 'activo', now())
        RETURNING id
    """), {"t": tenant_id, "r": f"96{uuid.uuid4().hex[:8]}",
           "n": f"Alumno rep {sufijo}", "c": f"rep.{sufijo}@test.local"}).scalar()


def _crear_plan(db, tenant_id, nombre, precio):
    return db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                            duracion_dias, activo, es_comercial)
        VALUES (:t, :n, 10, false, :p, 30, true, true) RETURNING id
    """), {"t": tenant_id, "n": nombre, "p": precio}).scalar()


def _crear_suscripcion(db, tenant_id, usuario_id, plan_id, inicio, expiracion,
                       estado="activo"):
    return db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                   creditos_totales, creditos_disponibles,
                                   fecha_inicio, fecha_expiracion)
        VALUES (:t, :u, :p, CAST(:e AS estado_suscripcion), 10, 10, :i, :f)
        RETURNING id
    """), {"t": tenant_id, "u": usuario_id, "p": plan_id, "e": estado,
           "i": _mediodia(inicio), "f": _mediodia(expiracion)}).scalar()


def _crear_transaccion(db, tenant_id, monto, fecha):
    return db.execute(text("""
        INSERT INTO transacciones_financieras
            (tenant_id, tipo, categoria, monto, fecha, referencia_tipo)
        VALUES (:t, 'ingreso', 'membresia', :m, :f, 'suscripcion')
        RETURNING id
    """), {"t": tenant_id, "m": monto, "f": fecha}).scalar()


def _limpiar(db, tenant_id):
    db.rollback()
    try:
        db.execute(text("DELETE FROM transacciones_financieras WHERE tenant_id = :t"),
                   {"t": tenant_id})
        db.execute(text("DELETE FROM suscripciones WHERE tenant_id = :t"),
                   {"t": tenant_id})
        db.execute(text("DELETE FROM planes WHERE tenant_id = :t"), {"t": tenant_id})
        db.execute(text("DELETE FROM usuarios WHERE tenant_id = :t"), {"t": tenant_id})
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"\n[WARN] limpieza test_reporte_4tabs_bugs: {e}")


# ── Bug 1: formato de dinero en YTD (y en "Por plan" del ARPU) ──────────────
def test_bug1_ytd_columnas_de_dinero_son_b_y_c(db):
    hoy = hoy_santiago()
    # Un tenant sin datos basta: la tabla YTD se arma igual (con ceros).
    contenido = rep.crear_reporte_ventas_mensual_bytes(db, 999999999,
                                                       hoy.month, hoy.year)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["YTD"]
    assert ws.cell(6, 1).value == "Concepto"  # sanity: la data arranca en A
    for fila in range(7, 11):                 # Ingresos, Egresos, Neto, Nuevos
        # Col B (año actual) y col C (año anterior) = dinero con miles.
        assert ws.cell(fila, 2).number_format == "#,##0", f"col B fila {fila}"
        assert ws.cell(fila, 3).number_format == "#,##0", f"col C fila {fila}"
        # Col D es "Variación" (texto tipo +12.3%): NO lleva formato de dinero.
        assert ws.cell(fila, 4).number_format != "#,##0", f"col D fila {fila}"
    wb.close()


# ── Bug 2: "Por plan" cuenta sólo suscripciones vigentes HOY ────────────────
def test_bug2_por_plan_cuenta_solo_vigentes_hoy(db):
    hoy = hoy_santiago()
    tenant = _crear_tenant(db)
    suf = _sufijo()
    nombre_a = f"Plan A {suf}"
    nombre_b = f"Plan B {suf}"
    plan_a = _crear_plan(db, tenant, nombre_a, 40000)
    plan_b = _crear_plan(db, tenant, nombre_b, 30000)

    # Plan A: 2 vigentes hoy + 1 ya vencida (no debe contar).
    for _ in range(2):
        u = _crear_usuario(db, tenant)
        _crear_suscripcion(db, tenant, u, plan_a, hoy - timedelta(days=10),
                           hoy + timedelta(days=10))
    u = _crear_usuario(db, tenant)
    _crear_suscripcion(db, tenant, u, plan_a, hoy - timedelta(days=40),
                       hoy - timedelta(days=1))
    # Plan B: 1 futura (todavía no empieza -> no vigente hoy).
    u = _crear_usuario(db, tenant)
    _crear_suscripcion(db, tenant, u, plan_b, hoy + timedelta(days=5),
                       hoy + timedelta(days=35))
    db.commit()

    try:
        contenido = rep.crear_reporte_ventas_mensual_bytes(
            db, tenant, hoy.month, hoy.year)
        wb = load_workbook(BytesIO(contenido))
        ws = wb["ARPU"]
        # Tabla "Por plan": header en fila 11, data desde 12 (A=Plan, C=Suscripciones).
        conteo = {}
        for fila in range(12, ws.max_row + 1):
            nombre = ws.cell(fila, 1).value
            if not nombre or str(nombre).startswith("Ticket"):
                break
            conteo[str(nombre)] = ws.cell(fila, 3).value
        assert conteo.get(nombre_a) == 2, conteo
        assert conteo.get(nombre_b) == 0, conteo
        wb.close()
    finally:
        _limpiar(db, tenant)


# ── Bug 3: MoM del mes en curso corta el mes anterior al mismo día ──────────
def test_bug3_mom_mes_en_curso_compara_dia_contra_dia(db, monkeypatch):
    hoy_fijo = date(2026, 11, 11)
    monkeypatch.setattr(rep, "hoy_santiago", lambda: hoy_fijo)

    tenant = _crear_tenant(db)
    # Actual (nov): 5-nov = $1.000.
    # Anterior (oct): 11-oct = $500 (dentro del tramo) y 20-oct = $7.000 (fuera
    # del tramo: con el bug, el mes completo lo sumaba y daba $7.500).
    _crear_transaccion(db, tenant, 1000, date(2026, 11, 5))
    _crear_transaccion(db, tenant, 500, date(2026, 10, 11))
    _crear_transaccion(db, tenant, 7000, date(2026, 10, 20))
    db.commit()

    try:
        contenido = rep.crear_reporte_ventas_mensual_bytes(db, tenant, 11, 2026)
        wb = load_workbook(BytesIO(contenido))
        ws = wb["MoM"]
        # El subtítulo (fila 3) avisa que la comparación es parcial.
        subtitulo = ws.cell(3, 1).value or ""
        assert "comparado al día 11" in subtitulo, subtitulo
        # "Ingresos" = fila 12: A=Concepto, B=actual, C=anterior.
        assert ws.cell(12, 1).value == "Ingresos"
        assert ws.cell(12, 2).value == "$1,000"
        assert ws.cell(12, 3).value == "$500", ws.cell(12, 3).value
        wb.close()
    finally:
        _limpiar(db, tenant)
