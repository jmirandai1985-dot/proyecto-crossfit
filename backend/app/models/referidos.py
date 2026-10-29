"""
Modelos SQLAlchemy del Sistema de Referidos + Invitación por correo.

Fase 1 declaró el ESQUEMA; las fases siguientes agregaron la generación de
códigos (2), los endpoints de consulta/validación/configuración (3a) y los
descuentos reales al confirmarse una compra (3b): `CreditoReferido` es el
beneficio pendiente del invitador para SU próxima compra.

Dos funciones comparten estas tablas:
  1. Invitación por correo (admin/coach → prospecto): marketing puro, sin premio.
     El prospecto completa el auto-registro existente (`invitaciones.estado`
     pasa a `registrado` y se guarda `usuario_registrado_id`).
  2. Programa de Referidos (alumno → alumno): cada alumno nuevo recibe un
     `codigo_referido`; el invitado lo ingresa al registrarse o al comprar y la
     fila queda `pendiente` hasta que compra su primer plan (`convertido`).

Los tipos nativos se llaman igual que en `SQLEnum(..., name=...)` y que en la
migración 051 (`alembic/versions/051_referidos_invitaciones.py`): un estado
nuevo exige migración, no entra como texto libre (mismo criterio que
`estado_suscripcion`, 023, y `estado_beneficio`, 038).
"""
import enum

from sqlalchemy import (Boolean, CheckConstraint, Column, Date, ForeignKey,
                        Index, Integer, Numeric, String, UniqueConstraint,
                        Enum as SQLEnum)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


# ── Enums del programa ───────────────────────────────────────────────────────

class OrigenInvitacion(str, enum.Enum):
    """Quién disparó la invitación por correo.

    `alumno` (migración 054) es la invitación alumno → alumno: lleva el código
    del invitador y un token de rastreo, y es la única que da premio.
    """
    admin = "admin"
    coach = "coach"
    alumno = "alumno"


class EstadoInvitacion(str, enum.Enum):
    """Ciclo de vida de una invitación.

    `enviada` → `registrado` cuando el prospecto completa el auto-registro; o
    → `expirada` si vence sin registrarse (la expiración es Fase 2).
    """
    enviada = "enviada"
    registrado = "registrado"
    expirada = "expirada"


class EstadoReferido(str, enum.Enum):
    """Una aplicación de código nace `pendiente` y pasa a `convertido` cuando
    el invitado compra su primer plan (la detección es Fase 2)."""
    pendiente = "pendiente"
    convertido = "convertido"


class EstadoCreditoReferido(str, enum.Enum):
    """Ciclo de vida del crédito que gana el INVITADOR al convertirse un referido.

    Nace `pendiente` (vale para su próxima compra de plan) y pasa a `usado` la
    única vez que se aplica. No hay vencimiento: el premio se gana y se conserva
    hasta que el invitador vuelva a comprar.
    """
    pendiente = "pendiente"
    usado = "usado"


class PeriodoPromocion(str, enum.Enum):
    """Ventana de conteo de las promociones por volumen. Por ahora sólo mensual;
    el enum deja el punto de extensión para semanal/trimestral."""
    mensual = "mensual"


class TipoPremio(str, enum.Enum):
    """Premio que otorga una promoción al cumplir el umbral.

    `mes_gratis` y `dias_gratis` usan `valor_premio` como días cuando aplica;
    `descuento_extra` lo usa como porcentaje (las reglas son Fase 2/3).
    """
    mes_gratis = "mes_gratis"
    descuento_extra = "descuento_extra"
    dias_gratis = "dias_gratis"


class EstadoPromocionDetectada(str, enum.Enum):
    """Flujo de confirmación del admin sobre un umbral detectado.

    La detección deja la fila `pendiente_confirmacion` (y alimenta la
    notificación al admin, mismo patrón que `notificaciones_enviadas`); el
    admin la resuelve a `confirmado` o `rechazado`.
    """
    pendiente_confirmacion = "pendiente_confirmacion"
    confirmado = "confirmado"
    rechazado = "rechazado"


