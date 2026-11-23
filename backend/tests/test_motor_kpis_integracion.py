"""Pruebas de integración del motor de KPIs (SÓLO TEST, con rollback).

Se ejecutan así (desde `backend/`):
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_motor_kpis_integracion.py -q --noconftest

El fixture `motor_kpis_fixture()` abre UNA transacción, inserta el escenario y la
revierte al final. `guard_test_db()` aborta si el host de `DATABASE_URL` no es
exactamente el endpoint de TEST permitido.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook
from sqlalchemy import text

from app.api.v1 import kpis, kpis_populate
from app.services import metricas_service as metricas
from app.services import reportes_service
from app.utils.santiago import hoy_santiago
from ml import entrenar as ml_entrenar
from tests.fixtures_kpis_motor import (
    ESPERADO, FIN_KPI, MES_KPI, guard_test_db, motor_kpis_fixture)


@pytest.fixture(autouse=True)
def _guard_test():
    """La guarda también se evalúa antes de cada prueba, sin tocar la base."""
    guard_test_db()


def _plan(financiero: dict, nombre: str) -> dict:
    return next(p for p in financiero["ticket_promedio"]["por_plan"]
                if p["plan"] == nombre)


def _cohorte(resultado: dict, label: str) -> dict:
    return next(c for c in resultado["cohortes"] if c["cohorte"] == label)


def _money(valor) -> float:
    """Convierte una celda del Excel (`$380,000`) a float."""
    if isinstance(valor, (int, float)):
        return float(valor)
    return float(str(valor).replace("$", "").replace(",", "").strip())


def test_motor_kpis_valores_esperados():
    with motor_kpis_fixture() as (db, datos):
        tid = datos["tenant_id"]
        hoy = hoy_santiago()

        # ── Dinero: usuarios es_prueba fuera ──────────────────────────────
        assert metricas.mrr(db, tid, hoy) == pytest.approx(ESPERADO["mrr"])
        assert (metricas.alumnos_vigentes(db, tid, hoy)
                == ESPERADO["alumnos_vigentes_hoy"])
        assert (metricas.alumnos_vigentes(db, tid, FIN_KPI)
                == ESPERADO["alumnos_vigentes_cierre_mes"])
        assert (metricas.ingresos_netos(db, tid, MES_KPI, FIN_KPI)
                == pytest.approx(ESPERADO["ingresos_netos_mes"]))
        assert (metricas.ventas_bazar(db, tid, MES_KPI, FIN_KPI)
                == pytest.approx(ESPERADO["bazar_mes"]))

        # ── Conversión prueba → plan ──────────────────────────────────────
        embudo = kpis_populate.calcular_embudo_conversion(
            db, tid, MES_KPI, FIN_KPI)
        assert embudo["alumnos_prueba"] == ESPERADO["alumnos_prueba"]
        assert (embudo["alumnos_plan_comprado"]
                == ESPERADO["alumnos_plan_comprado"])
        assert (embudo["conversion_rate"]
                == pytest.approx(ESPERADO["conversion_rate"]))
        assert embudo["alumnos_clase_prueba_ejecutada"] == 3

        # ── Asistencia REAL del mes ───────────────────────────────────────
        asistencia = kpis_populate.calcular_asistencia_mes(
            db, tid, MES_KPI, FIN_KPI)
        assert asistencia["asistentes"] == ESPERADO["asistentes_mes"]
        assert asistencia["reservas"] == ESPERADO["reservas_mes"]
        assert (asistencia["asistencia_promedio"]
                == pytest.approx(ESPERADO["asistencia_real_pct"]))

        # ── Ticket global/por plan + vida ─────────────────────────────────
        financiero = kpis.get_financiero(
            db=db, current_user={"tenant_id": tid})
        ticket = financiero["ticket_promedio"]
        assert ticket["n_transacciones"] == ESPERADO["ticket_n"]
        assert (ticket["ingreso_total"]
                == pytest.approx(ESPERADO["ticket_ingreso_total"]))
        assert ticket["global"] == pytest.approx(ESPERADO["ticket_global"])

        p40 = _plan(financiero, "Plan 40K")
        p60 = _plan(financiero, "Plan 60K")
        ptest = _plan(financiero, "Plan Test 50K")
        assert (p40["suscripciones"], p40["n_transacciones"],
                p40["ingreso_total"]) == (10, 10, 400_000.0)
        assert (p60["suscripciones"], p60["n_transacciones"],
                p60["ingreso_total"]) == (5, 5, 300_000.0)
        # El plan de las 5 cuentas de prueba no tiene ni suscripciones ni dinero.
        assert (ptest["suscripciones"], ptest["n_transacciones"],
                ptest["ingreso_total"]) == (0, 0, 0.0)

        vida = financiero["vida"]
        assert vida["vida_promedio_dias"] == ESPERADO["vida_dias"]
        assert (vida["vida_promedio_meses"]
                == pytest.approx(ESPERADO["vida_meses"]))
        assert vida["n_alumnos"] == ESPERADO["vida_n_alumnos"]
        assert vida["n_con_baja"] == ESPERADO["vida_n_con_baja"]

        # ── Cohortes: 4 -> n/d (insuficiente), 5 -> 60 % ──────────────────
        cohortes = kpis.get_cohortes(
            db=db, current_user={"tenant_id": tid})
        c4 = _cohorte(cohortes, datos["cohorte_4"])
        c5 = _cohorte(cohortes, datos["cohorte_5"])
        c6 = _cohorte(cohortes, datos["cohorte_6"])
        assert c4["n_alumnos"] == 4
        assert c4["h30"]["evaluables"] == ESPERADO["cohorte_4_evaluables"]
        assert c4["h30"]["activos"] == ESPERADO["cohorte_4_activos"]
        assert c4["h30"]["retencion_pct"] is None
        assert c5["n_alumnos"] == 5
        assert c5["h30"]["evaluables"] == ESPERADO["cohorte_5_evaluables"]
        assert c5["h30"]["activos"] == ESPERADO["cohorte_5_activos"]
        assert (c5["h30"]["retencion_pct"]
                == pytest.approx(ESPERADO["cohorte_5_retencion_pct"]))
        # Los 5 es_prueba tienen la misma fecha de alta que la cohorte C: no
        # deben inflar el n_alumnos (6 reales, no 11).
        assert c6["n_alumnos"] == 6

        # ── Serie del forecast: octubre real, sin transacciones de prueba ─
        serie = ml_entrenar.serie_mensual(db, tid)
        octubre = next(neto for (y, m, neto) in serie
                       if (y, m) == (2026, 10))
        assert octubre == pytest.approx(ESPERADO["forecast_octubre_neto"])



def test_regresion_es_prueba_en_dinero():
    """Si se quita el filtro es_prueba de las transacciones, esto falla."""
    with motor_kpis_fixture() as (db, datos):
        tid = datos["tenant_id"]
        neto = metricas.ingresos_netos(db, tid, MES_KPI, FIN_KPI)
        assert neto == pytest.approx(380_000.0)
        assert neto != pytest.approx(630_000.0)  # +250.000 de prueba

        financiero = kpis.get_financiero(
            db=db, current_user={"tenant_id": tid})
        global_ticket = financiero["ticket_promedio"]["global"]
        assert global_ticket == pytest.approx(46_667.0)
        assert global_ticket != pytest.approx(47_500.0)  # 950.000 / 20

        assert (metricas.ventas_bazar(db, tid, MES_KPI, FIN_KPI)
                == pytest.approx(10_000.0))

        serie = ml_entrenar.serie_mensual(db, tid)
        octubre = next(neto for (y, m, neto) in serie
                       if (y, m) == (2026, 10))
        assert octubre == pytest.approx(380_000.0)


def test_regresion_rechazado_en_mrr():
    """Si se quita el estado 'rechazado' del MRR, el valor sube a 820.000."""
    with motor_kpis_fixture() as (db, datos):
        tid = datos["tenant_id"]
        mrr = metricas.mrr(db, tid, hoy_santiago())
        assert mrr == pytest.approx(700_000.0)

        rechazado = float(db.execute(text("""
            SELECT COALESCE(SUM(p.precio_clp), 0)
            FROM suscripciones s
            JOIN planes p ON p.id = s.plan_id
            JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.tenant_id = :tid
              AND u.estado = 'rechazado'
              AND NOT u.es_prueba
        """), {"tid": tid}).scalar() or 0)
        assert rechazado == pytest.approx(120_000.0)
        assert mrr != pytest.approx(700_000.0 + rechazado)


def test_conversion_no_suma_miembro_comprador():
    """Un miembro previo que compra en el mes NO entra al cohorte de prueba."""
    with motor_kpis_fixture() as (db, datos):
        tid = datos["tenant_id"]

        # Numerador "viejo": TODAS las compras pagas reales que empiezan en
        # octubre. Son 3: la renovación de A0 + los 2 compradores del cohorte C.
        compras_pagas = int(db.execute(text("""
            SELECT COUNT(*)
            FROM suscripciones s
            JOIN planes p ON p.id = s.plan_id
            JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.tenant_id = :tid
              AND u.tenant_id = :tid
              AND u.rol = 'alumno'
              AND NOT u.es_prueba
              AND p.precio_clp > 0
              AND (s.fecha_inicio AT TIME ZONE 'America/Santiago')::date >= :ini
              AND (s.fecha_inicio AT TIME ZONE 'America/Santiago')::date <= :fin
        """), {"tid": tid, "ini": MES_KPI, "fin": FIN_KPI}).scalar() or 0)
        assert compras_pagas == ESPERADO["compras_pagas_mes"] == 3

        embudo = kpis_populate.calcular_embudo_conversion(
            db, tid, MES_KPI, FIN_KPI)
        # Sólo los 2 compradores del cohorte de prueba; A0 queda fuera.
        assert embudo["alumnos_prueba"] == 6
        assert embudo["alumnos_plan_comprado"] == 2
        assert embudo["conversion_rate"] == pytest.approx(33.33)


def test_reporte_excel_y_historico_coinciden_con_ingresos_netos():
    """El neto del Excel y el histórico usan el mismo neto que metricas."""
    with motor_kpis_fixture() as (db, datos):
        tid = datos["tenant_id"]
        neto_metricas = metricas.ingresos_netos(
            db, tid, MES_KPI, FIN_KPI)
        assert neto_metricas == pytest.approx(380_000.0)

        excel = reportes_service.crear_reporte_ventas_mensual_bytes(
            db, tid, 10, 2026)
        wb = load_workbook(io.BytesIO(excel), data_only=True)
        assert "Este mes" in wb.sheetnames
        assert "Por alumno" in wb.sheetnames

        ws = wb["Este mes"]
        neto_excel = None
        for row in range(1, ws.max_row + 1):
            if ws.cell(row, 1).value == "Neto":
                neto_excel = _money(ws.cell(row, 2).value)
                break
        assert neto_excel == pytest.approx(neto_metricas)

        # La hoja "Por alumno" no tiene una fila de "neto": su total es el
        # ingreso de membresías (700.000), no el neto del mes. Se valida que
        # excluya las cuentas de prueba; el neto real está en "Este mes" y en
        # el histórico, y ambos se comparan contra ingresos_netos.
        ws = wb["Por alumno"]
        total_membresias = None
        pagos = None
        for row in range(1, ws.max_row + 1):
            label = ws.cell(row, 1).value
            if label == "Total cobrado en membresías":
                total_membresias = _money(ws.cell(row, 2).value)
            elif label == "Cantidad de pagos de membresía":
                pagos = int(ws.cell(row, 2).value)
        assert total_membresias == pytest.approx(
            ESPERADO["ticket_ingreso_total"])
        assert total_membresias != pytest.approx(950_000.0)
        assert pagos == ESPERADO["ticket_n"]

        historico = reportes_service._build_historico_mensual(db, tid)
        octubre = next(h for h in historico
                       if h["anio"] == 2026 and h["mes_num"] == 10)
        assert octubre["neto"] == pytest.approx(neto_metricas)
        assert octubre["ingresos"] == pytest.approx(480_000.0)
        assert octubre["egresos"] == pytest.approx(100_000.0)

