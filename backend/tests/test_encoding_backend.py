"""Guarda anti-mojibake del BACKEND: ningún archivo puede quedar con el texto UTF-8
guardado/leído con la codificación equivocada.

Correr (aislado, sin BD ni servidor):
    cd backend && py -3.12 -m pytest tests/test_encoding_backend.py -q --noconftest

POR QUÉ EXISTE
--------------
Es el hermano backend de `frontend/scripts/test-encoding.mjs` (commit 8df8a94). El mismo
accidente que dejó "Fuerza M\\u00e1xima" en el frontend había tocado el backend: 18
archivos de `app/`, `tests/`, `scripts/` y la raíz tenían el texto DOBLEMENTE codificado
(el UTF-8 del texto se leyó como CP1252/Latin-1 y se volvió a guardar como UTF-8), así que
los comentarios se veían "configuraci\\u00f3n", las secciones "\\u00e2\\u201d\\u00e2\\u201d",
los emojis de log "\\u00f0\\u0178\\u0161\\u20ac" y las flechas "\\u00e2\\u2020\\u2019". (Los
patrones se escriben con escapes \\u A PROPÓSITO: si este archivo llevara los caracteres
literales, la guarda fallaría contra sí misma.)

Nada lo detecta solo: es Python válido, compila, y ningún test mira los comentarios. Por
eso la guarda mira el CONTENIDO byte a byte y falla si aparece:

  1. cualquiera de los patrones corruptos conocidos del reporte (letras acentuadas,
     comillas tipográficas, guiones, dibujos de caja, flechas, checks y emojis partidos en
     dos o tres caracteres);
  2. mojibake GENÉRICO por prueba de ida y vuelta: cada tramo NO ASCII de la línea se
     reconstruye como bytes CP1252/Latin-1 y se vuelve a decodificar en UTF-8; si sale
     texto distinto y limpio, ese tramo estaba doblemente codificado. Una "á" correcta NO
     pasa esa prueba (su byte 0xE1 no forma UTF-8 válido), así que el texto bueno queda
     intacto y la guarda no depende de una lista completa de patrones;
  3. caracteres de control C1 (U+0080-U+009F): sólo aparecen al leer UTF-8 como Latin-1
     (es el byte 0x8D de "\\u00c3<0x8D>" = Í, o el selector de emoji del aviso);
  4. que el archivo no decodifique como UTF-8 estricto (o sea: que se haya guardado en
     CP1252/Latin-1). El BOM NO se revisa acá: 33 archivos del backend lo traen de antes y
     no es mojibake (varios tests los leen con `utf-8-sig`).

QUÉ SE ESCANEA
--------------
Todo `backend/` salvo lo que no es fuente ni configuración legible: `.log`, imágenes,
dumps (`.db`/`.sqlite`), las carpetas de herramientas (`__pycache__`, `.venv`,
`.pytest_cache`, ...) y `backups/` (son copias con fecha: quedan como estaban). Los
`.env*` SÍ se revisan — son locales y no versionados, pero el accidente también los había
tocado.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]           # .../backend

# Texto legible por humanos. `_es_texto()` suma los `.env*` (sin extensión real para
# pathlib) y los Dockerfile/crontab, que no llevan extensión.
EXTENSIONES = (".py", ".sql", ".json", ".yml", ".yaml", ".md", ".txt", ".ini", ".cfg",
               ".toml", ".sh", ".bat", ".mako", ".js", ".mjs", ".ts", ".tsx", ".css",
               ".html")
NOMBRES = ("Dockerfile", "Dockerfile.cron", "crontab", ".dockerignore", ".gitignore")
CARPETAS_IGNORADAS = {"__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
                      ".pytest_cache", "htmlcov", ".git", "dist", "build", "logs",
                      "uploads", "backups"}

# Bytes 0x80-0x9F de CP1252 (lo que se obtiene al leer UTF-8 como CP1252) y su vuelta.
CP1252 = {0x80: 0x20AC, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E, 0x85: 0x2026,
          0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6, 0x89: 0x2030, 0x8A: 0x0160,
          0x8B: 0x2039, 0x8C: 0x0152, 0x8E: 0x017D, 0x91: 0x2018, 0x92: 0x2019,
          0x93: 0x201C, 0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
          0x98: 0x02DC, 0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A, 0x9C: 0x0153,
          0x9E: 0x017E, 0x9F: 0x0178}
REV = {caracter: byte for byte, caracter in CP1252.items()}

# Patrones corruptos del reporte, escritos como CÓDIGOS de caracter para que este archivo
# no pueda fallar contra sí mismo (si llevara los caracteres literales, la guarda los
# encontraría acá). No alcanza con la primera letra: una 'Ã' o una 'â' sueltas existen de
# verdad (`app/utils/busqueda.py` tiene la tabla de tildes con esas letras legítimas).
PATRONES = (
    ((0x00C3, 0x00B0), "emoji"),
    ((0x00C3, 0x00A1), "á"), ((0x00C3, 0x00A9), "é"), ((0x00C3, 0x00AD), "í"),
    ((0x00C3, 0x00B3), "ó"), ((0x00C3, 0x00BA), "ú"), ((0x00C3, 0x00B1), "ñ"),
    ((0x00C3, 0x0081), "Á"), ((0x00C3, 0x0089), "É"), ((0x00C3, 0x008D), "Í"),
    ((0x00C3, 0x0093), "Ó"), ((0x00C3, 0x009A), "Ú"),
    ((0x00E2, 0x20AC, 0x0153), "comilla de apertura"),
    ((0x00E2, 0x20AC, 0x009D), "comilla de cierre"),
    ((0x00E2, 0x20AC, 0x201D), "guion largo"),
    ((0x00E2, 0x20AC, 0x00A6), "puntos suspensivos"),
    ((0x00C2, 0x00A1), "¡"), ((0x00C2, 0x00BF), "¿"), ((0x00C2, 0x00B9), "¹"),
    ((0x00C2, 0x00BA), "º"), ((0x00C2, 0x00AA), "ª"), ((0x00C2, 0x00B2), "²"),
    ((0x00C3, 0x2039), "‹"), ((0x00C3, 0x0192), "doble codificación"),
    ((0x00E2, 0x201D, 0x20AC), "dibujo de caja"),
    ((0x00E2, 0x2020, 0x2019), "flecha"),
    ((0x00E2, 0x0153, 0x2026), "check"),
    ((0x00E2, 0x009D, 0x0152), "cruz"),
    ((0x00E2, 0x0161, 0x00A0), "aviso"),
    ((0x00E2, 0x201E, 0x00B9), "información"),
    ((0x00F0, 0x0178), "emoji"),
    ((0x00EF, 0x00B8), "selector de emoji"),
)
CONTROL_C1 = re.compile(r"[\u0080-\u009f]")
NO_ASCII = re.compile(r"[^\x00-\x7f]+")


def patron_de(codigos: tuple[int, ...]) -> str:
    """Los códigos del patrón -> el texto corrupto que hay que buscar."""
    return "".join(chr(codigo) for codigo in codigos)


def _es_texto(nombre: str) -> bool:
    return (nombre.lower().endswith(EXTENSIONES) or nombre in NOMBRES
            or nombre.startswith(".env"))


def _archivos() -> list[Path]:
    """Todo el backend que se puede leer como texto, sin las carpetas de herramientas."""
    return [ruta for ruta in sorted(RAIZ.rglob("*"))
            if ruta.is_file() and _es_texto(ruta.name)
            and not (CARPETAS_IGNORADAS & set(ruta.relative_to(RAIZ).parts[:-1]))]


ARCHIVOS = _archivos()


def _rel(ruta: Path) -> str:
    return ruta.relative_to(RAIZ).as_posix()


def _lineas(ruta: Path) -> list[str]:
    """Las líneas del archivo. `errors="replace"` a propósito: un archivo que no sea
    UTF-8 lo reporta el test C (acá, con `strict`, reventaría con un traceback ilegible)."""
    return ruta.read_bytes().decode("utf-8", errors="replace").split("\n")


def _bytes_de(texto: str) -> bytes | None:
    """Los bytes que produjeron el texto (CP1252 y, en 0x80-0x9F, el byte tal cual).

    None = el texto tiene un caracter "de verdad" (emoji, →, ─, ...), así que no puede
    venir de una doble codificación.
    """
    salida = bytearray()
    for caracter in texto:
        punto = ord(caracter)
        if punto < 0x80 or 0x80 <= punto <= 0x9F or punto in REV:
            salida.append(REV.get(punto, punto))
        elif punto <= 0xFF:
            salida.append(punto)
        else:
            return None
    return bytes(salida)


def _reparado(texto: str) -> str | None:
    """El texto que saldría de re-decodificar esos bytes como UTF-8 (None = no aplica)."""
    crudo = _bytes_de(texto)
    if crudo is None or all(byte < 0x80 for byte in crudo):
        return None
    try:
        return crudo.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _tramos_corruptos(linea: str) -> list[str]:
    """Los tramos de la línea que quedaron doblemente codificados (ya reparados)."""
    corruptos = []
    for tramo in NO_ASCII.findall(linea):
        reparado = _reparado(tramo)
        if reparado is not None and reparado != tramo and "\ufffd" not in reparado:
            corruptos.append(reparado)
    return corruptos


def test_a_ningun_archivo_le_queda_un_patron_corrupto_conocido():
    hallazgos = []
    for ruta in ARCHIVOS:
        for numero, linea in enumerate(_lineas(ruta), 1):
            marcas = [nombre for codigos, nombre in PATRONES if patron_de(codigos) in linea]
            if CONTROL_C1.search(linea):
                marcas.append("control C1")
            if marcas:
                hallazgos.append(f"{_rel(ruta)}:{numero}: {' / '.join(sorted(set(marcas)))}"
                                 f"  ->  {linea.strip()[:90]}")
    assert hallazgos == [], "\n".join(hallazgos)


def test_b_ninguna_linea_es_utf8_doblemente_codificado():
    """La prueba de ida y vuelta: vale para el mojibake de cualquier nivel."""
    hallazgos = []
    for ruta in ARCHIVOS:
        for numero, linea in enumerate(_lineas(ruta), 1):
            for reparado in _tramos_corruptos(linea):
                hallazgos.append(f"{_rel(ruta)}:{numero}: debería decir {reparado!r}"
                                 f"  ->  {linea.strip()[:90]}")
    assert hallazgos == [], "\n".join(hallazgos)


def test_c_todos_los_archivos_decodifican_como_utf8_estricto():
    """Sin `errors="replace"`: si alguno se guardó en CP1252/Latin-1, acá se cae.

    El BOM NO se revisa: 33 archivos de `app/`, `scripts/` y `tests/` lo traen de antes
    (varios tests los leen con `utf-8-sig`), no es mojibake y sacarlo sería un cambio de
    codificación ajeno a esta guarda.
    """
    ilegibles = []
    for ruta in ARCHIVOS:
        try:
            ruta.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            ilegibles.append(f"{_rel(ruta)}: {error}")
    assert ilegibles == [], "\n".join(ilegibles)


def test_d_la_guarda_detecta_el_mojibake_y_no_las_tildes_buenas():
    """Que la guarda de verdad mire: los patrones sirven sólo si detectan, y la tabla de
    tildes de `app/utils/busqueda.py` (que tiene 'Ã' y 'â' LEGÍTIMAS) no puede dar falso
    positivo: es lo que obliga a buscar pares de caracteres y no la primera letra."""
    corrompida = "configuraci" + patron_de((0x00C3, 0x00B3)) + "n"
    assert _tramos_corruptos(corrompida) == ["ó"]
    assert [nombre for codigos, nombre in PATRONES if patron_de(codigos) in corrompida] == ["ó"]

    # El texto correcto (con la 'ó' de verdad) no se toca...
    assert _tramos_corruptos("configuración") == []
    # ... ni la tabla de acentos reales, que además lleva la 'Ã' y la 'â' de verdad.
    acentos = (RAIZ / "app" / "utils" / "busqueda.py").read_text(encoding="utf-8-sig")
    linea = [renglon for renglon in acentos.splitlines()
             if renglon.startswith("_ORIGEN")][0]
    assert _tramos_corruptos(linea) == []
    assert [nombre for codigos, nombre in PATRONES if patron_de(codigos) in linea] == []
    assert CONTROL_C1.search(linea) is None

def test_e_la_guarda_mira_todo_el_backend():

    """Meta-guarda: si el barrido se rompiera, los tres tests de arriba pasarían en verde
    sin haber mirado nada."""
    nombres = {_rel(ruta) for ruta in ARCHIVOS}
    # Muestra de archivos que SÍ o SÍ tienen que estar escaneados (fuente, tests, scripts,
    # configuración y este mismo archivo).
    for esperado in ("app/main.py", "app/services/avisos_marketing.py",
                     "app/models/wod.py", "app/core/dependencies.py",
                     "run_setup_test_db.py", "scripts/sync_test_from_prod.py",
                     "tests/conftest.py", "tests/test_end_to_end.py",
                     "alembic.ini", ".dockerignore", ".env.example",
                     "tests/test_encoding_backend.py"):
        assert esperado in nombres, esperado
    assert len(ARCHIVOS) > 200, len(ARCHIVOS)
    # Lo que NO es fuente queda afuera (si no, la guarda sería ruido en cada corrida).
    assert not [nombre for nombre in nombres if nombre.endswith(".log")], "hay logs"
    assert not [nombre for nombre in nombres
                if "__pycache__" in nombre or ".venv" in nombre], "hay caché"

