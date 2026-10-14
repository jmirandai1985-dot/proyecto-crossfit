"""
El archivo semanal del coach → los WODs de la semana (y sus avisos).

QUÉ ES
------
`POST /wods/semana-archivo` recibe el .xlsx del coach (una fila por día) y devuelve la
vista previa; `POST /wods/programar-semana` guarda lo que esa vista mostró. Este módulo es
el ÚNICO lugar donde vive el formato:

  * el ORDEN de las columnas: fecha | calentamiento | musculacion | wod_nombre |
    wod_tipo | wod_descripcion | aviso;
  * la VALIDACIÓN de lo que es un archivo roto (celdas combinadas, filas vacías en el
    medio, fechas repetidas, más de 7 días y las columnas que no pueden venir vacías);
  * la NORMALIZACIÓN de `wod_tipo`: el vocabulario del mockup (For Time / AMRAP / EMOM) y
    TODO lo demás cae en "Otro" — el coach no tiene que memorizar la lista.

Las funciones son PURAS (no tocan la BD ni FastAPI): `leer_archivo` devuelve `(dias,
errores)` y `payloads_de_semana` arma los cuerpos que consume la API de WODs. Eso es lo que
permite probar el formato completo sin base de datos (`tests/test_wod_semana.py`).
"""
from datetime import date, datetime
from io import BytesIO

from openpyxl import load_workbook

# Las columnas, en el orden EXACTO del mockup (el archivo no lleva nombres).
COLUMNAS = ("fecha", "calentamiento", "musculacion", "wod_nombre", "wod_tipo",
            "wod_descripcion", "aviso")

# Tipos "bonitos" del selector; cualquier otra cosa (celda vacía, "amrap 20", "RFT")
# entra como "Otro": el coach no puede romper el archivo por cómo escribe el tipo.
TIPOS_VALIDOS = ("For Time", "AMRAP", "EMOM")
TIPO_OTRO = "Otro"

# Una semana son 7 días: más filas que eso es una planilla de otro mes.
MAX_DIAS = 7
# 2 MB: una planilla de 7 filas no llega ni cerca; el tope está para no leer cualquier cosa.
MAX_BYTES = 2 * 1024 * 1024


class ArchivoInvalido(Exception):
    """El archivo no se puede ni abrir (no es .xlsx o está corrupto)."""


def normalizar_tipo(valor) -> str:
    """`wod_tipo` de la planilla → uno de los tipos del mockup, o "Otro".

    Se compara sin importar mayúsculas ni espacios ("amrap " → "AMRAP"); lo que no
    reconoce NO se descarta ni se inventa: cae en "Otro", que es lo que el WOD muestra.
    """
    texto = valor.strip() if isinstance(valor, str) else (
        str(valor).strip() if valor is not None else "")
    for tipo in TIPOS_VALIDOS:
        if texto.lower() == tipo.lower():
            return tipo
    return TIPO_OTRO


def _texto(celda) -> str:
    """Celda → texto limpio ("" cuando viene vacía). Fechas y números también."""
    if celda is None:
        return ""
    if isinstance(celda, (datetime, date)):
        return celda.strftime("%Y-%m-%d")
    return str(celda).strip()


def _fecha(celda):
    """Celda → `date`, o None si no se entiende. Acepta celda de fecha y AAAA-MM-DD."""
    if isinstance(celda, datetime):
        return celda.date()
    if isinstance(celda, date):
        return celda
    texto = _texto(celda)
    if not texto:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None


def _fila_vacia(fila) -> bool:
    return all(_texto(c) == "" for c in fila)


