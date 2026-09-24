"""
P0-1 (auditoría panel Alumno) — regresión de `maintenance/marcar_plan_vencido.py`.

BUG ORIGINAL (reproducido en TEST el 2026-09-24):
  el job hacía `usuario.activo = False` **sin** tocar `usuarios.estado`. Con el
  CHECK `ck_usuarios_activo_estado` de la migración 034
  (`activo = (estado = 'activo')`) ese UPDATE viola la restricción → el `except`
  del job lo capturaba y solo lo logueaba → el job devolvía `False` y **ninguna**
  suscripción vencida se marcaba (38 pendientes en TEST/PROD).

Qué verifica este test (corre el job REAL contra la BD de TEST):
  1. `marcar_vencidos()` devuelve True (no explota por el CHECK).
  2. No quedan usuarios con `activo`/`estado` desincronizados.
  3. El job NO desactiva a nadie (si lo hiciera, el alumno no podría loguearse
     a renovar su plan: `get_current_user` exige `estado='activo'`).
  4. No quedan suscripciones vencidas (`fecha_expiracion` anterior a hoy) en
     estado 'activo'.

Requiere ENVIRONMENT=test (lo setea `_run_tests_orchestrator.py`); se saltea si
no, para no tocar una base real.
"""
import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("ENVIRONMENT") != "test",
    reason="Solo con ENVIRONMENT=test (el test ejecuta el job, que escribe)",
)


def _count(db, sql, **params):
    return db.execute(text(sql), params).scalar()


def test_p01_marcar_vencidos_no_rompe_el_check_de_estado():
    from app.db.database import SessionLocal
    from maintenance.marcar_plan_vencido import marcar_vencidos

    db = SessionLocal()
    try:
        # Estado ANTES de correr el job (para probar que no desactiva a nadie)
        usuarios_inactivos_antes = _count(db, "SELECT count(*) FROM usuarios WHERE activo = false")
        conflictos_antes = _count(
            db, "SELECT count(*) FROM usuarios WHERE activo IS DISTINCT FROM (estado = 'activo')")
        assert conflictos_antes == 0, "precondición: la BD de TEST ya tenía activo/estado desincronizados"
    finally:
        db.close()

    # 1) El job corre y devuelve True (el bug original devolvía False)
    assert marcar_vencidos() is True, (
        "marcar_vencidos() devolvió False: volvió el CheckViolation del CHECK "
        "ck_usuarios_activo_estado (¿se volvió a tocar usuarios.activo sin estado?)")

    db = SessionLocal()
    try:
        # 2) Invariante de la 034 intacto
        conflictos = _count(
            db, "SELECT count(*) FROM usuarios WHERE activo IS DISTINCT FROM (estado = 'activo')")
        assert conflictos == 0, f"{conflictos} usuarios con activo/estado desincronizados"

        # 3) El job NO cambia el ciclo de vida de los usuarios
        usuarios_inactivos_despues = _count(
            db, "SELECT count(*) FROM usuarios WHERE activo = false")
        assert usuarios_inactivos_despues == usuarios_inactivos_antes, (
            "marcar_vencidos() desactivó usuarios: les bloquea el login "
            "(para renovar tienen que poder entrar)")

        # 4) No quedan suscripciones vencidas sin marcar
        pendientes = _count(
            db,
            "SELECT count(*) FROM suscripciones "
            "WHERE estado = 'activo' AND fecha_expiracion::date < CURRENT_DATE")
        assert pendientes == 0, f"{pendientes} suscripciones vencidas siguen en estado 'activo'"
    finally:
        db.close()