class MotorPremios(str, enum.Enum):
    """Qué motor evalúa los premios del INVITADOR en el box (migración 064).

    `promociones` = Fase 5, umbral por MES CALENDARIO y umbrales acumulables.
    `tramos`      = escalera por CICLO de facturación, un solo premio (el más
                    alto alcanzado).

    Los dos motores NO conviven: si evaluaran a la vez, un alumno con 3
    referidos cobraría el premio de la promoción **y** el del tramo. El job de
    cada motor se salta el box cuyo flag no le corresponde.
    """
    promociones = "promociones"
    tramos = "tramos"



# ── 1. Invitaciones por correo (admin/coach → prospecto) ─────────────────────

class Invitacion(Base):
    """Una invitación enviada a un correo que todavía no es alumno.

    Dos orígenes comparten la tabla:

      * `admin` / `coach` → marketing puro, sin premio. Reutiliza el flujo de
        auto-registro (cuenta + clase de prueba + contraseña) y no lleva código.
      * `alumno` (migración 054) → invitación de un alumno a un amigo. Guarda el
        código del invitador (`codigo_referido_id`) y un `token_rastreo` que
        viaja en el link `/landing?inv=<token>`. Al completarse el registro la
        fila queda `registrado` y ligada a `usuario_registrado_id`, que es lo que
        permite prellenar el código en la compra (`GET /referidos/mi-invitacion`).

    El `token_rastreo` se guarda EN CLARO a propósito: no es una credencial (no
    autentica ni autoriza, sólo identifica el link) y así el alumno puede
    reenviar el MISMO enlace sin regenerarlo.
    """
    __tablename__ = "invitaciones"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    origen = Column(SQLEnum(OrigenInvitacion, name="origen_invitacion"),
                    nullable=False)
    # Quién la disparó. NULL-able con SET NULL para conservar la invitación si
    # se elimina la cuenta (mismo criterio que `avisos_marketing.creado_por`).
    enviado_por_usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    correo_prospecto = Column(String(150), nullable=False)
    estado = Column(SQLEnum(EstadoInvitacion, name="estado_invitacion"),
                    nullable=False, server_default="enviada",
                    default=EstadoInvitacion.enviada)
    fecha_envio = Column(TIMESTAMP(timezone=True), nullable=False,
                         server_default=func.now())
    # Se llena cuando el prospecto completa el auto-registro.
    fecha_registro = Column(TIMESTAMP(timezone=True), nullable=True)
    usuario_registrado_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    # El código del alumno que invita (NULL en admin/coach: no dan premio).
    # SET NULL conserva la traza de la invitación si se borra el código.
    codigo_referido_id = Column(Integer, ForeignKey(
        "codigos_referido.id", ondelete="SET NULL"), nullable=True)
    # Token opaco del link `/landing?inv=<token>`. Único (varios NULL están
    # permitidos en PostgreSQL, así que admin/coach conviven sin token).
    token_rastreo = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("token_rastreo",
                         name="uq_invitaciones_token_rastreo"),
        Index("ix_invitaciones_tenant_id", "tenant_id"),
        # Buscar/duplicar invitaciones de un correo dentro del box.
        Index("ix_invitaciones_tenant_correo", "tenant_id", "correo_prospecto"),
        Index("ix_invitaciones_estado", "estado"),
        # "La invitación que trajo a este alumno" (prellenado del código).
        Index("ix_invitaciones_usuario_registrado_id",
              "usuario_registrado_id"),
    )

    def __repr__(self):
        return (f"<Invitacion(id={self.id}, correo='{self.correo_prospecto}', "
                f"origen='{self.origen}', estado='{self.estado}', "
                f"token='{self.token_rastreo}')>")


# ── 2. Código de referido (uno por alumno) ───────────────────────────────────

class CodigoReferido(Base):
    """El código personal de un alumno para invitar a otro.

    Formato (lo genera la Fase 2, no este esquema): 1 inicial del nombre +
    primeras 5 letras del apellido + 3 dígitos, en mayúsculas y sin tildes ni
    espacios (ej. "Juan Pérez" → `JPERE234`). `codigo` y `usuario_id` son únicos:
    un alumno tiene un solo código y un código no se repite entre alumnos.

    ⚠️ Sin backfill: sólo se asigna a alumnos creados desde la Fase 2 en
    adelante (hook del alta admin y del auto-registro). Los alumnos históricos
    quedan sin fila.
    """
    __tablename__ = "codigos_referido"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    codigo = Column(String(20), nullable=False)
    fecha_creacion = Column(TIMESTAMP(timezone=True), nullable=False,
                            server_default=func.now())
    # `activo=False` retira el código sin borrar el historial de referidos.
    activo = Column(Boolean, nullable=False, server_default="true",
                    default=True)

    __table_args__ = (
        UniqueConstraint("usuario_id", name="uq_codigos_referido_usuario_id"),
        UniqueConstraint("codigo", name="uq_codigos_referido_codigo"),
    )

    def __repr__(self):
        return (f"<CodigoReferido(id={self.id}, usuario_id={self.usuario_id}, "
                f"codigo='{self.codigo}', activo={self.activo})>")


