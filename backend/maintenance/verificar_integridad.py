"""Verifica integridad de datos: RUT/correos únicos, FKs válidas y fechas válidas."""
import logging

from sqlalchemy import text
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


def verificar():
    """Chequea: RUT únicos, correos únicos, FKs válidos, fechas válidas."""

    db = SessionLocal()
    try:
        issues = []

        # 1. RUT duplicados (tabla real: usuarios)
        dup_ruts = db.execute(text(
            "SELECT rut, COUNT(*) AS cnt FROM usuarios "
            "GROUP BY rut HAVING COUNT(*) > 1"
        )).fetchall()
        if dup_ruts:
            issues.append(
                f"⚠️ RUT duplicados ({len(dup_ruts)}): "
                f"{[(r[0], r[1]) for r in dup_ruts[:10]]}")

        # 2. Correos duplicados
        dup_correos = db.execute(text(
            "SELECT correo, COUNT(*) AS cnt FROM usuarios "
            "GROUP BY correo HAVING COUNT(*) > 1"
        )).fetchall()
        if dup_correos:
            issues.append(
                f"⚠️ Correos duplicados ({len(dup_correos)}): "
                f"{[(c[0], c[1]) for c in dup_correos[:10]]}")

        # 3. FKs rotas: suscripciones con usuario inexistente
        subs_sin_usuario = db.execute(text(
            "SELECT COUNT(*) FROM suscripciones s "
            "LEFT JOIN usuarios u ON u.id = s.usuario_id "
            "WHERE u.id IS NULL"
        )).scalar()
        if subs_sin_usuario:
            issues.append(f"⚠️ Suscripciones con usuario inexistente: {subs_sin_usuario}")

        # 4. Suscripciones con plan inexistente
        subs_sin_plan = db.execute(text(
            "SELECT COUNT(*) FROM suscripciones s "
            "LEFT JOIN planes p ON p.id = s.plan_id "
            "WHERE p.id IS NULL"
        )).scalar()
        if subs_sin_plan:
            issues.append(f"⚠️ Suscripciones con plan inexistente: {subs_sin_plan}")

        # 5. Fechas inválidas: expiración anterior al inicio
        fechas_invalidas = db.execute(text(
            "SELECT COUNT(*) FROM suscripciones "
            "WHERE fecha_expiracion < fecha_inicio"
        )).scalar()
        if fechas_invalidas:
            issues.append(
                f"⚠️ Suscripciones con expiración anterior al inicio: {fechas_invalidas}")

        if issues:
            for issue in issues:
                logger.warning(issue)
            logger.warning(f"Integridad: {len(issues)} problema(s) detectado(s)")
            return False
        else:
            logger.info("✅ Integridad OK")
            return True
    except Exception as e:
        logger.error(f"❌ Error verificar integridad: {e}")
        return False
    finally:
        db.close()
