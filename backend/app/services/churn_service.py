"""Recalculo de la fila de churn de UN alumno, en segundo plano (sin bloquear la respuesta).

Por que existe
--------------
`predictions_churn` es un DATA MART: `POST /kpis/populate/predictions` lo reescribe COMPLETO en
cada corrida (cron). Hasta el proximo poblado, la fila de un alumno es la del dia del poblado:
si HOY aprueba un plan (o registra una asistencia, o cambia de creditos) su `riesgo` y su
`recomendacion` quedan viejos — la SITUACION ya se sirve en vivo (`plan_vencimiento`), pero el
riesgo/probabilidad/arquetipo siguen siendo del snapshot hasta el proximo cron. Este modulo
recalcula SOLO ese alumno y reemplaza sus filas por una fresca.

Reglas
------
  * Se dispara con `BackgroundTasks` (no bloquea) y abre su PROPIA sesion (`SessionLocal`): la
    del request ya cerro cuando el task corre.
  * La probabilidad/nivel reproducen EXACTAMENTE `populate_predictions` (heuristica):
    `probabilidad_heuristica` y `nivel_de_riesgo` viven aca y el populate las reusa. El `motivo`
    sale de `plan_vencimiento.motivo_situacion` y la recomendacion de `_recomendacion_churn` (la
    MISMA del populate, importada de forma perezosa para no crear un ciclo de imports).
  * Un fallo NUNCA debe tumbar la operacion que lo disparo: se loguea y se descarta.
"""
import logging
from datetime import timedelta

from sqlalchemy import func

from app.db.database import SessionLocal
from app.models.asistencia import Asistencia
from app.models.predictions_churn import PredictionsChurn
from app.models.usuario import Usuario
from app.services import plan_vencimiento
from app.utils.santiago import fecha_chile, hoy_santiago

logger = logging.getLogger("uvicorn")


def probabilidad_heuristica(dias_inactivo: int, dias_para_vencer) -> float:
    """Probabilidad (0-100) de la heuristica: inactividad + ausencia/vencimiento del plan."""
    prob = min(dias_inactivo, 60) / 60 * 70
    if dias_para_vencer is None:
        prob += 20
    elif dias_para_vencer <= plan_vencimiento.DIAS_PLAN_POR_VENCER:
        prob += 10
    return round(min(prob, 100), 2)


def nivel_de_riesgo(prob: float) -> str:
    """CRITICO/ALTO/MEDIO/BAJO: los MISMOS umbrales en el populate y en el recalculo."""
    if prob >= 70:
        return "CRITICO"
    if prob >= 50:
        return "ALTO"
    if prob >= 30:
        return "MEDIO"
    return "BAJO"


def _dias_inactividad(db, tenant_id, usuario_id, created_at, hoy) -> int:
    """Dias desde la ultima asistencia y, si nunca asistio, desde el alta (COALESCE)."""
    ultima = db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
    ).scalar()
    referencia = ultima or (created_at.date() if created_at else None)
    if referencia is None:
        return 0
    return max(0, (hoy - referencia).days)


def _conteos(db, tenant_id, usuario_id, dias, hoy) -> int:
    """Asistencias del alumno en la ventana [hoy - dias, hoy]."""
    return db.query(func.count(Asistencia.id)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
        Asistencia.fecha >= hoy - timedelta(days=dias),
        Asistencia.fecha <= hoy,
    ).scalar() or 0


def recalcular_alumno(tenant_id: int, usuario_id: int) -> None:
    """Recalcula la fila de churn de UN alumno (sesion propia; nunca lanza)."""
    db = SessionLocal()
    try:
        alumno = db.query(Usuario).filter(
            Usuario.id == usuario_id, Usuario.tenant_id == tenant_id).first()
        if alumno is None:
            return
        # Import PEREZOSO: `_recomendacion_churn` es la MISMA regla del populate (evita un ciclo
        # de imports, porque el populate importa este modulo a nivel de modulo).
        from app.api.v1.kpis_populate import _recomendacion_churn

        hoy = hoy_santiago()
        dias_inactivo = _dias_inactividad(db, tenant_id, usuario_id, alumno.created_at, hoy)
        fila_plan = plan_vencimiento.suscripcion_vigente(db, alumno, hoy, solo_comercial=True)
        proxima = fila_plan[0].fecha_expiracion if fila_plan else None
        proxima_date = fecha_chile(proxima) if proxima else None
        dias_para_vencer = plan_vencimiento.dias_hasta(proxima, hoy)
        asis_30 = _conteos(db, tenant_id, usuario_id, 30, hoy)
        asis_90 = _conteos(db, tenant_id, usuario_id, 90, hoy)

        prob = probabilidad_heuristica(dias_inactivo, dias_para_vencer)
        nivel = nivel_de_riesgo(prob)
        motivo = plan_vencimiento.motivo_situacion(dias_inactivo, dias_para_vencer)
        recomendacion, reco_codigo = _recomendacion_churn(
            nivel, dias_para_vencer is not None, dias_para_vencer, asis_30, asis_90)

        # Reemplaza las filas del alumno (el data mart guarda UNA fila por alumno tras el refresh).
        db.query(PredictionsChurn).filter(
            PredictionsChurn.tenant_id == tenant_id,
            PredictionsChurn.usuario_id == usuario_id,
        ).delete()
        db.add(PredictionsChurn(
            tenant_id=tenant_id, usuario_id=usuario_id,
            probabilidad_churn=prob, riesgo_nivel=nivel, motivo=motivo,
            recomendacion=recomendacion, recomendacion_codigo=reco_codigo,
            fecha_proxima_renovacion=proxima_date,
        ))
        db.commit()
    except Exception as e:   # nunca romper la operacion que lo disparo
        db.rollback()
        logger.warning("recalculo de churn del alumno #%s fallo: %s", usuario_id, e)
    finally:
        db.close()


def programar_recalculo(background_tasks, tenant_id: int, usuario_id: int) -> None:
    """Encola el recalculo en segundo plano (no bloquea). Sin `background_tasks`, no hace nada."""
    if background_tasks is None or usuario_id is None:
        return
    background_tasks.add_task(recalcular_alumno, tenant_id, usuario_id)