# ── 3. Referidos aplicados (alumno → alumno) ─────────────────────────────────

class ReferidoAplicado(Base):
    """La aplicación de un código por parte de un alumno invitado.

    `fecha_ingreso_codigo` se registra al ingresar el código (en el registro o
    al comprar) y la fila queda `pendiente`; al comprar el primer plan PAGADO
    pasa a `convertido` y se llena `fecha_conversion`. Los descuentos se guardan
    como snapshot en CLP de lo efectivamente aplicado a cada lado
    (`descuento_aplicado_invitado` al confirmarse la compra del invitado;
    `descuento_aplicado_invitador` al consumirse el crédito en la compra
    siguiente del invitador). NULL = todavía no se aplicó / no aplica.
    """
    __tablename__ = "referidos_aplicados"

    id = Column(Integer, primary_key=True)
    codigo_referido_id = Column(Integer, ForeignKey(
        "codigos_referido.id", ondelete="CASCADE"), nullable=False)
    usuario_invitador_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    usuario_invitado_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    fecha_ingreso_codigo = Column(TIMESTAMP(timezone=True), nullable=False,
                                  server_default=func.now())
    estado = Column(SQLEnum(EstadoReferido, name="estado_referido"),
                    nullable=False, server_default="pendiente",
                    default=EstadoReferido.pendiente)
    fecha_conversion = Column(TIMESTAMP(timezone=True), nullable=True)
    descuento_aplicado_invitado = Column(Numeric(10, 2), nullable=True)
    descuento_aplicado_invitador = Column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        # Anti-auto-referido: un alumno no puede usar su propio código.
        CheckConstraint(
            "usuario_invitador_id <> usuario_invitado_id",
            name="ck_referidos_aplicados_no_auto_referido"),
        Index("ix_referidos_aplicados_codigo_referido_id", "codigo_referido_id"),
        Index("ix_referidos_aplicados_usuario_invitador_id",
              "usuario_invitador_id"),
        Index("ix_referidos_aplicados_usuario_invitado_id",
              "usuario_invitado_id"),
        Index("ix_referidos_aplicados_estado", "estado"),
    )

    def __repr__(self):
        return (f"<ReferidoAplicado(id={self.id}, "
                f"invitador={self.usuario_invitador_id}, "
                f"invitado={self.usuario_invitado_id}, "
                f"estado='{self.estado}')>")


# ── 4. Configuración de descuentos por box ───────────────────────────────────

class ConfiguracionReferidos(Base):
    """Porcentajes de descuento que el admin configura para su box.

    Una fila por tenant (UNIQUE `tenant_id`). Los porcentajes son 0..100;
    `activo=False` apaga el programa sin borrar la configuración.
    """
    __tablename__ = "configuracion_referidos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    porcentaje_descuento_invitado = Column(
        Numeric(5, 2), nullable=False, server_default="0", default=0)
    porcentaje_descuento_invitador = Column(
        Numeric(5, 2), nullable=False, server_default="0", default=0)
    activo = Column(Boolean, nullable=False, server_default="true",
                    default=True)
    # Qué motor paga los premios del invitador (migración 064). Default
    # `promociones` para que el deploy NO cambie el comportamiento del box:
    # el administrador cambia a `tramos` cuando su escalera está cargada.
    motor_premios = Column(String(20), nullable=False,
                           server_default=MotorPremios.promociones.value,
                           default=MotorPremios.promociones.value)

    __table_args__ = (
        UniqueConstraint("tenant_id",
                         name="uq_configuracion_referidos_tenant_id"),
        CheckConstraint(
            "porcentaje_descuento_invitado >= 0 "
            "AND porcentaje_descuento_invitado <= 100 "
            "AND porcentaje_descuento_invitador >= 0 "
            "AND porcentaje_descuento_invitador <= 100",
            name="ck_configuracion_referidos_porcentajes"),
        CheckConstraint(
            "motor_premios IN ('promociones', 'tramos')",
            name="ck_configuracion_referidos_motor"),
    )

    def __repr__(self):
        return (f"<ConfiguracionReferidos(tenant_id={self.tenant_id}, "
                f"invitado={self.porcentaje_descuento_invitado}, "
                f"invitador={self.porcentaje_descuento_invitador}, "
                f"motor='{self.motor_premios}', "
                f"activo={self.activo})>")


