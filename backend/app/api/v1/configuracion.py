"""
Router de Configuración del Negocio (datos bancarios por tenant)

    GET /api/v1/configuracion — autenticado: el box sale del TOKEN
    PUT /api/v1/configuracion — sólo admin del box

🔒 R1: el GET era PÚBLICO "por diseño" (SECURITY.md §3.2) porque lo consumen pantallas
de alumno, pero las TRES pantallas que lo usan (Configuración, Bazar y Solicitar plan)
están detrás del login y mandan el token. Público + `tenant_id` por query significaba
que cualquiera podía enumerar banco / cuenta / RUT / email / WhatsApp de TODOS los boxes
con `GET /configuracion?tenant_id=1..N` (200, sin credencial alguna). Ahora exige token,
toma el `tenant_id` del JWT (el query param se ignora) y tiene rate limit en GET y PUT.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
import re
from typing import Literal, Optional

from app.db.database import get_db
from app.models.configuracion import ConfiguracionNegocio
from app.models.usuario import Usuario
from app.core.dependencies import get_current_user, get_current_admin
from app.core.rate_limit import LIMIT_CONFIG_LECTURA, LIMIT_CRITICO, limiter
from app.services.auditoria_service import registrar_auditoria
from app.services.beneficios_service import TOPE_DESCUENTO_DEFAULT
from app.services.notificaciones_panel import notificar_admins_del_tenant
from app.utils.rut import normalizar_rut, validar_rut

router = APIRouter()

# Los campos que edita el admin: los que la auditoría compara antes/después (I1).
# `updated_at` / `updated_by` quedan afuera a propósito: son la marca de autoría, no
# un dato que el admin haya cambiado.
# `beneficio_descuento_max_pct` (M4) entra acá también: es el tope del descuento que un
# beneficio de Fidelización puede ofrecer y el cambio tiene que quedar auditado igual que
# los datos bancarios (un box podría subirlo a 100 y regalar todo el plan: eso se registra).
CAMPOS_EDITABLES = ("banco", "numero_cuenta", "tipo_cuenta", "rut",
                    "email_comprobantes", "whatsapp", "beneficio_descuento_max_pct")


class ConfiguracionUpdate(BaseModel):
    """Cuerpo del PUT /configuracion: los datos bancarios del box (los 6 que edita el admin).

    ⚠️ Antes eran 6 strings libres: sin largo máximo, sin formato, sin lista cerrada y sin
    validar el RUT. Lo que se guarda acá no es cosmético — el alumno lo LEE en la pantalla
    de transferencia (Bazar y Solicitar plan) y el WhatsApp sale en el pie de TODOS los
    correos del box. Un `numero_cuenta` con letras o un `tipo_cuenta` inventado son datos
    bancarios incorrectos que nadie valida después.

    Los `max_length` son los de las COLUMNAS de `ConfiguracionNegocio`: un valor que pasa
    por acá nunca puede reventar el INSERT por largo.

    `extra="forbid"`: una clave desconocida falla con 422 en vez de ignorarse en silencio.
    `""` en un campo de texto significa "sin dato" (NULL) — es el contrato del formulario;
    `model_fields_set` (abajo, en el endpoint) distingue "mandó vacío" de "no lo mandó".
    """
    banco: Optional[str] = Field(None, max_length=200)
    numero_cuenta: Optional[str] = Field(None, max_length=50)
    tipo_cuenta: Optional[Literal["Corriente", "Vista", "Rut", "Ahorro"]] = None
    rut: Optional[str] = Field(None, max_length=20)
    email_comprobantes: Optional[EmailStr] = Field(None, max_length=200)
    # Bloque C: el WhatsApp del box para el pie de los correos (vacío = sólo responder
    # el correo). El link lo arma `email_service.wa_link()` a partir de los dígitos.
    whatsapp: Optional[str] = Field(None, max_length=30)
    # M4: tope (%) del descuento que un beneficio de Fidelización puede ofrecer sobre el
    # "próximo plan". 0-100 (un descuento >100% sería regalar plata). Sólo admin y queda
    # auditado. `None` = no lo mandaron (se conserva lo guardado); si nunca se configuró,
    # el sistema usa TOPE_DESCUENTO_DEFAULT (50).
    beneficio_descuento_max_pct: Optional[int] = Field(
        None, ge=0, le=100,
        description="Tope del descuento (%) que un beneficio puede ofrecer (0-100)")

    model_config = ConfigDict(extra="forbid")

    @field_validator("banco", "numero_cuenta", "rut", "email_comprobantes",
                     "whatsapp", mode="before")
    @classmethod
    def _recortar(cls, valor):
        """Recorta el texto y convierte el campo vacío en `None` (no en `""`).

        Es lo que el formulario manda cuando el admin borra un dato: se guarda NULL, así
        el resto del sistema sólo tiene que chequear un caso (`if not valor`) y no dos.
        """
        if valor is None:
            return None
        limpio = str(valor).strip()
        return limpio or None

    @field_validator("numero_cuenta", mode="after")
    @classmethod
    def _cuenta_solo_digitos(cls, valor):
        """El número de cuenta son DÍGITOS (se toleran los separadores de la cartola).

        El box la escribe como la ve en el banco ("12.345.678-9", "0012 3456 7890"): se
        quitan puntos, guiones y espacios y se guarda sólo los dígitos, que es lo que el
        alumno copia para transferir. Cualquier letra (o un largo imposible) -> 422.
        """
        if valor is None:
            return None
        digitos = re.sub(r"[.\s-]", "", str(valor))
        if not re.fullmatch(r"\d{4,20}", digitos):
            raise ValueError(
                "La cuenta debe tener entre 4 y 20 dígitos (se aceptan puntos y guiones)")
        return digitos

    @field_validator("rut", mode="after")
    @classmethod
    def _rut_con_digito_verificador(cls, valor):
        """RUT del titular con dígito verificador real (módulo 11), no texto libre.

        Se guarda normalizado (`12345678-9`: sin puntos, DV en mayúscula), que es como lo
        compara el resto del sistema (`Usuario.rut` del alta de alumno).
        """
        if valor is None:
            return None
        rut = normalizar_rut(valor)
        if not validar_rut(rut):
            raise ValueError("RUT inválido: revisa el dígito verificador")
        return rut


@router.get("")
@limiter.limit(LIMIT_CONFIG_LECTURA)
def obtener_configuracion(
    request: Request,
    tenant_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Configuración del negocio del box del TOKEN (datos bancarios para transferencias).

    ⚠️ El `tenant_id` del query se IGNORA (queda declarado sólo por compatibilidad con
    los clientes que todavía lo mandan): pedir el box de otro devuelve el PROPIO —y, si
    ese box todavía no cargó nada, `configurado: False`—, así que no hay forma de
    enumerar la ficha bancaria de los demás boxes.
    """
    # 🔒 SEGURIDAD (R1): el box sale del token, nunca del request.
    tenant_id = current_user["tenant_id"]

    config = db.query(ConfiguracionNegocio).filter(
        ConfiguracionNegocio.tenant_id == tenant_id
    ).first()

    if not config:
        return {
            "tenant_id": tenant_id,
            "banco": None,
            "numero_cuenta": None,
            "tipo_cuenta": None,
            "rut": None,
            "email_comprobantes": None,
            "whatsapp": None,
            # M4: sin fila todavía, el tope efectivo es el default del diseño (50).
            "beneficio_descuento_max_pct": TOPE_DESCUENTO_DEFAULT,
            "configurado": False,
            "updated_at": None,
            "updated_by": None,
        }

    return {
        "id": config.id,
        "tenant_id": config.tenant_id,
        "banco": config.banco,
        "numero_cuenta": config.numero_cuenta,
        "tipo_cuenta": config.tipo_cuenta,
        "rut": config.rut,
        "email_comprobantes": config.email_comprobantes,
        "whatsapp": config.whatsapp,
        "beneficio_descuento_max_pct": (
            config.beneficio_descuento_max_pct
            if config.beneficio_descuento_max_pct is not None
            else TOPE_DESCUENTO_DEFAULT),
        "configurado": True,
        # I1: quién guardó la fila y cuándo (para que el admin note que otro la cambió).
        "updated_at": config.updated_at,
        "updated_by": config.updated_by,
    }


