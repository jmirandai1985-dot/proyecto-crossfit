"""
Códigos de RETIRO del Bazar (`pedidos.codigo_retiro`).

QUÉ ES
------
El código corto y legible que se genera **una sola vez** cuando el admin VALIDA un
pedido ("UB-4827") y que el alumno muestra en el mesón para retirarlo. En el mesón,
quien atiende (admin o coach del box) lo ingresa o lo escanea y el pedido pasa a
`entregado` con `entregado_por` / `entregado_en`.

REGLAS QUE VIVE ESTE MÓDULO (ver `docs/CODIGO_RETIRO_BAZAR.md`)

  1. **Sin caracteres ambiguos**: el alfabeto NO tiene `0/O/1/I/L` (se leen igual en
     un papel, en la pantalla de un celular o dictados por teléfono). `ALFABETO` es
     la única fuente de verdad y `PATRON` se DERIVA de él: si alguien agrega un
     símbolo, el formato acepta exactamente los mismos.
  2. **Único por BOX** (`tenant_id`), no global: dos boxes pueden tener el mismo
     código sin chocar. Lo garantiza `generar_codigo_unico` (reintenta) y, a nivel de
     BD, el índice único `uq_pedidos_codigo_retiro` (tenant_id, codigo_retiro).
  3. **Un código usado no se reutiliza**: el pedido entregado conserva su código (es
     la traza de la entrega), así que el código sigue ocupado para siempre.
  4. **El código de otro box no existe**: todas las búsquedas filtran por `tenant_id`,
     así que un código ajeno es indistinguible de uno inexistente (el endpoint
     responde 404 genérico y no revela nada).

Nada de acá commitea ni conoce HTTP: las funciones dejan los cambios en la
transacción del llamador y devuelven texto/datos; el endpoint (`api/v1/pedidos.py`)
traduce a 404/409 y commitea una sola vez.
"""
from __future__ import annotations

import re
import secrets
from datetime import timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.pedido import Pedido
from app.utils.santiago import SANTIAGO

__all__ = [
    "PREFIJO",
    "LARGO",
    "ALFABETO",
    "AMBIGUOS",
    "PATRON",
    "INTENTOS_UNICO",
    "SinCodigoDisponible",
    "MOTIVO_NO_VALIDADO",
    "MOTIVO_YA_ENTREGADO",
    "generar_codigo",
    "normalizar",
    "codigo_valido",
    "codigo_en_uso",
    "generar_codigo_unico",
    "buscar_pedido_por_codigo",
    "motivo_no_entregable",
    "texto_validado",
    "texto_no_validado",
    "texto_ya_entregado",
    "fmt_entrega",
]

# ── Formato: UB-XXXX ──────────────────────────────────────────────────────────
PREFIJO = "UB"
LARGO = 4

# 31 símbolos: dígitos 2-9 y letras A-Z SIN I, L ni O (y sin el 0 ni el 1, que ya
# quedaron fuera al empezar los dígitos en 2). Nada de caracteres que se confundan.
ALFABETO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

# Los que NO están (por si alguien "arregla" el alfabeto): se usan en los tests.
AMBIGUOS = ("0", "O", "1", "I", "L")

# El formato se DERIVA del alfabeto (una sola fuente de verdad).
PATRON = re.compile(rf"^{PREFIJO}-[{ALFABETO}]{{{LARGO}}}$")

# Un código nuevo se reintenta hasta INTENTOS_UNICO veces si el box ya tiene ese
# (31^4 = 923.521 combinaciones: agotar es prácticamente imposible salvo alfabeto roto).
INTENTOS_UNICO = 50

# Motivos por los que un pedido NO se puede entregar (el endpoint los traduce a 409
# con el texto correspondiente; `None` = sí se puede).
MOTIVO_NO_VALIDADO = "no_validado"
MOTIVO_YA_ENTREGADO = "ya_entregado"

# Caracteres que se aceptan como separadores al escribir/escanear un código
# ("ub 4827", "ub–4827", " UB-4827 "). Todo lo demás se descarta.
_SEPARADORES = re.compile(r"[^0-9A-Za-z]")


class SinCodigoDisponible(RuntimeError):
    """No hubo forma de generar un código único en `INTENTOS_UNICO` intentos.

    No debería pasar nunca (hay ~900.000 combinaciones por box): si pasa, el
    alfabeto está mal o el box ya tiene un volumen absurdo de códigos, y es mejor
    romper ruidosamente que escribir un código duplicado.
    """


# ── Generación ────────────────────────────────────────────────────────────────
def generar_codigo(elegir=secrets.choice) -> str:
    """Un código nuevo con el formato `UB-XXXX` (sin mirar la BD).

    `elegir` se puede inyectar para tests deterministas (una función que recibe la
    secuencia y devuelve un símbolo, como `secrets.choice` o `random.choice`).
    """
    cuerpo = "".join(elegir(ALFABETO) for _ in range(LARGO))
    return f"{PREFIJO}-{cuerpo}"


def codigo_en_uso(db: Session, tenant_id: int, codigo: str) -> bool:
    """¿Ese código ya lo tiene un pedido de ese box? (unicidad POR tenant)."""
    existe = db.query(Pedido.id).filter(
        Pedido.tenant_id == tenant_id,
        Pedido.codigo_retiro == codigo,
    ).first()
    return existe is not None