# ── 4b. La tarjeta FIJA del carrusel ("Invita y Gana") ───────────────────────

class TarjetaReferidos(Base):
    """Copy editable de la tarjeta fija del carrusel "Novedades del box".

    Una fila por tenant (UNIQUE `tenant_id`). Sin fila se usan los textos por
    defecto de `referidos_service` (`TARJETA_REFERIDOS_*`); con fila, cada texto
    NULL o en blanco vuelve a ese default CAMPO POR CAMPO, así no hay que
    backfillear nada y una mejora del copy genérico llega sola a los boxes que
    nunca lo personalizaron.

    Vive APARTE de `ConfiguracionReferidos` a propósito: el copy lo lee el
    ALUMNO (`GET /referidos/tarjeta`) y los porcentajes son del admin; además,
    crear una fila de copy no debe cambiar `configurada` ni encender `activo`.
    `visible=False` oculta la tarjeta sin apagar el programa ni la ruta
    `/alumno/invita-y-gana`.
    """
    __tablename__ = "tarjeta_referidos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    titulo = Column(String(80), nullable=True)
    texto = Column(String(300), nullable=True)
    cta = Column(String(40), nullable=True)
    visible = Column(Boolean, nullable=False, server_default="true",
                     default=True)
    actualizado_en = Column(TIMESTAMP(timezone=True), nullable=False,
                            server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id",
                         name="uq_tarjeta_referidos_tenant_id"),
    )

    def __repr__(self):
        return (f"<TarjetaReferidos(tenant_id={self.tenant_id}, "
                f"visible={self.visible})>")


# ── 5. Promociones por volumen (premios) ─────────────────────────────────────

class PromocionReferidos(Base):
    """Premio que el admin define al alcanzar N referidos convertidos.

    Ej. "3 referidos = mes gratis": `umbral_referidos_convertidos=3`,
    `periodo='mensual'`, `tipo_premio='mes_gratis'`. `valor_premio` es NULL
    para `mes_gratis` y lleva días o porcentaje según el tipo.
    """
    __tablename__ = "promociones_referidos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(150), nullable=False)
    umbral_referidos_convertidos = Column(Integer, nullable=False)
    periodo = Column(SQLEnum(PeriodoPromocion, name="periodo_promocion"),
                     nullable=False, server_default="mensual",
                     default=PeriodoPromocion.mensual)
    tipo_premio = Column(SQLEnum(TipoPremio, name="tipo_premio_referido"),
                         nullable=False)
    valor_premio = Column(Numeric(10, 2), nullable=True)
    activo = Column(Boolean, nullable=False, server_default="true",
                    default=True)

    __table_args__ = (
        CheckConstraint("umbral_referidos_convertidos > 0",
                        name="ck_promociones_referidos_umbral_positivo"),
        Index("ix_promociones_referidos_tenant_id", "tenant_id"),
        Index("ix_promociones_referidos_activo", "activo"),
    )

    def __repr__(self):
        return (f"<PromocionReferidos(id={self.id}, nombre='{self.nombre}', "
                f"umbral={self.umbral_referidos_convertidos}, "
                f"premio='{self.tipo_premio}', activo={self.activo})>")


# ── 6. Umbrales detectados (notificación + confirmación del admin) ───────────

