"""RUT chileno: normalización y validación del dígito verificador (módulo 11).

Vive en `app/utils` y no en un router a propósito: lo usan DOS rutas de negocio —el alta
de alumno (`api/v1/alumnos.py`) y los datos bancarios del box (`api/v1/configuracion.py`,
donde el RUT es el del titular de la cuenta)— y ninguna de las dos es "dueña" de la regla.
Antes vivía en `api/v1/alumnos.py` y la configuración del box no validaba nada: el RUT que
el alumno ve en la pantalla de transferencia podía ser cualquier texto.
"""
import re

# Cuerpo de 1 a 8 dígitos + guion + dígito verificador (0-9 o K).
PATRON_RUT = re.compile(r"^\d{1,8}-[0-9K]$")


def normalizar_rut(rut) -> str:
    """El RUT en la forma canónica del sistema: sin puntos ni espacios, con guion y DV
    en mayúscula ("12.345.678-9" -> "12345678-9").

    Si el texto no trae guion o el DV no es válido, devuelve igual el texto recortado:
    decidir si sirve es trabajo de `validar_rut`, no de la normalización.
    """
    if rut is None:
        return ""
    return re.sub(r"[.\s]", "", str(rut)).strip().upper()


def validar_rut(rut) -> bool:
    """Valida el RUT chileno completo (formato + dígito verificador, módulo 11)."""
    rut = normalizar_rut(rut)
    if not PATRON_RUT.match(rut):
        return False
    cuerpo, dv = rut.split("-")
    suma = 0
    multiplo = 2
    for d in reversed(cuerpo):
        suma += int(d) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = suma % 11
    dv_calc = 11 - resto
    if dv_calc == 11:
        dv_calc = 0
    elif dv_calc == 10:
        dv_calc = "K"
    return str(dv_calc) == dv
