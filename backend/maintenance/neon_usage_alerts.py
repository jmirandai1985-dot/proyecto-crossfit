"""Alertas de uso de Neon free tier.

Neon free tier: 3 GB de almacenamiento.
Se calcula el tamaño real con pg_database_size(current_database()).
"""
import logging

from sqlalchemy import text
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

NEON_FREE_TIER_GB = 3.0
UMBRAL_ALERTA_PCT = 90.0


def verificar_uso():
    """Estima uso de Neon (GB) y alerta si > 90% del free tier."""

    db = SessionLocal()
    try:
        size_bytes = db.execute(
            text("SELECT pg_database_size(current_database())")).scalar()
        if size_bytes is None:
            logger.warning("⚠️ No se pudo obtener el tamaño de la BD")
            return False

        size_mb = size_bytes / (1024 * 1024)
        pct = (size_bytes / (NEON_FREE_TIER_GB * 1024 ** 3)) * 100
        logger.info(
            f"Tamaño BD: {size_mb:.2f} MB "
            f"({pct:.2f}% del free tier de {NEON_FREE_TIER_GB:.1f} GB)")

        if pct >= UMBRAL_ALERTA_PCT:
            logger.warning(
                f"🚨 ALERTA: uso de Neon en {pct:.2f}% >= {UMBRAL_ALERTA_PCT:.0f}% "
                f"del free tier — considerar limpieza o upgrade")
        else:
            logger.info("✅ Uso de Neon dentro de límite free tier")

        # Contexto: tablas con más filas (aproximado por estadísticas)
        try:
            tablas = db.execute(text("""
                SELECT relname, n_live_tup
                FROM pg_stat_user_tables
                ORDER BY n_live_tup DESC
                LIMIT 8
            """)).fetchall()
            for t in tablas:
                logger.info(f"   {t[0]}: {t[1]} filas aprox.")
        except Exception:
            pass

        return True
    except Exception as e:
        logger.error(f"❌ Error verificar Neon: {e}")
        return False
    finally:
        db.close()
