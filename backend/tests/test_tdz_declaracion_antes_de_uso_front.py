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
    palabra dentro de un string ("Sin plan") o de un comentario no cuenta como uso."""
    texto = _RE_COMENTARIO_BLOQUE.sub(lambda m: " " * len(m.group(0)), texto)
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


def test_c_fidelizacion_declara_el_estado_de_busqueda_antes_del_hook():
    fuente = _fuente(FIDELIZACION)
    assert "const [buscar, setBuscar] = useState('');" in fuente
    assert fuente.index("const [buscar, setBuscar] = useState('');") < fuente.index(
        "const churnQ = useChurn(tenant_id, buscar);")
    assert hallazgos(fuente) == []
