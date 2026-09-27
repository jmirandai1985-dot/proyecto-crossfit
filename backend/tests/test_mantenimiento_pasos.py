"""Tests del fix H1 (2026-09-27): los runners diario/mensual reflejan el resultado REAL.

Antes, `run_daily.py` y `run_monthly.py` logueaban "✅ <paso> OK" sin mirar lo que devolvía
cada script, así que un job con fallas quedaba con todos los ✅. Estos tests usan módulos
falsos (nunca los de verdad: no se toca ninguna base) y comprueban que un `False` se loguea
como error y que el resumen final dice cuántos pasos fallaron.

Se corre con:
    py -3.12 -m pytest tests/test_mantenimiento_pasos.py -q --noconftest
"""
import logging
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from maintenance import run_daily as rd  # noqa: E402
from maintenance import run_monthly as rm  # noqa: E402


def _modulo_falso(monkeypatch, nombre: str, funciones: dict) -> None:
    """Reemplaza `maintenance.<x>` por un módulo falso en sys.modules (sin tocar la base)."""
    modulo = types.ModuleType(nombre)
    for fn_nombre, fn in funciones.items():
        setattr(modulo, fn_nombre, fn)
    monkeypatch.setitem(sys.modules, nombre, modulo)


@pytest.mark.parametrize("runner", [rd, rm])
def test_paso_devuelve_false_cuando_el_script_falla(runner, caplog):
    with caplog.at_level(logging.INFO):
        assert runner._paso("1/5", "prueba", lambda: False) is False
        assert runner._paso("2/5", "prueba", lambda: None) is True
        assert runner._paso("3/5", "prueba", lambda: True) is True
        assert runner._paso("4/5", "prueba", lambda: 1 / 0) is False

    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "❌ prueba devolvió False" in texto
    assert "✅ 2/5 prueba OK" in texto          # None NO es un fallo
    assert "❌ prueba falló: division by zero" in texto


def test_run_daily_cuenta_los_fallos_en_el_resumen(monkeypatch, caplog):
    _modulo_falso(monkeypatch, "maintenance.backup_neon",
                  {"ejecutar_backup": lambda: False})
    _modulo_falso(monkeypatch, "maintenance.marcar_plan_vencido",
                  {"marcar_vencidos": lambda: False})
    _modulo_falso(monkeypatch, "maintenance.transacciones_huerfanas",
                  {"limpiar_huerfanas": lambda: True})
    _modulo_falso(monkeypatch, "maintenance.health_check",
                  {"verificar_salud": lambda: None})
    _modulo_falso(monkeypatch, "maintenance.neon_usage_alerts",
                  {"verificar_uso": lambda: False})

    with caplog.at_level(logging.INFO):
        rd.run()

    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "❌ JOB DIARIO TERMINADO CON 3 FALLO(S) de 5 pasos" in texto
    assert "✅ JOB DIARIO COMPLETADO" not in texto
    assert "✅ 3/5 transacciones_huerfanas OK" in texto


def test_run_monthly_cuenta_los_fallos_en_el_resumen(monkeypatch, caplog):
    for nombre, fn in (("maintenance.backup_neon", "ejecutar_backup"),
                       ("maintenance.verificar_integridad", "verificar"),
                       ("maintenance.marcar_plan_vencido", "marcar_vencidos"),
                       ("maintenance.transacciones_huerfanas", "limpiar_huerfanas"),
                       ("maintenance.cleanup_logs", "limpiar_logs"),
                       ("maintenance.health_check", "verificar_salud"),
                       ("maintenance.neon_usage_alerts", "verificar_uso"),
                       ("maintenance.reporte_estadisticas", "generar_reporte"),
                       ("maintenance.rotar_credenciales", "avisar_rotacion")):
        # Todos fallan salvo el reporte (None = OK): 8 fallos de 9.
        _modulo_falso(monkeypatch, nombre,
                      {fn: (lambda: None) if nombre.endswith("reporte_estadisticas")
                       else (lambda: False)})

    with caplog.at_level(logging.INFO):
        rm.run()

    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "❌ JOB MENSUAL TERMINADO CON 8 FALLO(S) de 9 pasos" in texto
    assert "✅✅✅ JOB MENSUAL COMPLETADO" not in texto
    assert "✅ 8/9 reporte_estadisticas OK" in texto
