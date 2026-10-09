"""`GET /membresias/mi-membresia`: los créditos se devuelven TAL CUAL (pueden ser NULL).

Ajuste 2 del bloque. El endpoint inventaba números cuando la fila traía NULL:

    suscripcion.creditos_totales or (16 if plan and not plan.es_ilimitado else 999)

  · plan ILIMITADO con NULL -> 999  (un cupo que no existe: es "∞");
  · plan CON CUPO y NULL    -> 16   (un cupo que nadie cargó).

Ahora responde el valor de la fila (`creditos_totales` / `creditos_disponibles`,
que pueden ser NULL) y el front decide el rótulo: "∞" si `es_ilimitado` y "—" si
el cupo no está cargado. El arreglo de las filas viejas con 999 es de DATOS, no
del endpoint: si la fila dice 999, se devuelve 999 (no se reinterpreta acá).

Sin red y sin base: se llama la función del endpoint con una sesión FALSA.
Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_mi_membresia_creditos.py -q --noconftest
"""
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
RAIZ = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1.membresias import obtener_mi_membresia      # noqa: E402
from app.utils.santiago import ahora_santiago               # noqa: E402

# `suscripciones.fecha_expiracion` es `timestamptz`: instante con zona (UTC en la
# BD), no un `date` pelado. Por eso el fixture usa `ahora_santiago()`, no `date.today()`.
VENCE = ahora_santiago() + timedelta(days=30)


class _SesionFalsa:
    """Sesión mínima: 1ª consulta devuelve la suscripción, 2ª el plan."""

    def __init__(self, suscripcion, plan=None):
        self._filas = [suscripcion, plan]
        self.consultas = 0

    def query(self, modelo):
        padre = self
        indice = self.consultas
        self.consultas += 1

        class _Consulta:
            def filter(self, *args, **kwargs):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def first(self):
                return padre._filas[indice] if indice < len(padre._filas) else None

        return _Consulta()


def _suscripcion(creditos_totales=None, creditos_disponibles=None, plan_id=12):
    return SimpleNamespace(
        plan_id=plan_id,
        creditos_totales=creditos_totales,
        creditos_disponibles=creditos_disponibles,
        fecha_expiracion=VENCE,
        fecha_compra_emergencia=None,
        es_compra_emergencia=False,
    )


def _plan(nombre="King Kong", es_ilimitado=True):
    return SimpleNamespace(id=12, nombre=nombre, es_ilimitado=es_ilimitado)


def _membresia(suscripcion, plan=None):
    return obtener_mi_membresia(
        db=_SesionFalsa(suscripcion, plan),
        current_user={"tenant_id": 1, "usuario_id": 533, "rol": "alumno"},
    )


# ── El caso de producción: plan ilimitado con la fila en NULL ───────────────

def test_plan_ilimitado_con_null_devuelve_null_no_999():
    d = _membresia(_suscripcion(None, None), _plan("King Kong", True))
    assert d["es_ilimitado"] is True
    assert d["clases_totales"] is None, "ilimitado = sin cupo: NULL, nunca el centinela 999"
    assert d["clases_disponibles"] is None
    assert d["clases_usadas"] == 0


def test_plan_con_cupo_y_null_devuelve_null_no_16():
    d = _membresia(_suscripcion(None, None), _plan("Princesa", False))
    assert d["es_ilimitado"] is False
    assert d["clases_totales"] is None, "cupo no cargado: NULL, nunca un 16 inventado"
    assert d["clases_disponibles"] is None


# ── Los valores reales pasan tal cual ───────────────────────────────────────

def test_plan_con_cupo_real_devuelve_sus_numeros():
    d = _membresia(_suscripcion(8, 5), _plan("Super Woman", False))
    assert d["clases_totales"] == 8
    assert d["clases_disponibles"] == 5
    assert d["clases_usadas"] == 3, "usadas = totales - disponibles"


def test_ilimitado_con_999_legacy_lo_devuelve_tal_cual():
    """La fila manda: el endpoint no reinterpreta datos viejos (ese arreglo es de datos)."""
    d = _membresia(_suscripcion(999, 999), _plan("King Kong", True))
    assert d["clases_totales"] == 999
    assert d["clases_disponibles"] == 999


def test_sin_suscripcion_activa_no_cambia():
    d = _membresia(None)
    assert d["activa"] is False
    assert d["clases_totales"] == 0 and d["clases_disponibles"] == 0
    assert d["clases_usadas"] == 0


def test_la_respuesta_conserva_su_contrato():
    d = _membresia(_suscripcion(8, 8), _plan("Super Woman", False))
    assert set(d) == {
        "activa", "plan_nombre", "clases_totales", "clases_disponibles",
        "clases_usadas", "es_ilimitado", "dias_restantes", "fecha_vencimiento",
        "puede_comprar_emergencia", "es_compra_emergencia",
    }


def test_ya_no_queda_ningun_centinela_en_el_archivo():
    fuente = (BACKEND / "app" / "api" / "v1" / "membresias.py").read_text(encoding="utf-8")
    assert "or (16 if plan and not plan.es_ilimitado else 999)" not in fuente
    assert "16 if" not in fuente and "else 999" not in fuente


def test_el_front_consume_la_fuente_unica_del_rotulo():
    """El rótulo no se reimplementa en el front: sale de `utils/rotuloCreditos.js`.

    Con NULL en un plan CON cupo no se inventa un 0: `Number(null) || 0` daba
    "0 créditos" y el plan sí tenía clases cargadas en `planes.creditos`. Los
    casos del rótulo (NULL, 0 real, ilimitado) están en
    `frontend/scripts/test-rotulo-creditos.mjs` y el consumo en las dos pantallas
    en `tests/test_dashboard_creditos_null_front.py`.
    """
    inicio = (RAIZ / "frontend" / "src" / "pages" / "alumno" / "InicioMobile.jsx") \
        .read_text(encoding="utf-8")
    assert "import { rotuloCreditos } from '../../utils/rotuloCreditos';" in inicio
    assert "const creditosTxt = rotuloCreditos(ilimitado, activa ? membresia?.clases_disponibles : 0);" in inicio
    assert "cupoDesconocido" not in inicio, "la regla ya no se copia en la pantalla"
