"""Genera reporte mensual de estadísticas (log + JSON en backend/logs/reportes/)."""
import json
import logging
import os
from datetime import date, timedelta

os.environ.setdefault('ENVIRONMENT', 'test')

from sqlalchemy import text
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


def _obtener_reporte(db) -> dict:
    """Recolecta métricas del mes actual (y compara ingresos vs mes anterior)."""
    hoy = date.today()
    mes_inicio = hoy.replace(day=1)
    mes_anterior_inicio = (mes_inicio - timedelta(days=1)).replace(day=1)

    def scalar(q, **params):
        return db.execute(text(q), params).scalar() or 0

    total_alumnos = scalar(
        "SELECT COUNT(*) FROM usuarios WHERE rol = 'alumno'")
    alumnos_activos = scalar(
        "SELECT COUNT(*) FROM usuarios WHERE rol = 'alumno' AND activo = true")
    planes_activos = scalar(
        "SELECT COUNT(*) FROM suscripciones WHERE estado = 'activo'")
    planes_vencidos_mes = scalar(
        "SELECT COUNT(*) FROM suscripciones WHERE estado = 'vencido' AND updated_at >= :ini",
        ini=mes_inicio)
    nuevos_alumnos_mes = scalar(
        "SELECT COUNT(*) FROM usuarios WHERE rol = 'alumno' AND created_at >= :ini",
        ini=mes_inicio)
    ingresos_mes = float(scalar(
        "SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras "
        "WHERE tipo = 'ingreso' AND fecha >= :ini",
        ini=mes_inicio))
    ingresos_mes_anterior = float(scalar(
        "SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras "
        "WHERE tipo = 'ingreso' AND fecha >= :ini AND fecha < :fin",
        ini=mes_anterior_inicio, fin=mes_inicio))

    variacion = None
    if ingresos_mes_anterior:
        variacion = round(
            ((ingresos_mes - ingresos_mes_anterior) / ingresos_mes_anterior) * 100, 2)

    return {
        "fecha": hoy.isoformat(),
        "mes": mes_inicio.isoformat(),
        "total_alumnos": total_alumnos,
        "alumnos_activos": alumnos_activos,
        "planes_activos": planes_activos,
        "planes_vencidos_mes": planes_vencidos_mes,
        "nuevos_alumnos_mes": nuevos_alumnos_mes,
        "ingresos_mes": ingresos_mes,
        "ingresos_mes_anterior": ingresos_mes_anterior,
        "variacion_ingresos_pct": variacion,
    }


def generar_reporte():
    """Reporte mensual: alumnos, planes activos, ingresos, nuevos/vencidos."""

    db = SessionLocal()
    try:
        reporte = _obtener_reporte(db)

        logger.info(f"📊 REPORTE MENSUAL {reporte['mes']}")
        for clave, valor in reporte.items():
            logger.info(f"   {clave}: {valor}")

        # Guardar JSON en backend/logs/reportes/ (no se sube a git)
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'logs', 'reportes')
        os.makedirs(log_dir, exist_ok=True)
        archivo = os.path.join(
            log_dir, f"reporte_{reporte['mes'].replace('-', '')}.json")
        with open(archivo, 'w', encoding='utf-8') as f:
            json.dump(reporte, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Reporte guardado en {archivo}")
        return True
    except Exception as e:
        logger.error(f"❌ Error generar reporte: {e}")
        return False
    finally:
        db.close()
