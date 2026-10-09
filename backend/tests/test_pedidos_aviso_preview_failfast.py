"""Vista previa del aviso de retiro: NO puede colgarse (bug de PROD).

Síntoma reportado: "Avisar al comprador" se quedaba en "Pendiente" para siempre y el modal
nunca cargaba. Dos causas, las dos cubiertas acá:

  A. BACKEND — el handler abría una SEGUNDA conexión a la BD (`SessionLocal()` dentro de
     `contacto_del_box`) mientras el request ya tenía la suya de `get_db`. Ese checkout
     extra esperando el pool es lo que no respondía. Ahora el render REUTILIZA la sesión
     del request y cualquier fallo se convierte en un 502 CON MENSAJE (nada sin respuesta).
  B. FRONT — la hoja hacía `await api.get(...)` sin plazo: si el backend no contestaba,
     giraba para siempre. Ahora la petición corre contra un reloj (`utils/avisoRetiro.js`)
     y, si vence, muestra el motivo + "Reintentar".

Tests AISLADOS (sin red, sin base de datos): reglas, cableado y el comportamiento real del
handler con dobles (se lo llama directo, sin TestClient).

Correr:
    cd backend && py -3.12 -m pytest tests/test_pedidos_aviso_preview_failfast.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from app.api.v1 import pedidos as pedidos_mod
    from app.services import email_service
except Exception as exc:   # pragma: no cover - entorno sin dependencias del backend
    pytest.skip(f"no se pudo importar el router de pedidos: {exc}",
                allow_module_level=True)

RAIZ = Path(__file__).resolve().parents[2]
PEDIDOS = "backend/app/api/v1/pedidos.py"
FRONT = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
UTIL_AVISO = "frontend/src/utils/avisoRetiro.js"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _bloque(fuente: str, desde: str, hasta: str) -> str:
    """El texto entre dos marcas (hasta el final del archivo si la marca no está)."""
    inicio = fuente.index(desde)
    final = fuente.find(hasta, inicio)
    return fuente[inicio:] if final == -1 else fuente[inicio:final]



# ── Dobles ───────────────────────────────────────────────────────────────────

class _ConsultaFalsa:
    """`db.query(X).filter(...).first()` con una fila fija (o None)."""

    def __init__(self, fila):
        self._fila = fila

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._fila


class _DbFalsa:
    """Sesión de mentira: registra que se consultó y devuelve SIEMPRE la misma fila."""

    def __init__(self, fila=None):
        self.fila = fila
        self.consultas = 0
        self.cerrada = False

    def query(self, *a, **k):
        self.consultas += 1
        return _ConsultaFalsa(self.fila)

    def close(self):
        self.cerrada = True


def _pedido(**kwargs):
    base = {"id": 7, "cantidad": 1, "codigo_retiro": "UB-WK3D",
            "estado": "validado", "entregado_en": None, "updated_at": None}
    base.update(kwargs)
    return SimpleNamespace(**base)


_ALUMNO = SimpleNamespace(id=42, nombre="Alumno Demo", correo="demo@test.local")


# ── A. El render NO abre una segunda conexión ────────────────────────────────

def test_a1_contacto_del_box_reutiliza_la_sesion_prestada():
    """Con `db=` NO se abre otra sesión: es el checkout extra que colgaba el preview."""
    abiertas = []

    def SessionLocalFalsa():
        abiertas.append(1)
        return _DbFalsa(SimpleNamespace(whatsapp="+56 9 1234 5678"))

    import app.db.database as database
    original = database.SessionLocal
    database.SessionLocal = SessionLocalFalsa
    prestada = _DbFalsa(SimpleNamespace(whatsapp="+56 9 1234 5678"))
    try:
        numero = email_service.contacto_del_box(tenant_id=1, db=prestada)
    finally:
        database.SessionLocal = original

    assert numero == "+56 9 1234 5678"
    assert abiertas == [], "no debe abrir una segunda sesión cuando se la prestan"
    assert prestada.cerrada is False, "la sesión del request la cierra su dueño"


def test_a2_contacto_del_box_sin_db_sigue_abriendo_la_suya():
    """Compatibilidad: el scheduler y `_enviar` NO pasan `db` y siguen funcionando."""
    creadas = []

    def SessionLocalFalsa():
        sesion = _DbFalsa(SimpleNamespace(whatsapp="+56 9 0000 0000"))
        creadas.append(sesion)
        return sesion

    import app.db.database as database
    original = database.SessionLocal
    database.SessionLocal = SessionLocalFalsa
    try:
        numero = email_service.contacto_del_box(tenant_id=1)
    finally:
        database.SessionLocal = original

    assert numero == "+56 9 0000 0000"
    assert len(creadas) == 1, "sin `db` el helper abre la suya"
    assert creadas[0].cerrada is True, "y la cierra él (no la deja colgada)"


def test_a3_el_preview_pasa_la_db_del_request_al_render(monkeypatch):
    """El preview le entrega su propia sesión a `render_con_contacto`."""
    visto = {}

    def espia(html, tenant_id=None, db=None):
        visto["tenant_id"] = tenant_id
        visto["db"] = db
        return html + "<!--pie-->"

    monkeypatch.setattr(pedidos_mod, "_pedido_para_avisar",
                        lambda db, cu, pid: (_pedido(), _ALUMNO, "Poleras"))
    monkeypatch.setattr(pedidos_mod, "render_con_contacto", espia)
    monkeypatch.setattr(pedidos_mod, "ultimo_aviso_manual",
                        lambda db, tenant_id, ids: {})

    sesion = object()
    datos = pedidos_mod.preview_aviso_retiro(
        pedido_id=7, db=sesion,
        current_user={"tenant_id": 3, "usuario_id": 1})

    assert visto["db"] is sesion, "el render tiene que recibir la sesión del request"
    assert visto["tenant_id"] == 3
    assert datos["html"].endswith("<!--pie-->")
    assert datos["codigo_retiro"] == "UB-WK3D"


def test_a4_ningun_endpoint_de_pedidos_abre_su_propia_sesion():
    """Guard general: el router de pedidos no puede tener un `SessionLocal()` suelto."""
    assert "SessionLocal()" not in _fuente(PEDIDOS)


def test_a5_los_otros_previews_tambien_pasan_la_db():
    """Mismo defecto (y mismo fix) en los previews hermanos."""
    for relativa in ("backend/app/api/v1/admin.py",
                     "backend/app/api/v1/fidelizacion.py",
                     "backend/app/services/fidelizacion_plantillas.py"):
        fuente = _fuente(relativa)
        assert "render_con_contacto(" in fuente
        assert "db=db" in fuente, f"{relativa}: el render tiene que reutilizar la sesión"


# ── A. Y si el render falla, responde CON MENSAJE (nunca sin respuesta) ──────

def test_a6_si_el_render_falla_el_preview_devuelve_un_502_visible(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(pedidos_mod, "_pedido_para_avisar",
                        lambda db, cu, pid: (_pedido(), _ALUMNO, "Poleras"))

    def explota(*a, **k):
        raise RuntimeError("boom del pooler")

    monkeypatch.setattr(pedidos_mod, "render_con_contacto", explota)

    with pytest.raises(HTTPException) as info:
        pedidos_mod.preview_aviso_retiro(
            pedido_id=7, db=object(),
            current_user={"tenant_id": 3, "usuario_id": 1})

    assert info.value.status_code == 502
    assert "Reintentá" in info.value.detail, "el modal necesita un motivo legible"


def test_a7_el_preview_envuelve_el_render_en_try_except():
    fuente = _fuente(PEDIDOS)
    preview = _bloque(fuente, "def preview_aviso_retiro", "\n@router.")
    assert "try:" in preview
    assert "except Exception" in preview
    assert "HTTPException" in preview
    assert "db=db" in preview


# ── B. La hoja del front nunca queda girando ─────────────────────────────────

def test_b1_el_front_pide_el_preview_con_plazo():
    fuente = _fuente(FRONT)
    assert "cargarPreviewAviso(" in fuente
    assert "/aviso-retiro/preview`)" in fuente     # la URL real sigue intacta


def test_b2_la_hoja_ofrece_reintentar_con_el_mismo_pedido():
    fuente = _fuente(FRONT)
    assert "Reintentar" in fuente
    assert "abrirAviso(aviso.pedido)" in fuente


def test_b3_el_helper_compromete_un_desenlace():
    util = _fuente(UTIL_AVISO)
    # El reloj contra la petición: pase lo que pase, la promesa se resuelve.
    assert "Promise.race" in util
    assert "clearTimeout" in util
    assert "esTimeout" in util
    # Y NO rechaza: devuelve el mismo contrato siempre.
    assert "ok: false" in util and "ok: true" in util
