"""Bloque D: los textos de la app hablan de TÚ (no de voseo).

Qué cubre
---------
1. Ningún archivo de `frontend/src` ni de `backend/app` tiene una forma de voseo de la lista
   curada (presente: `tenés`, `podés`, `querés`…; imperativos: `revisá`, `ingresá`, `considerá`…;
   imperativos con clítico: `contactalo`, `avisame`, `decile`…). Es el GUARD del bloque: una
   pantalla o un correo nuevo no puede volver al voseo sin que el run se ponga rojo.
2. El barrido NO es vacío: recorre los dos árboles y encuentra los archivos esperados.
3. Los textos que ya se arreglaron quedan FIJADOS (el asunto del correo de acompañamiento y el
   aviso de la solicitud rechazada): un copy-paste viejo los revive y el test lo dice.

⚠️ La lista `VOSEO` está escrita EN VOSEO a propósito (son las formas PROHIBIDAS): si algún día
se pasa un script de reemplazo por el repo, este archivo tiene que quedar afuera o la lista se
"corrige" a tuteo y el guard deja de detectar nada.

No necesita BD ni API: lee los archivos. No se gatean `backend/scripts` ni `docs/` (herramientas
y notas de desarrollo, también pasadas a tuteo pero fuera del producto).
"""
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
RAIZ = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

RAICES = (("frontend", "src"), ("backend", "app"))
SUFIJOS = (".jsx", ".js", ".py")

# Lista curada: SÓLO formas que en tuteo no existen. Quedan afuera las que son válidas en las
# dos variantes ("estás", "sé", "acá", "así") y los adverbios terminados en -á ("demás").
VOSEO = (
    # Presente
    "vos", "sos", "tenés", "tenes", "podés", "podes", "querés", "queres", "sabés",
    "venís", "hacés", "sentís", "decís", "elegís", "vivís", "debés", "salís", "ponés",
    "traés", "andás", "pensás", "seguís", "pedís", "conocés", "volvés", "construís",
    "creés", "llevás", "necesitás", "usás", "respondés",
    # Imperativos
    "considerá", "revisá", "agregá", "ingresá", "reservá", "coordiná", "probá", "cargá",
    "completá", "guardá", "cerrá", "buscá", "cambiá", "pasá", "registrá", "seleccioná",
    "esperá", "dejá", "llevá", "usá", "mandá", "empezá", "mirá", "creá", "avisá", "anotá",
    "actualizá", "ajustá", "asigná", "destildá", "entrá", "quitá", "reconfirmá",
    "reentrená", "renová", "agendá", "hablá", "marcá", "contactá", "escaneá", "confirmá",
    "recordá", "retomá",
    # Imperativos en -í/-é
    "corregí", "escribí", "definí", "elegí", "seguí", "reponé", "corré", "subí", "volvé",
    "vení", "decí", "hacé", "poné", "andá",
    # Imperativo + clítico
    "fijate", "anotate", "sumate", "tomate", "acordate", "olvidate", "movete", "quedate",
    "cuidate", "llevate", "divertite", "conectate", "escribinos", "contanos", "llamanos",
    "decime", "contame", "contactalo", "contactala", "contactame", "avisame", "decile",
    "contale", "avisale", "mostrale", "mandale", "pedile", "pasale", "escribime",
)
PATRON = re.compile(r"\b(" + "|".join(sorted(set(VOSEO), key=len, reverse=True)) + r")\b",
                    re.IGNORECASE)


def _archivos():
    """(ruta, texto) de cada archivo de código del producto."""
    for partes in RAICES:
        raiz = RAIZ.joinpath(*partes)
        assert raiz.is_dir(), f"no existe {raiz}"
        for p in sorted(raiz.rglob("*")):
            if p.suffix not in SUFIJOS or "node_modules" in str(p):
                continue
            yield p, p.read_text(encoding="utf-8", errors="replace")


def test_a1_el_barrido_lee_el_codigo_de_verdad():
    """Prueba NO vacua: si la ruta no encontrara archivos, el test pasaría sin mirar nada."""
    archivos = list(_archivos())
    assert len(archivos) > 100, f"sólo se leyeron {len(archivos)} archivos"

    nombres = {p.name for p, _ in archivos}
    for esperado in ("App.jsx", "MisReservas.jsx", "email_service.py",
                     "fidelizacion_plantillas.py"):
        assert esperado in nombres, f"el barrido no ve {esperado}"


def test_a2_no_queda_voseo_en_el_producto():
    """Ninguna pantalla, aviso ni correo del producto habla de voseo."""
    hallazgos = []
    for ruta, texto in _archivos():
        for i, linea in enumerate(texto.splitlines(), 1):
            encontrados = PATRON.findall(linea)
            if encontrados:
                hallazgos.append(f"{ruta}:{i}: [{','.join(sorted(set(encontrados)))}] "
                                 f"{linea.strip()[:120]}")

    assert not hallazgos, (
        "quedó voseo (el producto habla de tú):\n" + "\n".join(hallazgos[:20]))


@pytest.mark.parametrize("texto", [
    # El asunto del correo de acompañamiento (antes: "¿Cómo vienes…? Cuéntame").
    "vienes",
    "Cuéntame",
    # El aviso del login con la cuenta rechazada (antes: "Contacta al box").
    "Contacta al box",
    # El mensaje de la clase de prueba cuando el correo no sale.
    "Usa la contraseña de abajo",
])
def test_a3_los_textos_ya_arreglados_quedan_fijados(texto):
    """El texto nuevo tiene que seguir estando: el test no sólo mira que NO haya voseo."""
    archivos = [p for p, t in _archivos() if texto in t]
    assert archivos, f"desapareció el texto en tuteo: {texto!r}"


def test_a4_los_correos_de_fidelizacion_salen_en_tuteo():
    """El copy de los correos (no sólo el asunto) tampoco puede volver al voseo."""
    from app.services import email_service

    asunto_riesgo, html_riesgo = email_service.render_email_riesgo_alto("Ana Pérez", 45)
    _, html_larga = email_service.render_email_fidelizacion_larga("Ana Pérez", 40, True)

    for html in (html_riesgo, html_larga):
        assert not PATRON.search(html), "un correo de Fidelización volvió al voseo"
    assert not PATRON.search(asunto_riesgo)
    assert "vienes" in asunto_riesgo, "el asunto quedó en tuteo: ¿Cómo vienes…?"
    assert "no tienes un plan vigente" in html_larga, "la frase de la renovación quedó en tuteo"
