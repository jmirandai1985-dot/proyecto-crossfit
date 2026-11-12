"""
Modelo SQLAlchemy para la tabla candidatos_boxmagic
"""
from typing import Final

from sqlalchemy import (
    Column, ForeignKey, Index, Integer, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base

# ── Estados crudos del Excel de BoxMagic (columna `Estado`) ─────────────────
# Son los 5 valores que trae el archivo real (712 filas, 2026-11-05). Se guardan tal
# como vienen: el panel no los reinterpreta, y el día de la migración real sirven para
# saber quién estaba congelado, quién era de prueba, etc.
ESTADO_BOXMAGIC_ACTIVO: Final[str] = "Activo"
ESTADO_BOXMAGIC_INACTIVO: Final[str] = "Inactivo"
ESTADO_BOXMAGIC_CONGELADO: Final[str] = "Congelado"
ESTADO_BOXMAGIC_NUEVO: Final[str] = "Nuevo"
ESTADO_BOXMAGIC_PRUEBA: Final[str] = "Prueba"

ESTADOS_BOXMAGIC: Final[tuple] = (
    ESTADO_BOXMAGIC_ACTIVO,
    ESTADO_BOXMAGIC_INACTIVO,
    ESTADO_BOXMAGIC_CONGELADO,
    ESTADO_BOXMAGIC_NUEVO,
    ESTADO_BOXMAGIC_PRUEBA,
)

# ── Grupos del padrón (lo que separa los dos paneles) ───────────────────────
#   'activacion'   -> hay que invitarlo / activarlo (NO está Inactivo)
#   'recuperacion' -> dejó de venir (está Inactivo): hay que traerlo de vuelta
GRUPO_ACTIVACION: Final[str] = "activacion"
GRUPO_RECUPERACION: Final[str] = "recuperacion"
GRUPOS_CANDIDATO: Final[tuple] = (GRUPO_ACTIVACION, GRUPO_RECUPERACION)


def normalizar_correo(valor) -> str:
    """Correo canónico del padrón: sin espacios alrededor y en MINÚSCULAS.

    El Excel real trae mayúsculas mezcladas (31 de 712 filas) y el SaaS guarda el
    correo como lo escribió cada alumno, así que el único cruce fiable entre
    `candidatos_boxmagic` y `usuarios` es comparando los dos lados normalizados.
    Acá se normaliza el lado del padrón (al importar y al leer), y el lado de
    `usuarios` se normaliza en el JOIN con `lower(trim(correo))`.
    """
    return str(valor or "").strip().lower()


def estado_canonico(estado) -> str:
    """Estado del Excel con la grafía canónica de `ESTADOS_BOXMAGIC`.

    Compara sin distinguir mayúsculas, así 'activo', 'ACTIVO' y 'Activo' son el mismo
    estado. Un estado que no está en la lista se devuelve tal como viene (recortado):
    preferimos ver 'Suspendido' en el panel antes que perder la fila o inventar un
    estado que BoxMagic no tiene (el importador los reporta para revisarlos a mano).
    """
    limpio = str(estado or "").strip()
    if not limpio:
        return ""
    for canonico in ESTADOS_BOXMAGIC:
        if limpio.lower() == canonico.lower():
            return canonico
    return limpio


def grupo_desde_estado(estado_boxmagic) -> str:
    """Grupo del padrón derivado del estado de BoxMagic.

    La ÚNICA regla: `Inactivo` -> 'recuperacion' (dejó de venir); cualquier otro
    estado (Activo, Congelado, Nuevo, Prueba) -> 'activacion' (hay que invitarlo).
    Congelado cuenta como activación a propósito: no es alguien que "se fue", es
    alguien que hay que reactivar cuando corresponda.
    """
    if str(estado_boxmagic or "").strip().lower() == ESTADO_BOXMAGIC_INACTIVO.lower():
        return GRUPO_RECUPERACION
    return GRUPO_ACTIVACION


class CandidatoBoxmagic(Base):
    """Un alumno del padrón de BoxMagic, ANTES de tener cuenta en el SaaS.

    POR QUÉ EXISTE: los paneles de la migración tienen que mostrar a los 712 alumnos
    reales desde ya, pero crear 712 `Usuario` de verdad (con acceso al sistema) es un
    paso POSTERIOR y aparte, que se hace el día de la migración. Esta fila es el padrón:
    nombre + correo + estado de BoxMagic, nada más. Los datos sensibles del Excel
    (RUT, fecha de nacimiento, dirección, teléfonos...) NO se copian acá: los completa
    el alumno en su propio formulario cuando migre.

    El vínculo con la cuenta real es POR CORREO (LEFT JOIN en el endpoint), no una FK:
    la mayoría de los candidatos todavía no tiene `usuarios` y el panel tiene que
    mostrarlos igual (en la etapa `sin_invitar` / estado `sin_contactar`).
    """

    __tablename__ = "candidatos_boxmagic"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(150), nullable=False)
    # Normalizado con `normalizar_correo()`: sin espacios y en minúsculas.
    correo = Column(String(150), nullable=False)
    # 'Activo' | 'Inactivo' | 'Congelado' | 'Nuevo' | 'Prueba' (ver ESTADOS_BOXMAGIC).
    estado_boxmagic = Column(String(20), nullable=False)
    # 'activacion' | 'recuperacion' (ver `grupo_desde_estado`).
    grupo = Column(String(20), nullable=False)
    cargado_en = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        # El UPSERT del importador se apoya en esta clave: un correo no se repite dos
        # veces en el padrón del mismo box. Mismo nombre que en la migración 079 para
        # que el `create_all()` de TEST arme exactamente el mismo esquema.
        UniqueConstraint("tenant_id", "correo",
                         name="uq_candidatos_boxmagic_tenant_correo"),
        Index("ix_candidatos_boxmagic_tenant_id", "tenant_id"),
        Index("ix_candidatos_boxmagic_tenant_grupo", "tenant_id", "grupo"),
    )

    def __repr__(self):
        return (f"<CandidatoBoxmagic(id={self.id}, tenant_id={self.tenant_id}, "
                f"correo='{self.correo}', estado='{self.estado_boxmagic}', "
                f"grupo='{self.grupo}')>")
