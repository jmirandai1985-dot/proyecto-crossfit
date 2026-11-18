"""Mutation testing ACOTADO de los módulos de pago (Windows, sin fork).

POR QUÉ NO mutmut
-----------------
`mutmut` 3.x exige soporte de `fork`: su propia documentación dice que en
Windows sólo corre dentro de WSL. Este host es Windows nativo (el proyecto se
prueba con `py -3.12` y una base Neon TEST), así que se usa este runner como
equivalente: genera mutaciones con `ast`, aplica UNA por vez, corre pytest y
restaura el archivo. La selección de tests por mutante sale de los contextos de
`coverage` (qué test ejecutó esa línea), así no se corre toda la suite N veces.

Uso (desde `backend/`):

    py -3.12 scripts/mutacion_pagos.py list
    py -3.12 scripts/mutacion_pagos.py run \
        --tests tests/test_cancelar_pago.py tests/test_expirar_pendientes.py \
        --coverage-file _mut/.coverage \
        --json _mut/reporte.json --markdown _mut/reporte.md

El runner NUNCA deja una mutación aplicada: restaura el archivo original en un
`finally` (incluso si pytest se cuelga y se mata el proceso).
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

BACKEND = Path(__file__).resolve().parents[1]

MODULOS_POR_DEFECTO = (
    "app/services/pagos.py",
    "app/services/aprobacion_planes.py",
    "app/services/suscripciones_mp.py",
)

# Tests que se pueden correr con `--noconftest` (docstring de cada archivo:
# usan DB falsa / no tocan red). Evita el coste de conectar a Neon en CADA
# mutante (conftest resuelve alumno/coach/admin con 3 consultas).
TESTS_SIN_CONFTEST = {
    "tests/test_cancelar_pago.py",
    "tests/test_expirar_pendientes.py",
    "tests/test_pago_iniciado_oculto.py",
    "tests/test_pagos_webhook_firma.py",
    "tests/test_pagos_mercadopago_estados.py",
    "tests/test_pagos_boton_front.py",
}

# Estados, conceptos y orígenes que son CONTRATO del negocio (no texto de log).
# Sólo se mutan literales de esta lista: cambiar un mensaje de logger no aporta.
VOCABULARIO = {
    # pagos.estado / solicitudes_planes.estado
    "iniciado", "pendiente", "en_proceso", "aprobado", "rechazado", "cancelado",
    "reembolsado", "expirado", "expirada", "en_cola", "approved", "rejected",
    "pending", "procesado", "desconocido", "duplicado", "aplicado",
    "monto_no_coincide", "ya_procesada", "no_encontrada", "ya_en_cola",
    # suscripciones
    "activo", "inactiva", "vencido", "pausada", "authorized", "paused",
    "cancelled", "scheduled", "processed", "recycling", "suspendida",
    # conceptos / referencias / orígenes / proveedores
    "membresia", "bazar", "solicitud_plan", "pedido", "suscripcion",
    "manual", "mercadopago", "emergencia",
    # resultados de services/suscripciones_mp
    "actualizada", "sin_cambios", "obsoleto", "estado_desconocido",
    "sin_suscripcion", "cobro_registrado", "cobro_actualizado",
    "monto_invalido", "sin_id", "otro_preapproval",
}

OPERADORES_COMPARACION = {
    ast.Eq: ("==", ast.NotEq),
    ast.NotEq: ("!=", ast.Eq),
    ast.Lt: ("<", ast.LtE),
    ast.LtE: ("<=", ast.Lt),
    ast.Gt: (">", ast.GtE),
    ast.GtE: (">=", ast.Gt),
    ast.Is: ("is", ast.IsNot),
    ast.IsNot: ("is not", ast.Is),
    ast.In: ("in", ast.NotIn),
    ast.NotIn: ("not in", ast.In),
}
SIMBOLO_COMPARACION = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
    ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not",
    ast.In: "in", ast.NotIn: "not in",
}


@dataclass
class Mutante:
    id: str
    archivo: str          # ruta relativa a backend/
    linea: int
    columna: int
    funcion: str
    operador: str
    original: str
    mutado: str
    descripcion: str

    def diff(self, texto_original: str, texto_mutado: str) -> str:
        return "".join(difflib.unified_diff(
            texto_original.splitlines(keepends=True),
            texto_mutado.splitlines(keepends=True),
            fromfile=f"a/{self.archivo}", tofile=f"b/{self.archivo}",
            n=2,
        ))

def _offsets(source: bytes) -> list[int]:
    """Offset absoluto en bytes del inicio de cada línea (0-based)."""
    offsets = [0]
    for i, byte in enumerate(source):
        if byte == 0x0A:
            offsets.append(i + 1)
    return offsets


def _offset(offsets: list[int], linea: int, columna: int) -> int:
    return offsets[linea - 1] + columna


def _segmento(source: bytes, node: ast.AST) -> bytes:
    offsets = _offsets(source)
    ini = _offset(offsets, node.lineno, node.col_offset)
    fin = _offset(offsets, node.end_lineno, node.end_col_offset)
    return source[ini:fin]


def _funcion_para(linea: int, funciones: list[tuple[int, int, str]]) -> str:
    candidatas = [f for f in funciones if f[0] <= linea <= f[1]]
    if not candidatas:
        return "<modulo>"
    # la función MÁS INTERNA (rango más chico) es la que contiene la línea
    return min(candidatas, key=lambda f: f[1] - f[0])[2]


def _docstrings(tree: ast.AST) -> set[ast.AST]:
    """Nodos Constant que son docstrings (no se mutan)."""
    nodos: set[ast.AST] = set()

    def _marcar(body):
        if body and isinstance(body[0], ast.Expr):
            valor = body[0].value
            if isinstance(valor, ast.Constant) and isinstance(valor.value, str):
                nodos.add(valor)

    _marcar(getattr(tree, "body", []))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _marcar(getattr(node, "body", []))
    return nodos


def _padres(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    padres: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for hijo in ast.iter_child_nodes(node):
            padres[hijo] = node
    return padres


def _en_logger(node: ast.AST, padres: dict[ast.AST, ast.AST]) -> bool:
    """¿El nodo cuelga de una llamada a logger.* (texto de diagnóstico)?"""
    actual: Optional[ast.AST] = node
    while actual is not None:
        padre = padres.get(actual)
        if isinstance(padre, ast.Call):
            func = padre.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in {"logger", "logging"}:
                    return True
        actual = padre
    return False

def generar_mutantes(archivo: Path, relativo: str) -> list[Mutante]:
    source = archivo.read_bytes()
    texto = source.decode("utf-8")
    tree = ast.parse(texto, filename=str(archivo))
    offsets = _offsets(source)
    padres = _padres(tree)
    docs = _docstrings(tree)
    funciones = [
        (n.lineno, n.end_lineno, n.name)
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    mutantes: list[Mutante] = []

    def _linea_de(offset: int) -> int:
        ini = 0
        while ini + 1 < len(offsets) and offsets[ini + 1] <= offset:
            ini += 1
        return ini + 1

    def _agregar(inicio: int, fin: int, nuevo: bytes, operador: str,
                 descripcion: str) -> None:
        original = source[inicio:fin]
        if original == nuevo:
            return
        linea = _linea_de(inicio)
        mutantes.append(Mutante(
            id=f"{relativo}:{linea}:{len(mutantes) + 1}",
            archivo=relativo,
            linea=linea,
            columna=inicio - offsets[linea - 1],
            funcion=_funcion_para(linea, funciones),
            operador=operador,
            original=original.decode("utf-8", "replace"),
            mutado=nuevo.decode("utf-8", "replace"),
            descripcion=descripcion,
        ))

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                izquierda = node.left if i == 0 else node.comparators[i - 1]
                derecha = node.comparators[i]
                tipo = type(op)
                if tipo not in OPERADORES_COMPARACION:
                    continue
                viejo, nuevo_tipo = OPERADORES_COMPARACION[tipo]
                gap_ini = _offset(offsets, izquierda.end_lineno,
                                  izquierda.end_col_offset)
                gap_fin = _offset(offsets, derecha.lineno, derecha.col_offset)
                gap = source[gap_ini:gap_fin]
                if b"\n" in gap:
                    continue
                # El operador está SIEMPRE entre el fin de la izquierda y el
                # inicio de la derecha; se reemplaza sólo esa aparición.
                pos = gap.find(viejo.encode("utf-8"))
                if pos < 0:
                    continue
                nuevo = SIMBOLO_COMPARACION[nuevo_tipo]
                _agregar(gap_ini + pos, gap_ini + pos + len(viejo.encode("utf-8")),
                         nuevo.encode("utf-8"), "comparacion",
                         f"{viejo} -> {nuevo}")

        elif isinstance(node, ast.BoolOp):
            viejo = "and" if isinstance(node.op, ast.And) else "or"
            nuevo = "or" if isinstance(node.op, ast.And) else "and"
            for i in range(len(node.values) - 1):
                gap_ini = _offset(offsets, node.values[i].end_lineno,
                                  node.values[i].end_col_offset)
                gap_fin = _offset(offsets, node.values[i + 1].lineno,
                                  node.values[i + 1].col_offset)
                gap = source[gap_ini:gap_fin]
                if b"\n" in gap:
                    continue
                pos = gap.find(viejo.encode("utf-8"))
                if pos < 0:
                    continue
                _agregar(gap_ini + pos, gap_ini + pos + len(viejo),
                         nuevo.encode("utf-8"), "booleano", f"{viejo} -> {nuevo}")

        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operando = _segmento(source, node.operand)
            _agregar(_offset(offsets, node.lineno, node.col_offset),
                     _offset(offsets, node.end_lineno, node.end_col_offset),
                     operando.strip(), "negacion", "quita `not`")

        elif isinstance(node, ast.Constant) and node in docs:
            continue

        elif isinstance(node, ast.Constant) and type(node.value) is int:
            if _en_logger(node, padres):
                continue
            _agregar(_offset(offsets, node.lineno, node.col_offset),
                     _offset(offsets, node.end_lineno, node.end_col_offset),
                     str(node.value + 1).encode("utf-8"), "entero",
                     f"{node.value} -> {node.value + 1}")

        elif isinstance(node, ast.Constant) and type(node.value) is bool:
            if _en_logger(node, padres):
                continue
            _agregar(_offset(offsets, node.lineno, node.col_offset),
                     _offset(offsets, node.end_lineno, node.end_col_offset),
                     (b"False" if node.value else b"True"), "booleano_const",
                     f"{node.value} -> {not node.value}")

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in VOCABULARIO:
                continue
            if _en_logger(node, padres):
                continue
            if isinstance(padres.get(node), ast.JoinedStr):
                continue
            _agregar(_offset(offsets, node.lineno, node.col_offset),
                     _offset(offsets, node.end_lineno, node.end_col_offset),
                     b'"__MUTANTE__"', "estado_str",
                     f"{node.value!r} -> '__MUTANTE__'")

    vistos = set()
    unicos = []
    for m in mutantes:
        clave = (m.linea, m.columna, m.original, m.mutado)
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(m)
    return unicos

def _normalizar_contextos(coverage_file: Path) -> dict[str, dict[int, set[str]]]:
    """{archivo_absoluto: {linea: {contextos}}} desde el .coverage de pytest-cov."""
    try:
        from coverage import Coverage
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Falta `coverage`. Instalalo en el entorno de TEST: "
            "py -3.12 -m pip install --user coverage pytest-cov"
        ) from exc
    cov = Coverage(data_file=str(coverage_file))
    cov.load()
    data = cov.get_data()
    salida: dict[str, dict[int, set[str]]] = {}
    for archivo in data.measured_files():
        try:
            ctx = data.contexts_by_lineno(archivo)
        except Exception:
            continue
        # Clave RELATIVA (app/services/...), no absoluta: así el mismo
        # `.coverage` sirve tanto en backend/ como en una copia para correr
        # mutantes sin tocar el árbol que usa el servidor de TEST.
        partes = Path(archivo).parts
        clave = "/".join(partes[-3:]) if len(partes) >= 3 else str(archivo)
        salida[clave.replace("\\", "/")] = {
            int(linea): {c for c in contextos if c} for linea, contextos in ctx.items()
        }
    return salida


def _nodeids_para(mutante: Mutante, contextos: dict[str, dict[int, set[str]]],
                  tests_permitidos: list[str]) -> list[str]:
    por_linea = contextos.get(mutante.archivo.replace("\\", "/"), {})
    candidatos = set(por_linea.get(mutante.linea, set()))
    permitidos = {t.replace("\\", "/") for t in tests_permitidos}
    elegidos = []
    for ctx in candidatos:
        normalizado = ctx.replace("\\", "/")
        if any(normalizado == p or normalizado.startswith(p + "::") for p in permitidos):
            elegidos.append(ctx)
    return sorted(set(elegidos))


def _correr_seleccion(python: str, nodeids: list[str], timeout: int,
                      cwd: Path, noconftest: bool) -> tuple[str, str]:
    """Corre los nodeids UNO por uno hasta que alguno mate el mutante.

    La selección por coverage ya es mínima; correr uno por vez evita pagar la
    suite completa cuando el primer test relevante falla (el caso normal).
    """
    salida = ""
    for nodeid in nodeids:
        estado, out = _correr_pytest(python, [nodeid], timeout, cwd, noconftest)
        salida += f"\n### {nodeid}\n{out}"
        if estado in ("killed", "timeout"):
            return estado, salida
    return "survived", salida


def _escribir_atomico(archivo: Path, contenido: bytes) -> None:
    """Escribe con archivo temporal + replace: si el proceso muere a mitad,
    el original NO queda truncado (lección de la primera pasada)."""
    tmp = archivo.with_name(archivo.name + ".muttmp")
    tmp.write_bytes(contenido)
    try:
        os.replace(tmp, archivo)
    except PermissionError:
        # En Windows el servidor uvicorn --reload puede tener el archivo abierto
        # sin FILE_SHARE_DELETE y el rename falla. Se escribe in-place (el
        # `.mutbak` sigue siendo la red de seguridad si el proceso muere).
        archivo.write_bytes(contenido)
        tmp.unlink(missing_ok=True)


def _backup(archivo: Path) -> Path:
    bak = archivo.with_name(archivo.name + ".mutbak")
    if not bak.exists():
        bak.write_bytes(archivo.read_bytes())
    return bak


def _restaurar_backup(archivo: Path) -> bool:
    bak = archivo.with_name(archivo.name + ".mutbak")
    if not bak.exists():
        return False
    _escribir_atomico(archivo, bak.read_bytes())
    bak.unlink()
    return True


def _limpiar_pycache(archivo: Path) -> None:
    pycache = archivo.parent / "__pycache__"
    if not pycache.exists():
        return
    for pyc in pycache.glob(archivo.stem + ".*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def _correr_pytest(python: str, nodeids: list[str], timeout: int,
                   cwd: Path, noconftest: bool = False) -> tuple[str, str]:
    cmd = [python, "-m", "pytest", "-q", "-x", "--no-header",
           "-p", "no:cacheprovider", *nodeids]
    if noconftest:
        cmd.insert(3, "--noconftest")
    env = dict(os.environ)
    env["ENVIRONMENT"] = "test"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
            timeout=timeout,
        )
        return ("killed" if proc.returncode else "survived",
                (proc.stdout + proc.stderr)[-4000:])
    except subprocess.TimeoutExpired as exc:
        salida = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(salida, bytes):
            salida = salida.decode("utf-8", "replace")
        return "timeout", salida[-4000:]


def _aplicar(archivo: Path, original: bytes, mutante: Mutante) -> bytes:
    """Devuelve el contenido mutado y lo escribe en disco."""
    offsets = _offsets(original)
    ini = _offset(offsets, mutante.linea, mutante.columna)
    fin = ini + len(mutante.original.encode("utf-8"))
    if original[ini:fin] != mutante.original.encode("utf-8"):
        raise RuntimeError(
            f"No coincide el segmento a mutar en {mutante.archivo}:"
            f"{mutante.linea}:{mutante.columna} ({original[ini:fin]!r} != "
            f"{mutante.original!r})")
    mutado = original[:ini] + mutante.mutado.encode("utf-8") + original[fin:]
    _escribir_atomico(archivo, mutado)
    return mutado


def _resumen_md(reporte: dict) -> str:
    lineas = [
        "# Reporte de mutation testing — módulos de pago",
        "",
        f"- **Generado:** {reporte['generado']}",
        f"- **Runner:** `{reporte['runner']}`",
        f"- **Mutantes generados:** {reporte['totales']}",
        f"- **Muertos:** {reporte['muertos']}",
        f"- **Sobrevivientes:** {reporte['sobrevivientes']}",
        f"- **Timeouts:** {reporte['timeouts']}",
        f"- **Sin cobertura (ningún test ejecutó la línea):** "
        f"{reporte['sin_cobertura']}",
        "",
        "## Por archivo",
        "",
        "| Archivo | Generados | Muertos | Sobrevivientes | Timeouts | Sin cobertura |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for archivo, datos in sorted(reporte["por_archivo"].items()):
        lineas.append(
            f"| `{archivo}` | {datos['totales']} | {datos['muertos']} | "
            f"{datos['sobrevivientes']} | {datos['timeouts']} | "
            f"{datos['sin_cobertura']} |")
    lineas += ["", "## Sobrevivientes", ""]
    for m in reporte["detalle_sobrevivientes"]:
        if m["estado"] != "survived":
            continue
        lineas += [
            f"### `{m['archivo']}:{m['linea']}` · `{m['funcion']}` · "
            f"{m['operador']}",
            "",
            f"- Cambio: `{m['original']}` → `{m['mutado']}` ({m['descripcion']})",
            f"- Tests que ejecutaron esa línea y NO la mataron: "
            f"{', '.join(m['tests_que_cubren']) or '(ninguno)'}",
            "",
            "```diff",
            m["diff"].rstrip(),
            "```",
            "",
        ]
    sin_cob = [m for m in reporte["detalle_sobrevivientes"]
               if m["estado"] == "sin_cobertura"]
    if sin_cob:
        lineas += ["## Sin cobertura (no ejecutadas por ningún test)", ""]
        for m in sin_cob:
            lineas.append(
                f"- `{m['archivo']}:{m['linea']}` · `{m['funcion']}` · "
                f"{m['operador']} · `{m['original']}` → `{m['mutado']}`")
        lineas.append("")


def cmd_list(args: argparse.Namespace) -> int:
    total = 0
    for relativo in args.modules:
        archivo = BACKEND / relativo
        mutantes = generar_mutantes(archivo, relativo)
        total += len(mutantes)
        print(f"{relativo}: {len(mutantes)} mutantes")
        for m in (mutantes[:args.limit] if args.limit else mutantes):
            print(f"  {m.linea:>5} {m.funcion:<45} {m.operador:<15} "
                  f"{m.original!r} -> {m.mutado!r}")
    print(f"TOTAL: {total}")


def cmd_run(args: argparse.Namespace) -> int:
    tests = [t.replace("\\", "/") for t in args.tests]
    faltantes = [t for t in tests if not (BACKEND / t).exists()]
    if faltantes:
        raise SystemExit(f"No existen estos tests: {faltantes}")

    # Si una corrida anterior murió a mitad, el archivo quedó con la mutación:
    # se recupera del .mutbak ANTES de generar los mutantes.
    for relativo in args.modules:
        archivo = BACKEND / relativo
        if _restaurar_backup(archivo):
            print(f"[recuperado] {relativo} desde {archivo.name}.mutbak")

    contextos: dict[str, dict[int, set[str]]] = {}
    if args.coverage_file:
        ruta_cov = Path(args.coverage_file)
        if not ruta_cov.is_absolute():
            ruta_cov = BACKEND / ruta_cov
        if not ruta_cov.exists():
            raise SystemExit(f"No existe el archivo de coverage: {ruta_cov}")
        contextos = _normalizar_contextos(ruta_cov)
        print(f"coverage: {len(contextos)} archivos medidos")

    mutantes: list[Mutante] = []
    for relativo in args.modules:
        mutantes.extend(generar_mutantes(BACKEND / relativo, relativo))
    if args.lineas:
        wanted = {int(x) for x in args.lineas.split(",") if x.strip()}
        mutantes = [m for m in mutantes if m.linea in wanted]
    if args.max_mutantes:
        mutantes = mutantes[:args.max_mutantes]
    print(f"mutantes a correr: {len(mutantes)}", flush=True)

    originales = {m.archivo: (BACKEND / m.archivo).read_bytes()
                  for m in mutantes}
    for relativo in originales:
        _backup(BACKEND / relativo)
    por_archivo: dict[str, dict[str, int]] = defaultdict(
        lambda: {"totales": 0, "muertos": 0, "sobrevivientes": 0,
                 "timeouts": 0, "sin_cobertura": 0})
    detalle = []
    muertos = timeouts = sin_cob = sobrevivientes = 0
    inicio = time.time()

    try:
        for numero, m in enumerate(mutantes, start=1):
            archivo = BACKEND / m.archivo
            original = originales[m.archivo]
            por_archivo[m.archivo]["totales"] += 1
            nodeids = _nodeids_para(m, contextos, tests) if contextos else []

            if contextos and not nodeids:
                estado, salida = "sin_cobertura", ""
            else:
                a_correr = nodeids if nodeids else tests
                noconftest = all(
                    f in TESTS_SIN_CONFTEST
                    for f in {n.split("::", 1)[0] for n in a_correr})
                _aplicar(archivo, original, m)
                _limpiar_pycache(archivo)
                if nodeids and len(nodeids) <= 40:
                    estado, salida = _correr_seleccion(
                        args.python, a_correr, args.timeout, BACKEND, noconftest)
                else:
                    if len(a_correr) > 60:
                        a_correr = sorted({n.split("::", 1)[0] for n in a_correr})
                    estado, salida = _correr_pytest(
                        args.python, a_correr, args.timeout, BACKEND, noconftest)
                _escribir_atomico(archivo, original)

            print(f"[{numero}/{len(mutantes)}] {m.archivo}:{m.linea} "
                  f"{m.funcion} · {m.operador} · {m.original!r}->"
                  f"{m.mutado!r} => {estado.upper()}", flush=True)

            if estado == "killed":
                muertos += 1
                por_archivo[m.archivo]["muertos"] += 1
                continue
            if estado == "timeout":
                timeouts += 1
                por_archivo[m.archivo]["timeouts"] += 1
            elif estado == "sin_cobertura":
                sin_cob += 1
                por_archivo[m.archivo]["sin_cobertura"] += 1
            else:
                sobrevivientes += 1
                por_archivo[m.archivo]["sobrevivientes"] += 1

            original_txt = original.decode("utf-8", "replace")
            detalle.append({
                **asdict(m),
                "estado": estado,
                "diff": m.diff(original_txt, _texto_mutado(original, m)),
                "tests_que_cubren": sorted({
                    n.split("::", 1)[0] for n in nodeids}),
                "nodeids_que_cubren": nodeids,
                "salida": salida,
            })

            if args.limit and numero >= args.limit:
                break
    finally:
        for relativo, contenido in originales.items():
            _escribir_atomico(BACKEND / relativo, contenido)
            bak = BACKEND / (relativo + ".mutbak")
            if bak.exists():
                bak.unlink()
            _limpiar_pycache(BACKEND / relativo)

    reporte = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "runner": "scripts/mutacion_pagos.py (AST + pytest; equivalente en "
                  "Windows a mutmut, que exige fork/WSL)",
        "modulos": list(args.modules),
        "tests": tests,
        "coverage_file": args.coverage_file,
        "duracion_segundos": round(time.time() - inicio, 1),
        "totales": len(mutantes),
        "muertos": muertos,
        "sobrevivientes": sobrevivientes,
        "timeouts": timeouts,
        "sin_cobertura": sin_cob,
        "por_archivo": dict(por_archivo),
        "detalle_sobrevivientes": detalle,
    }
    for campo in ("json", "markdown"):
        destino = getattr(args, campo)
        if not destino:
            continue
        ruta = Path(destino)
        if not ruta.is_absolute():
            ruta = BACKEND / ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if campo == "json":
            ruta.write_text(json.dumps(reporte, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        else:
            ruta.write_text(_resumen_md(reporte), encoding="utf-8")
        print(f"{campo.upper()}: {ruta}")

    print(f"\nTOTAL={reporte['totales']} MUERTOS={muertos} "
          f"SOBREVIVIENTES={sobrevivientes} TIMEOUTS={timeouts} "
          f"SIN_COBERTURA={sin_cob} ({reporte['duracion_segundos']}s)")
    return 0


def _texto_mutado(original: bytes, mutante: Mutante) -> str:
    offsets = _offsets(original)
    ini = _offset(offsets, mutante.linea, mutante.columna)
    fin = ini + len(mutante.original.encode("utf-8"))
    return (original[:ini] + mutante.mutado.encode("utf-8")
            + original[fin:]).decode("utf-8", "replace")



def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comando", choices=("list", "run"))
    parser.add_argument("--modules", nargs="+", default=list(MODULOS_POR_DEFECTO))
    parser.add_argument("--tests", nargs="+", default=[])
    parser.add_argument("--coverage-file", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--markdown", default=None)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-mutantes", type=int, default=0)
    parser.add_argument("--lineas", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--segunda-pasada", action="store_true")
    args = parser.parse_args(argv)
    if args.comando == "list":
        return cmd_list(args)
    if not args.tests:
        raise SystemExit("`run` necesita --tests (archivos de test)")
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())

