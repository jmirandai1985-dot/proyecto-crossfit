"""Modelo SQLAlchemy para la tabla tokens_migracion_boxmagic (envío masivo)."""
from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class TokenMigracionBoxmagic(Base):
    """Token de un solo uso para activar la cuenta de un candidato del padrón.

    Mismo patrón que `PasswordResetToken` (auth): se guarda SOLO el hash sha256 del
    token —nunca el valor en claro—, con `expires_at` y `used_at` para el uso único.
    Cuelga de `candidato_id` y no de `usuario_id` porque el candidato todavía NO tiene
    cuenta en el SaaS: la cuenta nace recién cuando usa este link.

    El token viaja en el link del correo de activación
    (`/migracion/activar?token=...`); el panel de activación sólo guarda el hash, así
    que quien lea la tabla no puede reconstruir el link.
    """
    __tablename__ = "tokens_migracion_boxmagic"

    id = Column(Integer, primary_key=True)
    candidato_id = Column(Integer, ForeignKey(
        "candidatos_boxmagic.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        # El envío masivo consulta por candidato si ya tiene un token vigente.
        Index("ix_tokens_migracion_boxmagic_candidato_id", "candidato_id"),
    )

    def __repr__(self):
        return (f"<TokenMigracionBoxmagic(id={self.id}, "
                f"candidato_id={self.candidato_id}, "
                f"usado={self.used_at is not None})>")