def leer_archivo(contenido: bytes) -> tuple[list[dict], list[str]]:
    """El .xlsx → `(dias, errores)`: los días VÁLIDOS y el detalle de lo que falló.

    Se devuelven las dos cosas juntas (y no se corta en el primer error) para que la vista
    previa diga exactamente qué fila está mal: el coach arregla la planilla una vez, no a
    ciegas. Una fila con error NO se cuela como día programado.
    """
    if not contenido:
        raise ArchivoInvalido("El archivo llegó vacío.")
    if len(contenido) > MAX_BYTES:
        raise ArchivoInvalido("El archivo es demasiado grande (máximo 2 MB).")

    try:
        hoja = load_workbook(BytesIO(contenido), data_only=True).active
    except Exception as exc:  # openpyxl levanta varios tipos según el daño
        raise ArchivoInvalido(
            f"No se pudo leer el archivo como Excel (.xlsx): {exc}") from exc

    if hoja is None:
        raise ArchivoInvalido("El archivo no tiene ninguna hoja con datos.")

    errores = []
    combinadas = list(hoja.merged_cells.ranges) if hoja.merged_cells else []
    if combinadas:
        rangos = ", ".join(str(r) for r in combinadas[:3])
        errores.append(f"El archivo tiene celdas combinadas ({rangos}): cada día va en su "
                       "propia fila, sin celdas unidas.")

    filas = list(hoja.iter_rows(values_only=True))
    # Encabezado: si la primera fila no arranca con una fecha, se la toma como títulos
    # (el mockup documenta las columnas y mucha gente las pega igual en la planilla).
    if filas and _fecha(filas[0][0] if filas[0] else None) is None:
        filas = filas[1:]

    dias = []
    vistas = set()
    for numero, fila in enumerate(filas, start=1):
        if _fila_vacia(fila):
            # Una fila vacía EN EL MEDIO es un error explícito: si se saltea en silencio,
            # el coach cree que programó un día que nunca se publicó.
            errores.append(f"La fila {numero} está vacía: saca las filas en blanco.")
            continue

        celdas = list(fila) + [None] * (len(COLUMNAS) - len(fila))
        fecha = _fecha(celdas[0])
        if fecha is None:
            errores.append(f"Fila {numero}: la fecha tiene que ser una fecha de Excel o "
                           "venir como AAAA-MM-DD (ej. 2026-10-13).")
            continue
        if fecha in vistas:
            errores.append(f"Fila {numero}: la fecha {fecha} está repetida.")
            continue

        nombre = _texto(celdas[3])
        descripcion = _texto(celdas[5])
        if not descripcion:
            errores.append(f"Fila {numero} ({fecha}): falta la descripción del WOD.")
            continue
        if not nombre:
            errores.append(f"Fila {numero} ({fecha}): falta el nombre del WOD.")
            continue

        vistas.add(fecha)
        dias.append({
            "fecha": fecha,
            "calentamiento": _texto(celdas[1]) or None,
            "musculacion": _texto(celdas[2]) or None,
            "wod_nombre": nombre,
            "wod_tipo": normalizar_tipo(celdas[4]),
            "wod_descripcion": descripcion,
            "aviso": _texto(celdas[6]) or None,
        })

    if len(dias) > MAX_DIAS:
        errores.append(f"El archivo trae {len(dias)} días: una semana son {MAX_DIAS} "
                       "(lunes a domingo), así que no se programó nada.")
        return [], errores

    if not dias and not errores:
        errores.append("El archivo no tiene ninguna fila con datos.")

    return sorted(dias, key=lambda d: d["fecha"]), errores


def payloads_de_semana(dias: list[dict]) -> list[dict]:
    """Los días → el cuerpo de `WodCreate` de cada uno (un WOD por fecha).

    El mapeo a los nombres de la tabla es FIJO y no lo elige la pantalla:
    `musculacion` → `fuerza_habilidad` y `wod_descripcion` → `wod_principal` (los mismos
    campos que llena el formulario de Gestión de Clases). `estado` sale publicado: el WOD
    se ve el día que le toca por su propia `fecha`, sin ningún job que lo "publique".
    """
    return [{
        "fecha": dia["fecha"],
        "titulo": dia["wod_nombre"],
        "calentamiento": dia.get("calentamiento"),
        "fuerza_habilidad": dia.get("musculacion"),
        "wod_principal": dia["wod_descripcion"],
        "tipo_metcon": normalizar_tipo(dia.get("wod_tipo")),
        "estado": "publicado",
    } for dia in dias]
