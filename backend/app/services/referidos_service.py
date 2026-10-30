"""
Generación y asignación del código de referido de un alumno (Fase 2).

QUÉ ES
------
Cada alumno NUEVO recibe un código corto y legible para invitar a otro alumno.
El formato es 1 inicial del nombre + 5 letras del apellido + 3 dígitos, en
mayúsculas y sin tildes ni espacios: "Juan Pérez" → `JPERE234`.

REGLAS QUE VIVE ESTE MÓDULO
---------------------------
1. **Sólo alumnos.** `asignar_codigo_referido` confirma el rol ANTES de generar
   nada: admin y coach nunca reciben una fila en `codigos_referido`.
2. **Una sola fuente de verdad del formato.** `construir_prefijo` normaliza
   (NFKD: tildes, ñ y diéresis se convierten en su letra base) y recorta el
   apellido compuesto a su PRIMERA palabra ("De La Torre" → "DEXXX").
3. **Unicidad global.** `generar_codigo_referido` consulta `codigos_referido`
   (el código es UNIQUE en la BD) y reintenta los 3 dígitos hasta
   `INTENTOS_DIGITOS` veces. Si el prefijo agotara sus 1.000 combinaciones
   (prácticamente imposible), cae a un sufijo UUID corto.
4. **Sin efectos de negocio.** `generar_codigo_referido` NO inserta ni commitea:
   sólo lee para validar unicidad. `asignar_codigo_referido` agrega la fila y
   hace `flush()` dentro de la transacción del llamador, que es quien commitea
   (alta de alumno). Si la generación falla, la excepción sube y el alta entera
   se revierte: ni alumno sin código ni código huérfano.

Fase 3a agrega las REGLAS DE VALIDACIÓN de un código ingresado por el invitado
(sin auto-referido y una sola aplicación por alumno) y los constructores de
respuesta de los endpoints. El servicio sigue sin commitear: el router consulta,
inserta y hace el commit de `referidos_aplicados`.

Fase 3b aplica el DINERO: `confirmar_compra` se llama en el punto donde la
compra queda confirmada (aprobación de la solicitud o alta directa de la
suscripción), convierte el referido `pendiente` y descuenta al invitado; al
convertirse crea el `CreditoReferido` del invitador, que se consume UNA sola vez
en SU próxima compra. Sin configuración activa no se convierte ni se descuenta.
Tampoco commitea: el llamador guarda suscripción, referido, crédito e ingreso en
la misma transacción.

`previsualizar_compra` dice lo MISMO sin escribir nada, porque el monto se fija
antes de cobrar (preferencia de Mercado Pago, monto de la transferencia): con el
descuento aplicado recién al aprobar, el alumno pagaba el precio de lista y el
premio aparecía después de que la plata ya había salido.

La migración 054 suma las INVITACIONES ALUMNO → ALUMNO: armar el link
rastreable (`enlace_invitacion`), decidir si un correo se puede invitar
(`motivo_invitacion_rechazada`) y ligar la invitación al usuario que se
registra (`marcar_invitacion_registrada`). El envío del correo vive en el
router: el servicio no habla SMTP ni commitea.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.urls import url_frontend
from app.models.plan import Plan
from app.models.referidos import (CodigoReferido, ConfiguracionReferidos,
                                  CreditoReferido, EstadoCreditoReferido,
                                  EstadoInvitacion, EstadoReferido, Invitacion,
                                  ReferidoAplicado)
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario

__all__ = [
    "LARGO_APELLIDO",
    "RELLENO",
    "DIGITOS_ALEATORIOS",
    "INTENTOS_DIGITOS",
    "INTENTOS_FALLBACK",
    "PATRON_CODIGO",
    "MOTIVO_CODIGO_INEXISTENTE",
    "MOTIVO_CODIGO_INACTIVO",
    "MOTIVO_CODIGO_PROPIO",
    "MOTIVO_YA_REFERIDO",
    "MENSAJE_REFERIDO_REGISTRADO",
    "normalizar_letras",
    "dividir_nombre_completo",
    "construir_prefijo",
    "generar_codigo_referido",
    "asignar_codigo_referido",
    "normalizar_codigo_ingresado",
    "motivo_codigo_invalido",
    "calcular_descuento_clp",
    "es_primera_compra_pagada",
    "confirmar_compra",
    "datos_mi_codigo",
    "datos_referido_aplicado",
    "datos_configuracion",
    # La tarjeta fija del carrusel ("Invita y Gana").
    "TARJETA_REFERIDOS_TITULO",
    "TARJETA_REFERIDOS_TEXTO",
    "TARJETA_REFERIDOS_CTA",
    "datos_tarjeta",
    # Invitaciones alumno → alumno (migración 054).
    "TOKEN_INVITACION_BYTES",
    "LIMITE_INVITACIONES_DIA",
    "DIAS_BLOQUEO_REENVIO",
    "MOTIVO_INVITACION_PROPIA",
    "MOTIVO_INVITACION_YA_USUARIO",
    "MOTIVO_INVITACION_DUPLICADA",
    "MOTIVO_INVITACION_LIMITE",
    "normalizar_correo_invitacion",
    "generar_token_invitacion",
    "enlace_invitacion",
    "motivo_invitacion_rechazada",
    "invitacion_pendiente_por_token",
    "marcar_invitacion_registrada",
    "datos_invitacion_enviada",
    "datos_mi_invitacion",
]

# ── Formato: 1 inicial + 5 letras del apellido + 3 dígitos ───────────────────
LARGO_APELLIDO = 5
RELLENO = "X"
DIGITOS_ALEATORIOS = 3
INTENTOS_DIGITOS = 10
INTENTOS_FALLBACK = 10

# Contrato del formato "normal" (el fallback UUID corto NO matchea a propósito:
# es la salida de emergencia, no el formato esperado).
PATRON_CODIGO = re.compile(
    rf"^[A-Z]{{1}}[A-Z]{{{LARGO_APELLIDO}}}\d{{{DIGITOS_ALEATORIOS}}}$")

_ESPACIOS = re.compile(r"\s+")
_NO_LETRAS = re.compile(r"[^A-Za-z]")


def normalizar_letras(texto: Optional[str]) -> str:
    """Letras A-Z en mayúscula, sin tildes/ñ/diéresis ni espacios.

    NFKD separa cada letra de su acento ("é" → "e" + combinante, "ñ" → "n" +
    combinante); se descartan los combinantes y todo lo que no sea letra ASCII.
    """
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFKD", str(texto))
    sin_tildes = "".join(c for c in descompuesto
                         if not unicodedata.combining(c))
    return _NO_LETRAS.sub("", sin_tildes).upper()


def dividir_nombre_completo(nombre_completo: Optional[str]) -> Tuple[str, str]:
    """Separa "Nombre Apellido..." en (nombre, apellido).

    El alta guarda UN solo campo `nombre` con el nombre completo: la primera
    palabra es el nombre y el resto el apellido (que puede ser compuesto). Sin
    apellido, el segundo valor es "" y `construir_prefijo` rellena con "X".
    """
    partes = _ESPACIOS.split((nombre_completo or "").strip())
    partes = [p for p in partes if p]
    if not partes:
        return "", ""
    if len(partes) == 1:
        return partes[0], ""
    return partes[0], " ".join(partes[1:])


def construir_prefijo(nombre: Optional[str], apellido: Optional[str]) -> str:
    """Las 6 letras del código: inicial del nombre + 5 del primer apellido.

    * Sólo la PRIMERA palabra del apellido ("De La Torre" usa "De", no "DELAT").
    * Si el apellido tiene menos de 5 letras, se rellena con "X".
    * Sin nombre/ apellido utilizables, el prefijo sigue siendo válido ("X…").
    """
    inicial = normalizar_letras(nombre)[:1] or RELLENO

    palabras = [p for p in _ESPACIOS.split((apellido or "").strip()) if p]
    primera_palabra = palabras[0] if palabras else ""
    letras = normalizar_letras(primera_palabra)[:LARGO_APELLIDO]
    letras = letras.ljust(LARGO_APELLIDO, RELLENO)

    return inicial + letras


def _digitos_aleatorios() -> str:
    """3 dígitos con ceros a la izquierda (000-999), criptográficamente aleatorios.

    Es una función aparte para que los tests puedan sustituir la fuente de
    aleatoriedad y simular colisiones de forma determinista.
    """
    return f"{secrets.randbelow(10 ** DIGITOS_ALEATORIOS):0{DIGITOS_ALEATORIOS}d}"


def _codigo_en_uso(db: Session, codigo: str) -> bool:
    """¿Ya existe ese código? (lectura pura, sin insertar ni bloquear)."""
    return db.query(CodigoReferido.id).filter(
        CodigoReferido.codigo == codigo
    ).first() is not None


def generar_codigo_referido(nombre: str, apellido: str, db: Session) -> str:
    """Genera un código ÚNICO para el alumno, sin insertarlo en la BD.

    Estrategia:
      1. prefijo (1 inicial + 5 letras del apellido) + 3 dígitos aleatorios;
      2. si ese código ya existe, se regeneran SÓLO los 3 dígitos, hasta
         `INTENTOS_DIGITOS` veces;
      3. si el prefijo agotó sus combinaciones (caso extremo), se usa el mismo
         prefijo + 8 caracteres de un UUID4 (hasta `INTENTOS_FALLBACK` veces).

    Lanza `RuntimeError` sólo si tampoco el fallback encuentra un código libre:
    es preferible que el alta falle (y se revierta) a guardar un duplicado.
    """
    prefijo = construir_prefijo(nombre, apellido)

    for _ in range(INTENTOS_DIGITOS):
        candidato = f"{prefijo}{_digitos_aleatorios()}"
        if not _codigo_en_uso(db, candidato):
            return candidato

    for _ in range(INTENTOS_FALLBACK):
        candidato = f"{prefijo}{uuid.uuid4().hex[:8].upper()}"
        if not _codigo_en_uso(db, candidato):
            return candidato

    raise RuntimeError(
        "No se pudo generar un código de referido único "
        f"para el prefijo {prefijo} tras {INTENTOS_DIGITOS} reintentos "
        f"y {INTENTOS_FALLBACK} intentos de fallback"
    )


def _es_alumno(usuario: Usuario) -> bool:
    """Confirma el rol ANTES de generar: sólo `alumno` recibe código."""
    rol = getattr(usuario, "rol", None)
    # `RolUsuario` es str-enum: cubre tanto el enum como el texto plano.
    return getattr(rol, "value", rol) == RolUsuario.alumno.value


def asignar_codigo_referido(db: Session,
                            usuario: Usuario) -> Optional[CodigoReferido]:
    """Crea (sin commitear) la fila de `codigos_referido` del alumno.

    Devuelve `None` para admin/coach: la regla de negocio vive en un solo lugar
    y no depende de que cada endpoint se acuerde de preguntar el rol.

    Es idempotente por `usuario_id` (UNIQUE en la BD): si el alumno ya tiene
    código, devuelve la fila existente sin generar otra.

    El `flush()` deja la fila visible dentro de la MISMA transacción del alta y
    hace que cualquier violación de unicidad explote ANTES del commit, para que
    el llamador pueda revertir el alumno completo.
    """
    if not _es_alumno(usuario):
        return None

    if getattr(usuario, "id", None) is None:
        raise ValueError(
            "El usuario debe tener id (flush) antes de asignarle un código "
            "de referido")

    existente = db.query(CodigoReferido).filter(
        CodigoReferido.usuario_id == usuario.id
    ).first()
    if existente is not None:
        return existente

    nombre, apellido = dividir_nombre_completo(getattr(usuario, "nombre", None))
    codigo = generar_codigo_referido(nombre, apellido, db)

    fila = CodigoReferido(usuario_id=usuario.id, codigo=codigo, activo=True)
    db.add(fila)
    db.flush()
    return fila


# ── Validación de un código ingresado (Fase 3a) ──────────────────────────────

# Mensajes ÚNICOS de rechazo: el router los devuelve como `detail` de un 400 y
# los tests comprueban el texto, no un código de error inventado. El orden de
# `motivo_codigo_invalido` define qué mensaje ve el usuario cuando hay más de
# un problema (primero lo más básico: el código ni siquiera existe).
MOTIVO_CODIGO_INEXISTENTE = "El código de referido no existe"
MOTIVO_CODIGO_INACTIVO = "El código de referido está inactivo"
MOTIVO_CODIGO_PROPIO = "No puedes usar tu propio código de referido"
MOTIVO_YA_REFERIDO = (
    "Ya tienes un referido aplicado: sólo puedes ser referido una vez")

MENSAJE_REFERIDO_REGISTRADO = (
    "Código de referido aplicado. El referido quedó registrado como pendiente.")


def normalizar_codigo_ingresado(codigo: Optional[str]) -> str:
    """El código que escribe el invitado, en la forma en que se guarda.

    Los códigos se generan en MAYÚSCULAS y sin espacios, pero el alumno puede
    escribir " jpere234 " desde el celular. Se recorta y se pasa a mayúsculas
    ANTES de buscar en la BD: si no, un código válido parecería inexistente.
    """
    return (codigo or "").strip().upper()


def motivo_codigo_invalido(*, existe: bool, activo: bool, es_propio: bool,
                           ya_referido: bool) -> Optional[str]:
    """Devuelve el mensaje del primer motivo de rechazo, o `None` si es válido.

    Es una función PURA (sin BD): el router junta los cuatro hechos y esta
    función decide. Así las reglas de negocio se prueban sin base de datos y el
    orden de prioridad queda en un solo lugar:

      1. no existe (incluye el código de OTRO box: no se filtra su existencia);
      2. existe pero está inactivo;
      3. es el código del propio alumno (anti-auto-referido);
      4. el alumno ya tiene un referido aplicado (sólo se puede ser referido
         una vez, aunque ese referido siga `pendiente`).
    """
    if not existe:
        return MOTIVO_CODIGO_INEXISTENTE
    if not activo:
        return MOTIVO_CODIGO_INACTIVO
    if es_propio:
        return MOTIVO_CODIGO_PROPIO
    if ya_referido:
        return MOTIVO_YA_REFERIDO
    return None


def datos_mi_codigo(codigo: CodigoReferido) -> dict:
    """Respuesta de `GET /referidos/mi-codigo` (sólo el código propio).

    No incluye `usuario_id`: el alumno no necesita saber ids internos y el
    endpoint ya garantiza que la fila es la del token.
    """
    return {
        "codigo": codigo.codigo,
        "activo": bool(codigo.activo),
        "fecha_creacion": codigo.fecha_creacion,
    }


def datos_referido_aplicado(referido: ReferidoAplicado, codigo: str) -> dict:
    """Respuesta de `POST /referidos/validar-codigo` cuando el código es válido.

    `estado` sale del enum como texto (`pendiente`), que es lo que el panel
    muestra; la fila recién creada SIEMPRE nace `pendiente` en esta fase.
    """
    return {
        "valido": True,
        "codigo": codigo,
        "referido_id": referido.id,
        "estado": getattr(referido.estado, "value", referido.estado),
        "mensaje": MENSAJE_REFERIDO_REGISTRADO,
    }


def datos_configuracion(config: Any) -> dict:
    """Respuesta de la configuración del box, exista la fila o no.

    Sin fila se devuelven los DEFAULTS (`0%` / inactivo) y `configurada=False`,
    SIN crear nada en la BD: leer la configuración no escribe. Con fila, los
    `Numeric` se convierten a `float` para que el JSON sea un número y no un
    string/Decimal.
    """
    if config is None:
        return {
            "porcentaje_descuento_invitado": 0.0,
            "porcentaje_descuento_invitador": 0.0,
            "activo": False,
            "configurada": False,
        }

    return {
        "porcentaje_descuento_invitado": float(
            config.porcentaje_descuento_invitado),
        "porcentaje_descuento_invitador": float(
            config.porcentaje_descuento_invitador),
        "activo": bool(config.activo),
        "configurada": True,
    }


# ── La tarjeta FIJA del carrusel ("Invita y Gana") ──────────────────────────

# ESPEJO del `COPY_REFERIDOS` del frontend (`utils/avisosMarketing.js`): es el
# copy genérico que ve el alumno mientras el admin no personalice nada y, además,
# lo que pinta el carrusel si la consulta falla (la tarjeta nunca desaparece por
# un error de red). Los `..._MAX` de `app/schemas/referidos.py` tienen que poder
# contener estos textos: hay un test que lo verifica.
TARJETA_REFERIDOS_TITULO = "Invita y Gana"
TARJETA_REFERIDOS_TEXTO = (
    "Comparte tu código con un amigo y que entrene con nosotros.")
TARJETA_REFERIDOS_CTA = "Compartir mi código"


def _texto_o_default(valor: Optional[str], por_defecto: str) -> str:
    """El texto guardado (recortado) o el default; nunca una cadena en blanco."""
    limpio = (valor or "").strip()
    return limpio or por_defecto


def datos_tarjeta(tarjeta: Any) -> dict:
    """Copy EFECTIVO de la tarjeta fija del carrusel, exista la fila o no.

    Sin fila: los tres textos por defecto, `visible=True` y
    `personalizada=False`, SIN escribir en la BD (leer no crea filas). Con fila:
    cada texto NULL o en blanco cae a su default CAMPO POR CAMPO (así el admin
    puede personalizar sólo el texto y heredar el resto).

    `personalizada` es True sólo si el box guardó al menos un texto propio
    (`visible` no cuenta): el panel del admin lo usa para mostrar el chip
    "Texto por defecto" y ofrecer "Restablecer".
    """
    if tarjeta is None:
        return {
            "titulo": TARJETA_REFERIDOS_TITULO,
            "texto": TARJETA_REFERIDOS_TEXTO,
            "cta": TARJETA_REFERIDOS_CTA,
            "visible": True,
            "personalizada": False,
        }

    propios = (
        _texto_o_default(getattr(tarjeta, "titulo", None), ""),
        _texto_o_default(getattr(tarjeta, "texto", None), ""),
        _texto_o_default(getattr(tarjeta, "cta", None), ""),
    )
    return {
        "titulo": propios[0] or TARJETA_REFERIDOS_TITULO,
        "texto": propios[1] or TARJETA_REFERIDOS_TEXTO,
        "cta": propios[2] or TARJETA_REFERIDOS_CTA,
        "visible": bool(getattr(tarjeta, "visible", True)),
        "personalizada": any(propios),
    }


# ── Fase 3b: el dinero (descuentos al confirmarse una compra) ────────────────

def calcular_descuento_clp(precio_lista_clp: int, porcentaje) -> int:
    """Descuento en CLP sobre el precio de LISTA: `round(precio * % / 100)`.

    Es la MISMA aritmética de `beneficios_service.desglose`: un porcentaje
    calculado en dos lados es un porcentaje que se desincroniza. El redondeo es
    al peso (los montos del proyecto son enteros) y `porcentaje` puede venir como
    `Decimal` de la BD (los porcentajes admiten 2 decimales).
    """
    if isinstance(precio_lista_clp, bool) or not isinstance(precio_lista_clp, int) \
            or precio_lista_clp <= 0:
        raise ValueError(
            "El precio de lista tiene que ser un entero positivo "
            f"(llegó {precio_lista_clp!r}).")
    pct = Decimal(str(porcentaje if porcentaje is not None else 0))
    if pct < 0 or pct > 100:
        raise ValueError(
            f"El porcentaje tiene que estar entre 0 y 100 (llegó {porcentaje!r}).")
    return int(round(Decimal(precio_lista_clp) * pct / Decimal(100)))


def es_primera_compra_pagada(db: Session, *, tenant_id: int, usuario_id: int,
                             suscripcion_id: Optional[int] = None) -> bool:
    """¿El alumno no tiene ninguna suscripción ANTERIOR de un plan con precio > 0?

    No alcanza con contar suscripciones: el alta de alumno crea una suscripción
    al plan "Prueba" (`precio_clp=0`) y Fidelización crea el "Pase de regreso"
    (también gratis). Si esos contaran, NINGÚN alumno tendría una "primera
    compra" y el descuento del referido nunca se aplicaría. La regla es la
    compra de un plan PAGADO.

    `suscripcion_id` excluye la suscripción que se acaba de crear en esta misma
    compra (se pasa cuando ya está `flush()`eada, antes del commit).
    """
    consulta = db.query(Suscripcion.id).join(
        Plan, Plan.id == Suscripcion.plan_id
    ).filter(
        Suscripcion.usuario_id == usuario_id,
        Suscripcion.tenant_id == tenant_id,
        Plan.precio_clp > 0,
    )
    if suscripcion_id is not None:
        consulta = consulta.filter(Suscripcion.id != suscripcion_id)
    return consulta.first() is None


def _configuracion_activa(db: Session, tenant_id: int):
    """La configuración del box SÓLO si el programa está encendido (o `None`)."""
    return db.query(ConfiguracionReferidos).filter(
        ConfiguracionReferidos.tenant_id == tenant_id,
        ConfiguracionReferidos.activo.is_(True),
    ).first()


def _referido_pendiente(db: Session, usuario_id: int, *, bloquear: bool):
    """El referido `pendiente` del alumno como INVITADO (uno solo por validación).

    `FOR UPDATE` serializa dos compras simultáneas del mismo alumno: la segunda
    espera el lock y, al ver la fila ya `convertido`, no la convierte dos veces.
    """
    consulta = db.query(ReferidoAplicado).filter(
        ReferidoAplicado.usuario_invitado_id == usuario_id,
        ReferidoAplicado.estado == EstadoReferido.pendiente,
    )
    if bloquear:
        consulta = consulta.with_for_update()
    return consulta.order_by(ReferidoAplicado.id).first()


def _credito_pendiente(db: Session, *, tenant_id: int, usuario_id: int,
                       bloquear: bool):
    """El crédito `pendiente` MÁS VIEJO del invitador (FIFO), o `None`.

    `FOR UPDATE` hace que dos compras simultáneas no consuman el mismo crédito:
    la segunda espera y, al re-evaluar el `WHERE estado='pendiente'`, ya no lo ve.
    """
    consulta = db.query(CreditoReferido).filter(
        CreditoReferido.tenant_id == tenant_id,
        CreditoReferido.usuario_id == usuario_id,
        CreditoReferido.estado == EstadoCreditoReferido.pendiente,
    )
    if bloquear:
        consulta = consulta.with_for_update()
    return consulta.order_by(CreditoReferido.fecha_otorgado,
                             CreditoReferido.id).first()


def _descuento_cobrado(precio_lista_clp: int, descuento: int,
                       precio_final_clp: Optional[int]) -> int:
    """El descuento que REALMENTE se cobró cuando el precio ya estaba congelado.

    El precio puede haberse fijado ANTES de esta confirmación (la preferencia de
    Mercado Pago o el monto que el alumno transfirió): si la configuración del
    programa cambió entre medio, manda el dinero que entró a la caja y no un `%`
    recalculado hoy. Sin precio congelado se respeta el `%` de la configuración.
    Un precio final fuera de rango se acota a `[0, precio_lista_clp]`: nunca un
    descuento negativo ni mayor que el precio.
    """
    if precio_final_clp is None:
        return descuento
    return max(0, min(precio_lista_clp, precio_lista_clp - int(precio_final_clp)))


def _descuento_aplicable(db: Session, *, tenant_id: int, usuario_id: int,
                         precio_lista_clp, suscripcion_id: Optional[int],
                         bloquear: bool):
    """QUÉ descuento le toca a esta compra, sin escribir nada.

    Es la ÚNICA implementación del ORDEN de las reglas de `confirmar_compra` (ver
    su docstring): la usan la confirmación real (`bloquear=True`, con `FOR UPDATE`)
    y la previsualización (`bloquear=False`), así el precio que se anuncia antes de
    cobrar y el que se aplica al cobrar no pueden salir de dos reglas distintas.

    Devuelve `(config, referido, credito, pct, descuento_clp)` —exactamente uno de
    `referido`/`credito` es distinto de `None`— o `None` si no hay nada que aplicar.
    """
    if isinstance(precio_lista_clp, bool) or not isinstance(precio_lista_clp, int) \
            or precio_lista_clp <= 0:
        return None
    config = _configuracion_activa(db, tenant_id)
    if config is None:
        return None

    referido = None
    if es_primera_compra_pagada(db, tenant_id=tenant_id, usuario_id=usuario_id,
                                suscripcion_id=suscripcion_id):
        referido = _referido_pendiente(db, usuario_id, bloquear=bloquear)
        # Otra compra concurrente pudo convertirlo mientras esperábamos el lock.
        if referido is not None and referido.estado != EstadoReferido.pendiente:
            referido = None

    if referido is not None:
        pct = Decimal(str(config.porcentaje_descuento_invitado
                          if config.porcentaje_descuento_invitado is not None
                          else 0))
        return (config, referido, None, pct,
                calcular_descuento_clp(precio_lista_clp, pct))

    credito = _credito_pendiente(db, tenant_id=tenant_id,
                                 usuario_id=usuario_id, bloquear=bloquear)
    if credito is None or credito.estado != EstadoCreditoReferido.pendiente:
        return None
    pct = Decimal(str(credito.porcentaje
                      if credito.porcentaje is not None else 0))
    return (config, None, credito, pct,
            calcular_descuento_clp(precio_lista_clp, pct))


def previsualizar_compra(db: Session, *, tenant_id: int, usuario_id: int,
                         precio_lista_clp, suscripcion_id: Optional[int] = None
                         ) -> Optional[dict]:
    """El desglose que `confirmar_compra` aplicaría, SIN escribir nada.

    Existe porque el monto a cobrar tiene que conocerse ANTES de cobrar: la
    preferencia de Mercado Pago y el monto que el admin valida en la transferencia
    se fijan al crear la compra, y el descuento del referido aparecía recién al
    aprobarla (cuando el alumno ya había pagado el precio de lista).

    NO convierte el referido ni consume el crédito: consultar el precio no puede
    gastar el premio (un carrito abandonado dejaría al alumno sin su descuento).
    La conversión sigue ocurriendo en `confirmar_compra`, que ahora recibe el
    precio ya congelado para registrar exactamente lo que se cobró.

    Devuelve `{"origen", "porcentaje", "descuento_clp", "precio_lista_clp",
    "precio_final_clp", "referido_aplicado_id"}` o `None`.
    """
    base = _descuento_aplicable(db, tenant_id=tenant_id, usuario_id=usuario_id,
                                precio_lista_clp=precio_lista_clp,
                                suscripcion_id=suscripcion_id, bloquear=False)
    if base is None:
        return None
    _config, referido, credito, pct, descuento = base
    return {
        "origen": ("referido_invitado" if referido is not None
                   else "credito_invitador"),
        "porcentaje": float(pct),
        "descuento_clp": descuento,
        "precio_lista_clp": precio_lista_clp,
        "precio_final_clp": precio_lista_clp - descuento,
        "referido_aplicado_id": (referido.id if referido is not None
                                 else credito.referido_aplicado_id),
    }


def confirmar_compra(db: Session, *, tenant_id: int, usuario_id: int,
                     precio_lista_clp, suscripcion_id: Optional[int] = None,
                     ahora: Optional[datetime] = None,
                     precio_final_clp: Optional[int] = None) -> Optional[dict]:
    """Aplica los descuentos del programa al CONFIRMARSE una compra de plan.

    Se llama SÓLO en el punto en que la compra ya está confirmada (aprobar la
    solicitud o crear la suscripción desde el panel): escribe `referidos_aplicados`
    y `creditos_referido`. Devuelve el desglose que el llamador debe cobrar, o
    `None` si no había nada que aplicar. NO commitea.

    El precio que se ANUNCIA antes de cobrar lo dice `previsualizar_compra`, con
    las mismas reglas; ésta es la que CONVIERTE (una sola vez).

    `precio_final_clp` es el precio que ya se le fijó al alumno (preferencia de
    Mercado Pago, monto de la transferencia). Si viene, el descuento se mide
    contra ESE monto: lo que se registra tiene que ser lo que entró a la caja,
    aunque la configuración del programa haya cambiado entre medio. El
    `porcentaje` informado sigue siendo el de la configuración (es el número que
    el panel muestra como "el % del programa"); el dinero es el cobrado.

    Reglas (Fase 3b):
      1. Sin configuración activa no se convierte ni se descuenta.
      2. Invitado: sólo en su PRIMERA compra de un plan PAGADO, con un referido
         `pendiente`. La conversión ocurre aunque el porcentaje sea 0 (el
         invitador gana su crédito por la conversión); el descuento usa
         `porcentaje_descuento_invitado`.
      3. Invitador: su SIGUIENTE compra consume UN crédito `pendiente` (FIFO),
         una sola vez, y deja el monto en `descuento_aplicado_invitador`.
      4. No se apilan: si el alumno es invitado con primera compra Y además tiene
         un crédito propio, gana el descuento del invitado y el crédito queda
         pendiente para una compra futura.
      5. Un precio no positivo (plan Prueba / Pase de regreso) no genera nada.
    """
    base = _descuento_aplicable(db, tenant_id=tenant_id, usuario_id=usuario_id,
                                precio_lista_clp=precio_lista_clp,
                                suscripcion_id=suscripcion_id, bloquear=True)
    if base is None:
        return None
    config, referido, credito, pct, descuento = base
    descuento = _descuento_cobrado(precio_lista_clp, descuento, precio_final_clp)

    momento = ahora or datetime.now(timezone.utc)

    if referido is not None:
        referido.estado = EstadoReferido.convertido
        referido.fecha_conversion = momento
        referido.descuento_aplicado_invitado = Decimal(descuento)

        credito_otorgado = None
        pct_invitador = Decimal(str(config.porcentaje_descuento_invitador
                                    if config.porcentaje_descuento_invitador is not None
                                    else 0))
        if pct_invitador > 0:
            credito_otorgado = CreditoReferido(
                tenant_id=tenant_id,
                usuario_id=referido.usuario_invitador_id,
                referido_aplicado_id=referido.id,
                porcentaje=pct_invitador,
                estado=EstadoCreditoReferido.pendiente,
                fecha_otorgado=momento,
            )
            db.add(credito_otorgado)
            db.flush()

        return {
            "origen": "referido_invitado",
            "porcentaje": float(pct),
            "descuento_clp": descuento,
            "precio_lista_clp": precio_lista_clp,
            "precio_final_clp": precio_lista_clp - descuento,
            "referido_aplicado_id": referido.id,
            "promocion_detectada_id": None,
            "credito_referido_id": None,
            "credito_otorgado_id": (credito_otorgado.id
                                    if credito_otorgado is not None else None),
        }

    # No era el invitado: `_descuento_aplicable` sólo puede haber devuelto el
    # crédito del invitador (FIFO), YA bloqueado para que dos compras no lo gasten.
    credito.estado = EstadoCreditoReferido.usado
    credito.fecha_usado = momento
    credito.descuento_aplicado_clp = descuento
    credito.suscripcion_id = suscripcion_id
    # Snapshot en la fila del referido que originó el premio. Un crédito de
    # `descuento_extra` (Fase 5) no tiene referido: su origen es la detección
    # confirmada y no hay `referidos_aplicados` que actualizar.
    if credito.referido_aplicado_id is not None:
        origen = db.query(ReferidoAplicado).filter(
            ReferidoAplicado.id == credito.referido_aplicado_id
        ).with_for_update().first()
        if origen is not None:
            origen.descuento_aplicado_invitador = Decimal(descuento)

    return {
        "origen": "credito_invitador",
        "porcentaje": float(pct),
        "descuento_clp": descuento,
        "precio_lista_clp": precio_lista_clp,
        "precio_final_clp": precio_lista_clp - descuento,
        "referido_aplicado_id": credito.referido_aplicado_id,
        "promocion_detectada_id": credito.promocion_detectada_id,
        "credito_referido_id": credito.id,
        "credito_otorgado_id": None,
    }


# ── Invitaciones alumno → alumno (migración 054) ─────────────────────────────
# Un alumno invita a un amigo por correo. La fila de `invitaciones` guarda SU
# código y un token opaco que viaja en el link; al registrarse, el amigo queda
# ligado a la invitación y la compra puede prellenar el código.

# 24 bytes → 32 caracteres en base64url: cabe de sobra en `varchar(64)` y no es
# adivinable (no es un id incremental).
TOKEN_INVITACION_BYTES = 24
# Anti-abuso por ALUMNO (no por IP: el rate limit por IP es compartido por todo
# el box detrás del mismo NAT, y bloquearía a todos por un solo abusador).
LIMITE_INVITACIONES_DIA = 5
# Reenvío al MISMO correo: se bloquea dentro de esta ventana. El enlace viejo
# sigue sirviendo, así que el bloqueo no le quita nada al invitador.
DIAS_BLOQUEO_REENVIO = 7

MOTIVO_INVITACION_PROPIA = "No puedes invitarte a ti mismo"
MOTIVO_INVITACION_YA_USUARIO = "Ese correo ya pertenece a un usuario del box"
MOTIVO_INVITACION_DUPLICADA = (
    "Ya se envió una invitación a ese correo hace menos de 7 días: "
    "reenvía el mismo enlace")
MOTIVO_INVITACION_LIMITE = (
    "Alcanzaste el límite de 5 invitaciones por día. Inténtalo mañana")


def normalizar_correo_invitacion(correo: Optional[str]) -> str:
    """El correo del amigo en la forma en que se guarda y se compara.

    Igual que el resto del alta (`usuarios.correo` se guarda en minúsculas):
    sin recortar, `" Amigo@Box.cl "` no encontraría al usuario existente y el
    anti-abuso se podría saltar cambiando mayúsculas o espacios.
    """
    return (correo or "").strip().lower()


def generar_token_invitacion() -> str:
    """Token del link `/landing?inv=<token>` (criptográficamente aleatorio)."""
    return secrets.token_urlsafe(TOKEN_INVITACION_BYTES)


def enlace_invitacion(token: str) -> str:
    """Link ABSOLUTO que recibe el amigo (una sola definición del path)."""
    return url_frontend(f"/landing?inv={token}")


def motivo_invitacion_rechazada(*, es_propio: bool, ya_usuario: bool,
                                enviada_reciente: bool) -> Optional[str]:
    """Primer motivo por el que NO se puede invitar a ese correo (o `None`).

    Función PURA (sin BD), mismo criterio que `motivo_codigo_invalido`: el
    router junta los hechos y acá queda el orden de prioridad en un solo lugar.
    El límite diario NO está acá porque se responde 429, no 400.
    """
    if es_propio:
        return MOTIVO_INVITACION_PROPIA
    if ya_usuario:
        return MOTIVO_INVITACION_YA_USUARIO
    if enviada_reciente:
        return MOTIVO_INVITACION_DUPLICADA
    return None


def invitacion_pendiente_por_token(db: Session, token: Optional[str],
                                   tenant_id: int) -> Optional[Invitacion]:
    """La invitación `enviada` con ese token en el box, o `None`.

    `None` es la respuesta a un token vacío, inexistente, de otro box o YA
    usado (`registrado`): el alta lo ignora en silencio y nunca falla por eso.
    """
    limpio = (token or "").strip()
    if not limpio:
        return None
    return db.query(Invitacion).filter(
        Invitacion.token_rastreo == limpio,
        Invitacion.tenant_id == tenant_id,
        Invitacion.estado == EstadoInvitacion.enviada,
    ).first()


def marcar_invitacion_registrada(invitacion: Optional[Invitacion],
                                 usuario_id: int,
                                 momento: Optional[datetime] = None) -> None:
    """Liga la invitación al usuario recién creado (no commitea).

    Se llama DESPUÉS del `flush()` del alta, dentro de la misma transacción:
    si el alta falla, la invitación sigue `enviada` y el link se puede reusar.
    """
    if invitacion is None:
        return
    invitacion.estado = EstadoInvitacion.registrado
    invitacion.fecha_registro = momento or datetime.now(timezone.utc)
    invitacion.usuario_registrado_id = usuario_id


def datos_invitacion_enviada(invitacion: Invitacion, codigo: str) -> dict:
    """Respuesta de `POST /referidos/invitaciones` (el enlace se puede reenviar)."""
    return {
        "id": invitacion.id,
        "correo_prospecto": invitacion.correo_prospecto,
        "codigo": codigo,
        "token_rastreo": invitacion.token_rastreo,
        "enlace": enlace_invitacion(invitacion.token_rastreo),
        "estado": getattr(invitacion.estado, "value", invitacion.estado),
        "fecha_envio": invitacion.fecha_envio,
    }


def datos_mi_invitacion(invitacion: Optional[Invitacion],
                        codigo: Optional[str],
                        nombre_invitador: Optional[str]) -> dict:
    """Respuesta de `GET /referidos/mi-invitacion`.

    Sin invitación devuelve `codigo=None` (200, no 404): "no me invitó nadie"
    es un estado normal del alumno y el front simplemente no prellena nada.
    No se expone el correo del invitador: el alumno ya lo conoce y no hace
    falta ampliar la superficie de datos personales del endpoint.
    """
    if invitacion is None:
        return {
            "codigo": None,
            "nombre_invitador": None,
            "estado": None,
            "fecha_registro": None,
        }
    return {
        "codigo": codigo,
        "nombre_invitador": nombre_invitador,
        "estado": getattr(invitacion.estado, "value", invitacion.estado),
        "fecha_registro": invitacion.fecha_registro,
    }
