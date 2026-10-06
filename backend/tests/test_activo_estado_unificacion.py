"""T12 (Fase 2): `usuarios.activo` ya NO se lee — la fuente de verdad es `usuarios.estado`.

Contexto: el CHECK `ck_usuarios_activo_estado` de la migración 034 obliga a que
`activo = (estado = 'activo')`, así que leer `activo` era una SEGUNDA forma de decir lo mismo
(el diagnóstico está en `docs/ACTIVO_VS_ESTADO.md`). T12 migró las LECTURAS a `estado`.

Qué fija este archivo (guard de FUENTE: grep sobre los .py del repo, sin red y sin base):

  A. Ninguna consulta de producción (`backend/app`, `backend/maintenance`, `backend/scripts`)
     filtra usuarios por la columna `activo`: ni por ORM (`Usuario.activo == ...`) ni por SQL
     crudo (`u.activo`, `usuarios ... activo = true`). Se lee `estado = 'activo'`. Quedan sólo
     las 3 excepciones documentadas en `PERMITIDAS` (ver su comentario).
  B. Los DETECTORES DE CONTRADICCIÓN siguen leyendo las dos columnas: son la única razón
     legítima para mirar `activo` (A.1(a) de mantenimiento y del seed anual).
  C. La API sigue EXPONIENDO `activo` y el front lo CONSUME. Es a propósito: la Fase 3 del doc
     (dejar de exponerlo) NO está lista. Si C falla porque alguien ya migró el front, entonces
     SÍ se puede sacar la clave de la respuesta — y hay que actualizar este test con eso.
  D. Los escritores siguen escribiendo los DOS campos (el CHECK lo exige): `alumnos.py`,
     `usuarios.py` y los dos SQL crudos.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_activo_estado_unificacion.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
DIRS = ("backend/app", "backend/maintenance", "backend/scripts")

# ── Excepciones: usos de la columna cruda que SON correctos y están justificados ────────────
# (archivo, fragmento de la línea). El test las exige presentes: si desaparecen, el allowlist
# quedó obsoleto y hay que borrar la entrada.
PERMITIDAS = (
    # El script de prueba LEE el par para imprimirlo en su verificación final (no decide nada).
    ("backend/scripts/seed_usuarios_prueba.py", "u.activo, u.estado"),
    # Escritor del par en TEST: `SET activo=true` a secas fallaba el CHECK si el usuario no
    # estaba ya en `estado='activo'` (ver el comentario en el propio script).
    ("backend/scripts/aplicar_overrides_test.py", "activo=true WHERE id=7"),
    # Escritor del par en el diseño de mantenimiento: los dos campos juntos, como pide el CHECK.
    ("backend/maintenance/mantenimiento_cloud.py",
     "SET estado = 'rechazado', activo = false"),
)

# Filtros por la bandera heredada. `Usuario.activo` sólo importa comparado (`== True`): las
# LECTURAS para la respuesta de la API (`"activo": usuario.activo`) son contrato, no filtro.
RE_ORM = re.compile(r"Usuario\.activo\s*[=!]=")
RE_SQL_U = re.compile(r"u\.activo\b")
RE_SQL_USUARIOS = re.compile(r"usuarios[^\n]{0,140}\bactivo\s*=\s*(?:true|false)")


def _texto(relativa: str) -> str:
    """Fuente de un archivo (con `errors='replace'`: hay archivos con mojibake preexistente)."""
    return (RAIZ / relativa).read_text(encoding="utf-8", errors="replace")


def _lineas(relativa: str):
    for n, linea in enumerate(_texto(relativa).splitlines(), start=1):
        yield n, linea


def _archivos_py():
    for d in DIRS:
        for p in sorted((RAIZ / d).rglob("*.py")):
            yield p.relative_to(RAIZ).as_posix()


def _permitida(relativa: str, linea: str) -> bool:
    return any(relativa == f and frag in linea for f, frag in PERMITIDAS)


def _es_comentario(linea: str) -> bool:
    """Un comentario (`#`) o un comentario SQL (`--`) no filtra nada: no cuenta como uso."""
    s = linea.strip()
    return s.startswith("#") or s.startswith("--")


def test_a_ninguna_consulta_de_produccion_filtra_usuarios_por_activo():
    hallazgos = []
    for rel in _archivos_py():
        for n, linea in _lineas(rel):
            if _es_comentario(linea) or _permitida(rel, linea):
                continue
            if RE_ORM.search(linea) or RE_SQL_U.search(linea) or RE_SQL_USUARIOS.search(linea):
                hallazgos.append(f"{rel}:{n}: {linea.strip()}")
    assert hallazgos == [], "quedan filtros por `usuarios.activo` (usar `estado = 'activo'`):\n" + \
        "\n".join(hallazgos)


def test_a2_el_allowlist_sigue_vigente():
    """Las 3 excepciones existen y cada una sigue siendo la MISMA linea justificada."""
    for rel, frag in PERMITIDAS:
        assert frag in _texto(rel), f"{rel} ya no contiene «{frag}»: borrar la entrada"


def test_b_los_detectores_de_contradiccion_siguen_mirando_las_dos_columnas():
    """A.1(a) es el UNICO consumidor legitimo de la columna cruda: compara `activo` con `estado`.

    Sin el, un par descuadrado (base sin el CHECK de la 034) pasaria desapercibido.
    """
    assert "activo <> (estado = 'activo')" in _texto("backend/maintenance/mantenimiento_cloud.py")
    assert 'a["activo"] != (a["estado"] == "activo")' in _texto(
        "backend/scripts/seed_anual_prod.py")


def test_c_la_api_sigue_exponiendo_activo_y_el_front_lo_consume():
    """Fase 3 NO esta lista: `activo` sale en las respuestas y el front lo usa de verdad."""
    # 1) La API lo devuelve (dependencia del login, listado/ficha de alumnos y ficha del historial).
    assert '"activo": usuario.activo' in _texto("backend/app/core/dependencies.py")
    assert '"activo": usuario.activo' in _texto("backend/app/api/v1/alumnos.py")
    assert '"activo": bool(alumno.activo)' in _texto(
        "backend/app/services/historial_alumno_service.py")
    # 2) El front lo lee: la ficha marca el CONFLICTO `estado='activo'` + `activo=false`, y el
    #    listado lo usa como respaldo cuando la respuesta vieja no trae `estado`.
    ficha = _texto("frontend/src/components/AlumnoFichaModal.jsx")
    assert "est === 'activo' && !d.activo" in ficha
    assert "est === 'activo' || d.activo" in ficha
    assert "alumno.activo" in _texto("frontend/src/pages/admin/Alumnos.jsx")


def test_d_los_escritores_escriben_estado_y_activo_juntos():
    """El CHECK rechaza cualquier par descuadrado => quien toca uno tiene que tocar el otro."""
    alumnos = _texto("backend/app/api/v1/alumnos.py")
    assert "usuario.activo = True" in alumnos and 'usuario.estado = "activo"' in alumnos
    assert 'usuario.estado = "rechazado"' in alumnos and "usuario.activo = False" in alumnos
    usuarios = _texto("backend/app/api/v1/usuarios.py")
    assert 'usuario.estado = "baja"' in usuarios and "usuario.activo = False" in usuarios

