"""Modelo SQLAlchemy para la tabla `ml_modelos` (modelos de ML en la BD).

Los modelos entrenados (churn / forecast) se persisten como pickle en la BD en
vez de archivos .pkl en disco: el filesystem de Render es efímero y los
artefactos se perderían en cada reinicio/redeploy.

Índice ÚNICO (tenant_id, tipo_modelo) -> siempre hay UN solo modelo vigente por
tipo; el guardado es un UPSERT (ON CONFLICT DO UPDATE).
"""
from sqlalchemy import (
    Column, Integer, String, Text, LargeBinary, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base

# Tipos de modelo soportados (coinciden con el CHECK implícito del endpoint).
TIPOS_MODELO = ("churn", "forecast")


class MlModelo(Base):
    """Un modelo de ML serializado (pickle) por tenant y tipo."""

    __tablename__ = "ml_modelos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    # 'churn' | 'forecast'
    tipo_modelo = Column(String(20), nullable=False)
    # pickle del estimador de scikit-learn (pickle.dumps)
    modelo_binario = Column(LargeBinary, nullable=False)
    # mismo JSON que antes se escribía en *_meta.json
    metadata_json = Column(Text, nullable=True)
    fecha_entrenamiento = Column(TIMESTAMP(timezone=True),
                                 nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ux_ml_modelos_tenant_tipo", "tenant_id", "tipo_modelo",
              unique=True),
    )

    def __repr__(self):
        return (f"<MlModelo(tenant_id={self.tenant_id}, "
                f"tipo='{self.tipo_modelo}')>")