@router.put("")
@limiter.limit(LIMIT_CRITICO)
def actualizar_configuracion(
    request: Request,
    data: ConfiguracionUpdate,
    tenant_id: Optional[int] = None,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Actualiza o crea la configuracion del negocio. Solo admin (tenant del token).

    I1 — trazabilidad: el cambio queda en `auditoria` con los valores de antes y después,
    la fila guarda quién y cuándo la tocó (`updated_by` / `updated_at`) y los DEMÁS
    admins del box se enteran por la campana (`config_bancaria` → `/admin/configuracion`).
    El aviso llega a todos los admins activos, incluido el que guardó (el helper no
    excluye al autor): es el precio de no duplicar la consulta de destinatarios.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    # Buscar o crear configuracion
    config = db.query(ConfiguracionNegocio).filter(
        ConfiguracionNegocio.tenant_id == tenant_id
    ).first()

    if not config:
        config = ConfiguracionNegocio(tenant_id=tenant_id)
        db.add(config)

    # I1: foto ANTES de tocar nada (los campos del formulario, en el orden de CAMPOS_EDITABLES).
    antes = {campo: getattr(config, campo) for campo in CAMPOS_EDITABLES}

    # Se aplican SÓLO los campos que vinieron en el request (`model_fields_set`), no todos:
    #  - el formulario manda los 6, así que un campo borrado llega como `None` y BORRA el
    #    dato (antes `if data.banco is not None` hacía imposible vaciar banco/RUT/etc.);
    #  - un cliente que manda sólo un campo (como el test del WhatsApp) no toca el resto.
    enviados = data.model_fields_set
    for campo in CAMPOS_EDITABLES:
        if campo in enviados:
            setattr(config, campo, getattr(data, campo))

    # ── I1: cierre de la trazabilidad ────────────────────────────────────────
    despues = {campo: getattr(config, campo) for campo in CAMPOS_EDITABLES}
    config.updated_by = current_user["usuario_id"]

    # El cambio y su traza viajan en la MISMA transacción (registrar_auditoria commitea
    # las dos cosas): o queda todo —fila + auditoría— o no queda nada.
    db.flush()
    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="configuracion_negocio",
        entidad_id=config.id,
        detalle={"antes": antes, "despues": despues},
    )

    # Campana de los demás admins del box (best-effort: el helper filtra por
    # tenant + rol + estado='activo' y nunca tumba el guardado).
    # Sólo si algo cambió de verdad: re-guardar el mismo formulario no tiene que
    # ensuciar la campana con un aviso de "cambié algo" que no cambió.
    if antes != despues:
        notificar_admins_del_tenant(
            db, tenant_id, "config_bancaria",
            f"🏦 {current_user['nombre']} actualizó los datos bancarios del box")

    db.refresh(config)

    return {
        "id": config.id,
        "tenant_id": config.tenant_id,
        "banco": config.banco,
        "numero_cuenta": config.numero_cuenta,
        "tipo_cuenta": config.tipo_cuenta,
        "rut": config.rut,
        "email_comprobantes": config.email_comprobantes,
        "whatsapp": config.whatsapp,
        "beneficio_descuento_max_pct": (
            config.beneficio_descuento_max_pct
            if config.beneficio_descuento_max_pct is not None
            else TOPE_DESCUENTO_DEFAULT),
        "configurado": True,
        "updated_at": config.updated_at,
        "updated_by": config.updated_by,
    }
