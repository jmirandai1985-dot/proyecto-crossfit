"""Búsqueda server-side insensible a MAYÚSCULAS Y TILDES (nombre / correo del alumno).

Por qué `translate()` y no `unaccent()`: la base de este proyecto (Neon + TEST) NO tiene
la extensión `unaccent` instalada (solo `plpgsql`), pero `translate()` sí (mapea carácter
a carácter). Se combina con `lower()` para el lado de mayúsculas.

`normalizar()` (Python) y `columna_normalizada()` (SQL) usan la MISMA tabla origen->destino,
así el patrón `%...%` y la columna se comparan siempre "en el mismo idioma".
"""
from sqlalchemy import func

# Pares origen->destino. OJO: la tabla incluye la MAYÚSCULA acentuada además de la
# minúscula, porque `lower()` de Postgres puede no bajar una 'Á' según la colección; así
# el mapeo funciona igual aunque `lower()` falle. Cada acentuada cae en su letra simple.
_ORIGEN = "áàäâãéèëêíìïîóòöôõúùüûñçÁÀÄÂÃÉÈËÊÍÌÏÎÓÒÖÔÕÚÙÜÛÑÇ"
_DESTINO = "aaaaaeeeeiiiiooooouuuunc" * 2
_TABLA = str.maketrans(_ORIGEN, _DESTINO)


def normalizar(texto: str | None) -> str:
    """`lower()` + sin tildes, en Python. Normaliza el término `buscar` del patrón."""
    if not texto:
        return ""
    return texto.lower().translate(_TABLA)


def columna_normalizada(columna):
    """Expresión SQL `translate(lower(columna), origen, destino)` (columna lista para `like`)."""
    return func.translate(func.lower(columna), _ORIGEN, _DESTINO)
