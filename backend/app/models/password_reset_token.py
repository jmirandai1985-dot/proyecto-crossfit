"""Modelo SQLAlchemy para la tabla password_reset_tokens (flujo de recuperación)."""
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class PasswordResetToken(Base):
    """Token de restablecimiento de contraseña de un solo uso.

    Se guarda SOLO el hash sha256(token) — nunca el token en texto plano.
    Expiración corta (1h, expires_at); used_at marca el consumo único
    (token de un solo uso).
    """
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    def __repr__(self):
        return (f"<PasswordResetToken(id={self.id}, usuario_id={self.usuario_id}, "
                f"usado={self.used_at is not None})>")
