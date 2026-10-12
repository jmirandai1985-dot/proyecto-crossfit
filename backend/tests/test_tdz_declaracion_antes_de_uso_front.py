"""Fix del TDZ que dejaba Fidelización en el ErrorBoundary ("La app no pudo abrir esta pantalla").

CAUSA (2026-10, confirmada en un build de PRODUCCIÓN): en `Fidelizacion.jsx` el hook
`useChurn(tenant_id, buscar)` se llamaba ANTES de declarar `buscar`:

    const churnQ = useChurn(tenant_id, buscar);     // usa `buscar`
    ...
    const [buscar, setBuscar] = useState('');       // se declara DESPUÉS

Los `const`/`let` viven en la ZONA MUERTA TEMPORAL (TDZ): el render tira
`Cannot access '...' before initialization` y el ErrorBoundary muestra el cartel de error.
En el bundle de producción el nombre sale minificado (el mensaje decía `so`/`se`), por eso
el síntoma parece un problema del bundler y no del orden de las declaraciones.

Este guard es un análisis ESTÁTICO del fuente (sin red y sin base):
  A. El detector encuentra un TDZ real (autotest: no es un guard vacío).
  B. Ninguna pantalla/componente de `frontend/src` usa un identificador antes de declararlo.
  C. El caso concreto de `Fidelizacion.jsx` queda con el orden correcto.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_tdz_declaracion_antes_de_uso_front.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SRC = RAIZ / "frontend" / "src"
FIDELIZACION = "frontend/src/pages/admin/Fidelizacion.jsx"

RESERVADAS = {
    "null", "true", "false", "undefined", "this", "of", "in", "new", "void",
    "typeof", "delete", "default", "case", "instanceof",
}

_RE_COMENTARIO_BLOQUE = re.compile(r"/\*[\s\S]*?\*/")
_RE_COMENTARIO_LINEA = re.compile(r"(^|[^:])//[^\n]*")
_RE_COMILLA_SIMPLE = re.compile(r"'[^'\n]*'")
_RE_COMILLA_DOBLE = re.compile(r'"[^"\n]*"')
_RE_TEMPLATE = re.compile(r"`[^`]*`")
_RE_TEXTO_JSX = re.compile(r">[^<>{}]*<")
_RE_LLAVE_ABRE = re.compile(r"\{")
_RE_LLAVE_CIERRA = re.compile(r"\}")
_RE_IDENTIFICADOR = re.compile(r"[A-Za-z_$][\w$]*")
_RE_DECLARACION = re.compile(
    r"\b(const|let)\s+(\[[^\]]*\]|\{[^}]*\}|[A-Za-z_$][\w$]*)\s*=")


def _vaciar(match: "re.Match") -> str:
    """Vacía el contenido conservando el largo (así las posiciones siguen siendo las del
    fuente original)."""
    texto = match.group(0)
    return texto[0] + " " * (len(texto) - 2) + texto[-1]


def _limpiar(texto: str) -> str:
    """Saca comentarios, strings, templates y TEXTO JSX dejando huecos del mismo largo: una
    palabra dentro de un string ("Sin plan") o de un comentario no cuenta como uso. Los
    saltos de línea se conservan SIEMPRE (si no, los números de línea del reporte mienten)."""
    def _huecos(match: "re.Match") -> str:
        return "".join(("\n" if c == "\n" else " ") for c in match.group(0))

    texto = _RE_COMENTARIO_BLOQUE.sub(_huecos, texto)
    texto = _RE_COMENTARIO_LINEA.sub(
        lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))), texto)
    texto = _RE_COMILLA_SIMPLE.sub(_vaciar, texto)
    texto = _RE_COMILLA_DOBLE.sub(_vaciar, texto)
    texto = _RE_TEMPLATE.sub(_vaciar, texto)
    return _RE_TEXTO_JSX.sub(_vaciar, texto)


def _ambitos(texto: str) -> dict:
    """Id de ámbito (la última llave abierta sin cerrar) de cada identificador: una sola
    pasada, con las llaves y los identificadores en orden de posición."""
    eventos = [(m.start(), 1) for m in _RE_LLAVE_ABRE.finditer(texto)]
    eventos += [(m.start(), -1) for m in _RE_LLAVE_CIERRA.finditer(texto)]
    eventos.sort()

    siguiente_id = 0
    pila = [0]
    ambito = {}
    i = 0
    for token in _RE_IDENTIFICADOR.finditer(texto):
        pos = token.start()
        while i < len(eventos) and eventos[i][0] < pos:
            if eventos[i][1] == 1:
                siguiente_id += 1
                pila.append(siguiente_id)
            elif len(pila) > 1:
                pila.pop()
            i += 1
        ambito[pos] = pila[-1]
    return ambito


def hallazgos(texto: str):
    """[(linea_uso, nombre, linea_declaracion)] por cada uso anterior a su declaración en el
    MISMO ámbito. Un uso dentro de un closure anidado tiene otro ámbito y NO cuenta: ahí se
    evalúa después y no hay TDZ."""
    limpio = _limpiar(texto)
    ambito = _ambitos(limpio)

    posiciones = {}
    for token in _RE_IDENTIFICADOR.finditer(limpio):
        pos = token.start()
        # `x.nombre` (acceso a propiedad) y `nombre:` (clave de objeto / etiqueta) NO son
        # referencias al binding: se descartan para no inventar hallazgos.
        if pos and limpio[pos - 1] == ".":
            continue
        if token.end() < len(limpio) and limpio[token.end()] == ":":
            continue
        posiciones.setdefault(token.group(0), []).append(pos)

    salida = []
    ya = set()
    for decl in _RE_DECLARACION.finditer(limpio):
        mi_ambito = ambito.get(decl.start())
        for nombre in _RE_IDENTIFICADOR.findall(decl.group(2)):
            if nombre in RESERVADAS:
                continue
            clave = (nombre, mi_ambito)
            if clave in ya:
                continue
            for pos in posiciones.get(nombre, []):
                if pos >= decl.start():
                    break
                if ambito.get(pos) != mi_ambito:
                    continue
                salida.append((limpio.count("\n", 0, pos) + 1, nombre,
                               limpio.count("\n", 0, decl.start()) + 1))
                ya.add(clave)
                break
    return salida


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


# ── TDZ INDIRECTO: una función que usa un `const` declarado más abajo Y SE LLAMA ANTES ──
# Caso real (2026-10, Bloque 2 parte C): `buildWeekGrid()` se llamaba en la primera línea
# del panel del coach y su cuerpo usaba `clasesSemana`, que pasó a declararse más abajo.
# El uso está en OTRO ámbito (el cuerpo de la función), así que el chequeo de arriba no lo
# ve, pero la llamada ocurre antes de la declaración y el render rompe igual.
_RE_ARROW_BODY = re.compile(r"=>\s*\{")
_RE_FUNC_BODY = re.compile(r"\bfunction\b[^;{}]*\([^)]*\)\s*\{")
_RE_NOMBRE_ARROW = re.compile(r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=")


def _fin_del_bloque(limpio: str, abre: int) -> int:
    """Posición de la llave que CIERRA el bloque que abre en `abre`."""
    nivel = 0
    for i in range(abre, len(limpio)):
        if limpio[i] == "{":
            nivel += 1
        elif limpio[i] == "}":
            nivel -= 1
            if nivel == 0:
                return i
    return len(limpio) - 1


def _nombre_de_arrow(limpio: str, flecha: int) -> str:
    """`const nombre = (...) => {` → 'nombre'. Un callback anónimo → None."""
    corte = max(limpio.rfind(";", 0, flecha), limpio.rfind("{", 0, flecha),
                limpio.rfind("}", 0, flecha))
    match = _RE_NOMBRE_ARROW.search(limpio[corte + 1:flecha + 1])
    return match.group(1) if match else None


def _cuerpos(limpio: str) -> list:
    """(inicio, fin, nombre, pos_flecha) de cada cuerpo de función del archivo."""
    cuerpos = []
    for m in _RE_ARROW_BODY.finditer(limpio):
        abre = m.end() - 1
        cuerpos.append((abre, _fin_del_bloque(limpio, abre),
                        _nombre_de_arrow(limpio, m.start()), m.start()))
    for m in _RE_FUNC_BODY.finditer(limpio):
        abre = m.end() - 1
        nombre = re.search(r"\bfunction\s+([A-Za-z_$][\w$]*)", limpio[m.start():m.end()])
        cuerpos.append((abre, _fin_del_bloque(limpio, abre),
                        nombre.group(1) if nombre else None, m.start()))
    return cuerpos


def _cuerpo_dueno(pos: int, cuerpos: list):
    """El cuerpo de función MÁS INTERNO que contiene la posición (None si está en el
    nivel de módulo)."""
    dentro = [c for c in cuerpos if c[0] <= pos <= c[1]]
    return min(dentro, key=lambda c: c[1] - c[0]) if dentro else None


def _es_llamada(limpio: str, match: "re.Match") -> bool:
    """`nombre(...)` cuenta como llamada; `function nombre(...)` y `obj.nombre(...)` no."""
    antes = limpio[:match.start()].rstrip()
    if antes.endswith("function") or antes.endswith(".") or antes.endswith("?."):
        return False
    return True


def _se_ejecuta_al_pasar(pos: int, cuerpos: list, limpio: str) -> bool:
    """¿La posición se evalúa en el flujo que corre YA (no dentro de un callback)?

    Un componente (`const Panel = () => {`) corre al renderizar: su cuerpo va de arriba
    abajo, así que una llamada antes de la declaración SÍ es TDZ. Un `useEffect`/`onClick`
    no (se evalúa después), y una fábrica de `useMemo` sí (corre en el render)."""
    dentro = [c for c in cuerpos if c[0] <= pos <= c[1]]
    if not dentro:
        return True
    ini, _fin, nombre, flecha = min(dentro, key=lambda c: c[1] - c[0])
    if nombre and nombre[0].isupper():
        return True
    if nombre is None and "useMemo(" in limpio[max(0, flecha - 80):flecha]:
        return True
    return False


def hallazgos_en_funciones(texto: str) -> list:
    """(linea_llamada, nombre, linea_declaracion) de cada TDZ indirecto."""
    limpio = _limpiar(texto)
    cuerpos = _cuerpos(limpio)

    declaraciones = []
    for decl in _RE_DECLARACION.finditer(limpio):
        for nombre in _RE_IDENTIFICADOR.findall(decl.group(2)):
            if nombre not in RESERVADAS:
                declaraciones.append((nombre, decl.start()))

    salida = []
    for ini, fin, nombre_f, _flecha in cuerpos:
        if not nombre_f:
            continue
        en_cuerpo = set(_RE_IDENTIFICADOR.findall(limpio[ini:fin + 1]))
        for nombre, pos_decl in declaraciones:
            if nombre not in en_cuerpo or pos_decl <= fin:
                continue
            # La declaración tiene que ser VISIBLE desde este cuerpo: si vive dentro de
            # OTRA función (un `const data = ...` local de un vecino) no lo es, y el
            # nombre repetido no prueba nada.
            dueno = _cuerpo_dueno(pos_decl, cuerpos)
            if dueno is not None and not (dueno[0] <= ini and fin <= dueno[1]):
                continue
            for call in re.finditer(r"\b" + re.escape(nombre_f) + r"\s*\(", limpio):
                if call.start() >= pos_decl:
                    break
                if ini <= call.start() <= fin:
                    continue                      # se llama a sí misma (recursión)
                if not _es_llamada(limpio, call):
                    continue                      # `function nombre(` / `obj.nombre(` no llaman
                if _se_ejecuta_al_pasar(call.start(), cuerpos, limpio):
                    salida.append((limpio.count("\n", 0, call.start()) + 1, nombre,
                                   limpio.count("\n", 0, pos_decl) + 1))
                    break
    return sorted(set(salida))



def test_a_el_detector_encuentra_un_tdz_real():
    """Autotest: si el detector no marca este caso, el guard no sirve para nada."""
    roto = (
        "const F = () => {\n"
        "    const churnQ = useChurn(tenant_id, buscar);\n"
        "    const [buscar, setBuscar] = useState('');\n"
        "    return churnQ;\n"
        "};\n"
    )
    assert hallazgos(roto) == [(2, "buscar", 3)]
    # El MISMO código en orden correcto no marca nada.
    bien = (
        "const F = () => {\n"
        "    const [buscar, setBuscar] = useState('');\n"
        "    const churnQ = useChurn(tenant_id, buscar);\n"
        "    return churnQ;\n"
        "};\n"
    )
    assert hallazgos(bien) == []
    # Dentro de un closure anidado (con llaves propias) el uso es legítimo: se evalúa después.
    closure = (
        "const F = () => {\n"
        "    const enviar = () => { setBuscar(buscar.trim()); };\n"
        "    const [buscar, setBuscar] = useState('');\n"
        "    return enviar;\n"
        "};\n"
    )
    assert hallazgos(closure) == []


def test_b_ninguna_pantalla_usa_un_identificador_antes_de_declararlo():
    problemas = []
    for archivo in sorted(list(SRC.rglob("*.jsx")) + list(SRC.rglob("*.js"))):
        rel = archivo.relative_to(RAIZ).as_posix()
        for linea, nombre, linea_decl in hallazgos(archivo.read_text(encoding="utf-8")):
            problemas.append(
                f"{rel}:{linea} usa '{nombre}' (se declara en la línea {linea_decl})")
    assert problemas == [], (
        "TDZ: identificador usado antes de su const/let en el mismo ámbito "
        "(rompe el render en producción):\n  " + "\n  ".join(problemas))


def test_d_tdz_indirecto_en_una_funcion_llamada_antes_de_la_declaracion():
    """El caso que se escapó: la referencia está en el cuerpo de una función y la LLAMADA
    ocurre antes de la declaración (el render rompe igual que en el TDZ directo)."""
    roto = (
        "const Componente = () => {\n"                       # 1
        "    const armarGrilla = () => {\n"                  # 2
        "        return (clases || []).map(c => c.id);\n"    # 3
        "    };\n"                                           # 4
        "    const grilla = armarGrilla();\n"                # 5  <- llamada
        "    const clases = listaDeClases();\n"              # 6  <- declaración
        "    return grilla;\n"                               # 7
        "};\n"                                               # 8
    )
    assert hallazgos_en_funciones(roto) == [(5, "clases", 6)]
    # Mismo código con `clases` declarado ANTES: no hay nada que avisar.
    bien = (
        "const Componente = () => {\n"
        "    const clases = listaDeClases();\n"
        "    const armarGrilla = () => {\n"
        "        return (clases || []).map(c => c.id);\n"
        "    };\n"
        "    const grilla = armarGrilla();\n"
        "    return grilla;\n"
        "};\n"
    )
    assert hallazgos_en_funciones(bien) == []
    # Llamada DENTRO de un callback (useEffect / onClick): se evalúa después del render,
    # cuando la declaración ya ocurrió -> no es TDZ.
    diferido = (
        "const Componente = () => {\n"
        "    const armar = () => {\n"
        "        return (clases || []).map(c => c.id);\n"
        "    };\n"
        "    useEffect(() => { const g = armar(); }, []);\n"
        "    const clases = listaDeClases();\n"
        "    return null;\n"
        "};\n"
    )
    assert hallazgos_en_funciones(diferido) == []
    # ...pero una fábrica de useMemo SÍ corre en el render: ahí la llamada es un TDZ real.
    en_memo = (
        "const Componente = () => {\n"
        "    const armar = () => {\n"
        "        return (clases || []).map(c => c.id);\n"
        "    };\n"
        "    const g = useMemo(() => armar(), []);\n"
        "    const clases = listaDeClases();\n"
        "    return g;\n"
        "};\n"
    )
    assert hallazgos_en_funciones(en_memo) == [(5, "clases", 6)]


def test_e_ningun_archivo_llama_antes_a_una_funcion_que_usa_un_const_posterior():
    problemas = []
    for archivo in sorted(list(SRC.rglob("*.jsx")) + list(SRC.rglob("*.js"))):
        rel = archivo.relative_to(RAIZ).as_posix()
        for linea, nombre, linea_decl in hallazgos_en_funciones(
                archivo.read_text(encoding="utf-8")):
            problemas.append(
                f"{rel}:{linea} llama antes de tiempo a una función que usa '{nombre}' "
                f"(se declara en la línea {linea_decl})")
    assert problemas == [], (
        "TDZ indirecto: la función se llama antes de que su `const` esté inicializado "
        "(rompe el render en producción):\n  " + "\n  ".join(problemas))

    fuente = _fuente(FIDELIZACION)
    assert "const [buscar, setBuscar] = useState('');" in fuente
    assert fuente.index("const [buscar, setBuscar] = useState('');") < fuente.index(
        "const churnQ = useChurn(tenant_id, buscar);")
    assert hallazgos(fuente) == []