def generar_codigo_unico(db: Session, tenant_id: int,
                         intentos: int = INTENTOS_UNICO,
                         elegir=secrets.choice) -> str:
    """Código nuevo LIBRE en ese box, o `SinCodigoDisponible` si no lo logra.

    No commitea: quien llama lo guarda en el pedido (misma transacción que la
    validación, para que el aviso de campana lleve el código definitivo).
    """
    for _ in range(intentos):
        candidato = generar_codigo(elegir)
        if not codigo_en_uso(db, tenant_id, candidato):
            return candidato
    raise SinCodigoDisponible(
        f"No se pudo generar un código de retiro único para el box {tenant_id} "
        f"en {intentos} intentos")


# ── Lectura / normalización (lo que tipea o escanea el mesón) ─────────────────
def normalizar(texto: Optional[str]) -> Optional[str]:
    """Forma canónica `UB-XXXX` de lo que entró, o `None` si no parece un código.

    Acepta lo que un humano escribe o un lector pega: "ub-4827", "UB 4827",
    " ub4827 ", "UB–4827" (guion largo) e incluso solo "4827" → `"UB-4827"`.

    NO valida el alfabeto (eso es `codigo_valido`): un "UB-4O27" normaliza igual y
    después no existe en la BD, que es exactamente lo que debe pasar.
    """
    if texto is None:
        return None
    limpio = _SEPARADORES.sub("", str(texto)).upper()
    if not limpio:
        return None
    cuerpo = limpio[len(PREFIJO):] if limpio.startswith(PREFIJO) else limpio
    if len(cuerpo) != LARGO:
        return None
    return f"{PREFIJO}-{cuerpo}"


def codigo_valido(texto: Optional[str]) -> bool:
    """¿Tiene el formato exacto `UB-XXXX` con el alfabeto sin ambiguos?"""
    normalizado = normalizar(texto)
    return bool(normalizado and PATRON.match(normalizado))


def buscar_pedido_por_codigo(db: Session, tenant_id: int,
                             codigo: Optional[str]) -> Optional[Pedido]:
    """El pedido de ESE box con ese código, o `None`.

    `None` también cuando el texto ni siquiera tiene forma de código (sin tocar la
    BD) y cuando el código es de otro box: el llamador responde 404 genérico y no
    revela si existe en otro lado.

    Devuelve el pedido en CUALQUIER estado: el estado se revisa después, con
    `motivo_no_entregable`, para poder decir qué pasó (ya entregado / sin validar).
    """
    normalizado = normalizar(codigo)
    if not normalizado:
        return None
    return db.query(Pedido).filter(
        Pedido.tenant_id == tenant_id,
        Pedido.codigo_retiro == normalizado,
    ).first()


# ── Validaciones de la entrega (puras: reciben el pedido, no consultan nada) ──
def motivo_no_entregable(pedido: Optional[Pedido]) -> Optional[str]:
    """Por qué NO se puede entregar ese pedido, o `None` si sí se puede.

    Manda el estado REAL del pedido, no el código: un código que existe pero cuyo
    pedido sigue `pendiente` (o ya está `entregado`) no se entrega.
    """
    if pedido is None:
        return MOTIVO_NO_VALIDADO
    if pedido.estado == "entregado":
        return MOTIVO_YA_ENTREGADO
    if pedido.estado != "validado":
        return MOTIVO_NO_VALIDADO
    return None


def fmt_entrega(momento) -> str:
    """`dd/mm/aaaa hh:mm` en hora de CHILE del instante de la entrega.

    La BD guarda `timestamptz` (UTC): mostrarlo tal cual correría la hora entre 20:00
    y 23:59 CLT (bug ya documentado en Supervisión/Fechas). Un instante sin zona se
    asume UTC (lo que devuelve Postgres para una columna tz-aware).
    """
    if momento is None:
        return "fecha desconocida"
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(SANTIAGO).strftime("%d/%m/%Y %H:%M")


# ── Textos (una sola definición por mensaje) ──────────────────────────────────
def texto_validado(producto: str, cantidad: int, codigo: str) -> str:
    """Mensaje de campana del alumno al VALIDAR: incluye el código de retiro."""
    return (f"✅ Tu pedido de {producto} x{cantidad} fue validado. "
            f"Código de retiro: {codigo}")


def texto_no_validado(pedido: Pedido) -> str:
    """409 del mesón: el pedido todavía no está validado (sigue pendiente)."""
    return (f"El pedido #{pedido.id} todavía no fue validado. Pídele al "
            f"administrador del box que valide el comprobante y vuelve a intentar.")


def texto_ya_entregado(pedido: Pedido, nombre_entrego: Optional[str] = None) -> str:
    """409 del mesón: el código ya se usó (con fecha y quién entregó).

    Mismo texto para el reintento en el mesón y para el escaneo doble: es la traza
    de la entrega, no un error técnico.
    """
    return (f"Este pedido ya fue entregado el {fmt_entrega(pedido.entregado_en)} "
            f"por {nombre_entrego or 'otro usuario'}")
