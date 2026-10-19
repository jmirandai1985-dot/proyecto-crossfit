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

Esta fase NO expone endpoints ni aplica descuentos: el alta del alumno es el
único punto de escritura.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
import uuid
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.referidos import CodigoReferido
from app.models.usuario import RolUsuario, Usuario

__all__ = [
    "LARGO_APELLIDO",
    "RELLENO",
    "DIGITOS_ALEATORIOS",
    "INTENTOS_DIGITOS",
    "INTENTOS_FALLBACK",
    "PATRON_CODIGO",
    "normalizar_letras",
    "dividir_nombre_completo",
    "construir_prefijo",
    "generar_codigo_referido",
    "asignar_codigo_referido",
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