class PromocionReferidosDetectada(Base):
    """Un alumno alcanzó el umbral de una promoción en un período.

    La Fase 5 detecta el cumplimiento y crea la fila en
    `pendiente_confirmacion`, que dispara la notificación al admin (campana +
    correo). El admin la resuelve a `confirmado` (aplica el premio) o
    `rechazado` (no aplica nada). La UNIQUE (promoción, alumno, período) hace
    idempotente la detección: el mismo umbral no se notifica dos veces.

    El premio se CONGELA acá al detectar (`nombre_promocion`,
    `umbral_referidos_convertidos`, `tipo_premio`, `valor_premio`): editar o
    desactivar la promoción después no cambia lo que el alumno ya ganó.
    """
    __tablename__ = "promociones_referidos_detectadas"

    id = Column(Integer, primary_key=True)
    promocion_id = Column(Integer, ForeignKey(
        "promociones_referidos.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # "YYYY-MM" del período en que se cumplió el umbral (ej. "2026-10").
    periodo_cumplido = Column(String(7), nullable=False)
    # Snapshot del premio ganado (migración 053).
    nombre_promocion = Column(String(150), nullable=False)
    umbral_referidos_convertidos = Column(Integer, nullable=False)
    tipo_premio = Column(SQLEnum(TipoPremio, name="tipo_premio_referido"),
                         nullable=False)
    valor_premio = Column(Numeric(10, 2), nullable=True)
    fecha_deteccion = Column(TIMESTAMP(timezone=True), nullable=False,
                             server_default=func.now())
    estado = Column(SQLEnum(EstadoPromocionDetectada,
                            name="estado_promocion_detectada"),
                    nullable=False, server_default="pendiente_confirmacion",
                    default=EstadoPromocionDetectada.pendiente_confirmacion)
    fecha_confirmacion = Column(TIMESTAMP(timezone=True), nullable=True)
    # Qué admin resolvió la fila (NULL = todavía no la revisó o se eliminó su
    # cuenta: la traza del umbral se conserva).
    confirmado_por_usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        UniqueConstraint("promocion_id", "usuario_id", "periodo_cumplido",
                         name="uq_promociones_referidos_detectadas_periodo"),
        CheckConstraint(
            r"periodo_cumplido ~ '^\d{4}-(0[1-9]|1[0-2])$'",
            name="ck_promociones_referidos_detectadas_periodo_formato"),
        Index("ix_promociones_referidos_detectadas_usuario_id", "usuario_id"),
        Index("ix_promociones_referidos_detectadas_estado", "estado"),
    )

    def __repr__(self):
        return (f"<PromocionReferidosDetectada(id={self.id}, "
                f"promocion_id={self.promocion_id}, usuario_id={self.usuario_id}, "
                f"periodo='{self.periodo_cumplido}', estado='{self.estado}')>")


# ── 7. Crédito del invitador (Fase 3b) ───────────────────────────────────────

class CreditoReferido(Base):
    """Descuento GANADO por un alumno, consumible en SU próxima compra de plan.

    Tiene TRES orígenes posibles, y exactamente uno debe estar presente:
      * `referido_aplicado_id`: premio del invitador al convertir un referido;
      * `promocion_detectada_id`: premio `descuento_extra` de una promoción por
        volumen que el admin confirmó;
      * `premio_tramo_ciclo_id` (migración 064): premio `descuento_extra` de un
        tramo de la escalera al cierre de un ciclo de facturación.
    Cada origen es UNIQUE: un referido, una detección o un premio de tramo paga
    UN solo crédito. Los créditos NO se suman entre sí: cada uno se consume en
    una compra distinta (`referidos_service._credito_pendiente` toma el más
    antiguo pendiente), o sea que el descuento de un tramo no se acumula con el
    crédito individual del mismo referido.

    El `porcentaje` queda CONGELADO al otorgar el premio: cambiar la
    configuración del box o editar la promoción después no reescribe un premio
    ya ganado. No vence.

    `pendiente → usado` ocurre una sola vez, en la SIGUIENTE compra del alumno,
    y en ese momento se guardan el monto en pesos (`descuento_aplicado_clp`) y la
    suscripción que lo consumió (`suscripcion_id`, SET NULL si se borra la
    suscripción). Si el origen es un referido, el monto también se copia en
    `referidos_aplicados.descuento_aplicado_invitador`.
    """
    __tablename__ = "creditos_referido"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    # El alumno que GANÓ el crédito.
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # Origen A: el referido que lo originó (NULL si vino de una promoción).
    referido_aplicado_id = Column(Integer, ForeignKey(
        "referidos_aplicados.id", ondelete="CASCADE"), nullable=True)
    # Origen B: la detección confirmada que lo originó (NULL si vino de un referido).
    promocion_detectada_id = Column(Integer, ForeignKey(
        "promociones_referidos_detectadas.id", ondelete="CASCADE"), nullable=True)
    # Origen C (migración 064): el premio de tramo confirmado que lo originó.
    premio_tramo_ciclo_id = Column(Integer, ForeignKey(
        "premios_tramo_ciclo.id", ondelete="CASCADE"), nullable=True)
    # % del descuento, congelado al otorgarlo (0 < porcentaje <= 100).
    porcentaje = Column(Numeric(5, 2), nullable=False)
    estado = Column(SQLEnum(EstadoCreditoReferido,
                            name="estado_credito_referido"),
                    nullable=False, server_default="pendiente",
                    default=EstadoCreditoReferido.pendiente)
    fecha_otorgado = Column(TIMESTAMP(timezone=True), nullable=False,
                            server_default=func.now())
    fecha_usado = Column(TIMESTAMP(timezone=True), nullable=True)
    # Lo que costó el premio, en CLP, sobre el precio de LISTA del plan comprado.
    descuento_aplicado_clp = Column(Integer, nullable=True)
    # La suscripción que lo consumió (auditoría del cobro).
    suscripcion_id = Column(Integer, ForeignKey(
        "suscripciones.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        UniqueConstraint("referido_aplicado_id",
                         name="uq_creditos_referido_referido_aplicado_id"),
        UniqueConstraint("promocion_detectada_id",
                         name="uq_creditos_referido_promocion_detectada_id"),
        UniqueConstraint("premio_tramo_ciclo_id",
                         name="uq_creditos_referido_premio_tramo_ciclo_id"),
        CheckConstraint("porcentaje > 0 AND porcentaje <= 100",
                        name="ck_creditos_referido_porcentaje"),
        CheckConstraint(
            "(referido_aplicado_id IS NOT NULL)::int + "
            "(promocion_detectada_id IS NOT NULL)::int + "
            "(premio_tramo_ciclo_id IS NOT NULL)::int = 1",
            name="ck_creditos_referido_un_origen"),
        Index("ix_creditos_referido_tenant_id", "tenant_id"),
        Index("ix_creditos_referido_usuario_id", "usuario_id"),
        Index("ix_creditos_referido_estado", "estado"),
        # La consulta del consumo: créditos pendientes del usuario, FIFO.
        Index("ix_creditos_referido_usuario_estado", "usuario_id", "estado"),
    )

    def __repr__(self):
        return (f"<CreditoReferido(id={self.id}, usuario_id={self.usuario_id}, "
                f"referido_aplicado_id={self.referido_aplicado_id}, "
                f"promocion_detectada_id={self.promocion_detectada_id}, "
                f"premio_tramo_ciclo_id={self.premio_tramo_ciclo_id}, "
                f"porcentaje={self.porcentaje}, estado='{self.estado}')>")


# ── 8. Tramos del invitador (Parte C, migración 064) ────────────────────────

class TramoReferido(Base):
    """Un escalón de la escalera del box: "N referidos convertidos → premio".

    La escalera completa es el conjunto de filas activas ordenadas por
    `umbral_referidos`. `UNIQUE (tenant_id, umbral_referidos)` impide dos
    premios en el MISMO escalón (una escalera no puede ser ambigua); el orden
    lo da el umbral, no una columna `orden` que pueda desincronizarse.

    El premio se aplica al escalón MÁS ALTO alcanzado, no a todos: la
    exclusividad la garantiza `premios_tramo_ciclo` (una fila por ciclo).

    `valor_premio` depende del tipo (mismas reglas que `PromocionReferidos`):
    NULL en `mes_gratis`, días > 0 en `dias_gratis`, porcentaje 0–100 en
    `descuento_extra`. `activo=False` apaga el escalón sin borrar el historial
    de premios ya ganados (que conservan su snapshot).
    """
    __tablename__ = "tramos_referido"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    umbral_referidos = Column(Integer, nullable=False)
    tipo_premio = Column(SQLEnum(TipoPremio, name="tipo_premio_referido"),
                         nullable=False)
    valor_premio = Column(Numeric(10, 2), nullable=True)
    activo = Column(Boolean, nullable=False, server_default="true",
                    default=True)
    creado_en = Column(TIMESTAMP(timezone=True), nullable=False,
                       server_default=func.now())
    actualizado_en = Column(TIMESTAMP(timezone=True), nullable=False,
                            server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("umbral_referidos > 0",
                        name="ck_tramos_referido_umbral"),
        UniqueConstraint("tenant_id", "umbral_referidos",
                         name="uq_tramos_referido_tenant_umbral"),
        Index("ix_tramos_referido_tenant", "tenant_id", "activo"),
    )

    def __repr__(self):
        return (f"<TramoReferido(id={self.id}, tenant_id={self.tenant_id}, "
                f"umbral={self.umbral_referidos}, "
                f"premio='{self.tipo_premio}', activo={self.activo})>")


class PremioTramoCiclo(Base):
    """Premio GANADO por un alumno al cerrar UN ciclo de facturación.

    Nace al cierre del ciclo si el alumno alcanzó algún escalón: una fila por
    ciclo, con el escalón MÁS ALTO alcanzado (no uno por escalón). La
    `UNIQUE (usuario_id, suscripcion_id)` lo garantiza en la base: la detección
    usa `ON CONFLICT DO NOTHING`, así correr el job dos veces no duplica ni
    notifica dos veces.

    El premio y la ventana quedan CONGELADOS (`ciclo_inicio`, `ciclo_fin`,
    `referidos_convertidos`, `umbral_referidos`, `tipo_premio`, `valor_premio`):
    editar o apagar el escalón después no reescribe un premio ya ganado, igual
    que en `promociones_referidos_detectadas`.

    `aplicado_en` es la diferencia con la Fase 5: si al confirmar el alumno NO
    tiene plan vigente, el premio queda `confirmado` con `aplicado_en = NULL` en
    vez de rechazarse con 409, y el job diario lo aplica cuando vuelva a tener
    plan. Un premio ganado no se pierde porque el alumno esté entre planes.
    """
    __tablename__ = "premios_tramo_ciclo"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # El escalón que se aplicó (SET NULL si el admin borra la escalera: el
    # snapshot de abajo conserva lo que el alumno ganó).
    tramo_id = Column(Integer, ForeignKey(
        "tramos_referido.id", ondelete="SET NULL"), nullable=True)
    # El ciclo evaluado (la suscripción que lo define).
    suscripcion_id = Column(Integer, ForeignKey(
        "suscripciones.id", ondelete="SET NULL"), nullable=True)
    ciclo_inicio = Column(Date, nullable=False)
    ciclo_fin = Column(Date, nullable=False)
    referidos_convertidos = Column(Integer, nullable=False)
    # Snapshot del premio (mismo criterio que la Fase 5).
    umbral_referidos = Column(Integer, nullable=False)
    tipo_premio = Column(SQLEnum(TipoPremio, name="tipo_premio_referido"),
                         nullable=False)
    valor_premio = Column(Numeric(10, 2), nullable=True)
    estado = Column(SQLEnum(EstadoPromocionDetectada,
                            name="estado_promocion_detectada"),
                    nullable=False, server_default="pendiente_confirmacion",
                    default=EstadoPromocionDetectada.pendiente_confirmacion)
    fecha_deteccion = Column(TIMESTAMP(timezone=True), nullable=False,
                             server_default=func.now())
    fecha_confirmacion = Column(TIMESTAMP(timezone=True), nullable=True)
    confirmado_por_usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    aplicado_en = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("usuario_id", "suscripcion_id",
                         name="uq_premios_tramo_ciclo_ciclo"),
        CheckConstraint("ciclo_fin > ciclo_inicio",
                        name="ck_premios_tramo_ciclo_ventana"),
        CheckConstraint("referidos_convertidos > 0",
                        name="ck_premios_tramo_ciclo_convertidos"),
        Index("ix_premios_tramo_ciclo_estado", "estado"),
        Index("ix_premios_tramo_ciclo_tenant", "tenant_id", "estado"),
    )

    def __repr__(self):
        return (f"<PremioTramoCiclo(id={self.id}, usuario_id={self.usuario_id}, "
                f"umbral={self.umbral_referidos}, "
                f"convertidos={self.referidos_convertidos}, "
                f"estado='{self.estado}', aplicado_en={self.aplicado_en})>")
