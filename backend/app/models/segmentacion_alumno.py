"""Modelo SQLAlchemy para la tabla `segmentacion_alumnos` (arquetipos de retención).

Es un artefacto DERIVADO del modelo K-Means (K=5, 5 features, migración 026):
se reescribe COMPLETO en cada reentrenamiento (full refresh DELETE + INSERT por
tenant, igual que `predictions_churn`). El estimador vive en `ml_modelos`
(`tipo_modelo='segmentacion'`).

⚠️ NO confundir con las otras dos tablas "parecidas":
  - `student_segments` (migración 021): nivel de ATLETA
    (BASICO|INTERMEDIO|AVANZADO + fuerza/gimnástica/asistencia/retention).
  - `retencion_alumnos`: seguimiento MANUAL (coach_id, notas, proxima_renovacion).

Los 6 valores posibles de `arquetipo` (escalera de retención, definida en
`ml/segmentacion.py::ARQUETIPOS` + `etiquetar_cluster`): ABANDONADO_PERDIDO,
ABANDONADO_RECUPERABLE, EN_RIESGO, NUEVO, ACTIVO_EN_DECLIVE, ACTIVO_FIEL.
Se validan en Python (sin CHECK en la BD), mismo criterio que `TIPOS_MODELO`.
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class SegmentacionAlumno(Base):
    __tablename__ = "segmentacion_alumnos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # 0..K-1 (id crudo de KMeans.labels_).
    cluster_id = Column(Integer, nullable=False)
    # Uno de los 6 tramos de la escalera (ver docstring del módulo).
    arquetipo = Column(String(30), nullable=False, default="ACTIVO_FIEL")
    # Perfil que explica la asignación: {"modelo": {...}, "cluster": {...},
    # "alumno": {<5 features>}}. Nullable a propósito: la etiqueta NO depende
    # del perfil -> un fallo al serializar no debe tumbar el refresh.
    perfil_json = Column(Text, nullable=True)
    # `fecha_entrenamiento` del modelo que generó la fila.
    modelo_fecha = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        # Una sola fila vigente por alumno (a diferencia de predictions_churn).
        Index("uq_segmentacion_alumnos_tenant_usuario", "tenant_id",
              "usuario_id", unique=True),
        Index("ix_segmentacion_alumnos_tenant_id", "tenant_id"),
        Index("ix_segmentacion_alumnos_usuario_id", "usuario_id"),
        Index("ix_segmentacion_alumnos_tenant_arquetipo", "tenant_id",
              "arquetipo"),
    )

    def __repr__(self):
        return (f"<SegmentacionAlumno(usuario_id={self.usuario_id}, "
                f"arquetipo='{self.arquetipo}')>")
