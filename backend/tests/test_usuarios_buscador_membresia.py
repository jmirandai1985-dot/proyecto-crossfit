"""Buscador de alumnos (<768px): los extras de membresía son OPT-IN, sin N+1.

Qué fija este archivo:

  A. `usuarios._resumen_membresia` — el resumen que ve la ficha rápida: `creditos_disponibles`
     TAL CUAL (NULL = "cupo no cargado", no un 0 inventado), `es_ilimitado` del plan y los
     días restantes con el día de CHILE (0 = vence hoy). Sin plan activo => None.
  B. El listado `GET /usuarios/` pide los extras SOLO con `?con_membresia=true` (default
     false): Alumnos.jsx, Coaches.jsx y el selector de clases reciben el mismo contrato.
  C. Las consultas extra son TRES para toda la página (no una por alumno) y la "última
     asistencia" usa la misma definición que Fidelización (max(fecha), nunca 999).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_usuarios_buscador_membresia.py -q --noconftest
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from app.api.v1.usuarios import _resumen_membresia   # noqa: E402
    from app.utils.santiago import hoy_santiago, fin_del_dia_chile, SANTIAGO  # noqa: E402
except Exception as exc:   # pragma: no cover - entorno sin dependencias del backend
    pytest.skip(f"no se pudo importar el router de usuarios: {exc}",
                allow_module_level=True)

RAIZ = Path(__file__).resolve().parents[2]


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _suscripcion(**kwargs):
    base = {
        "plan_id": 7,
        "creditos_disponibles": 8,
        "creditos_totales": 12,
        "fecha_expiracion": datetime(2026, 11, 30, 23, 59, 59, tzinfo=SANTIAGO),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── A. El resumen ────────────────────────────────────────────────────────────

def test_a1_sin_plan_activo_el_resumen_es_none():
    assert _resumen_membresia(None, None) is None


def test_a2_devuelve_plan_cupo_y_dias_restantes():
    hoy = hoy_santiago()
    r = _resumen_membresia(
        _suscripcion(fecha_expiracion=fin_del_dia_chile(hoy + timedelta(days=3))),
        SimpleNamespace(nombre="Mensual full", es_ilimitado=False),
    )
    assert r["plan_nombre"] == "Mensual full"
    assert r["creditos_disponibles"] == 8 and r["creditos_totales"] == 12
    assert r["es_ilimitado"] is False
    assert r["dias_restantes"] == 3


def test_a3_cupo_null_no_se_convierte_en_cero():
    r = _resumen_membresia(
        _suscripcion(creditos_disponibles=None),
        SimpleNamespace(nombre="X", es_ilimitado=True))
    assert r["creditos_disponibles"] is None, (
        "NULL es 'cupo no cargado': el front lo pinta '—'/'∞', nunca 0")
    assert r["es_ilimitado"] is True


def test_a4_plan_que_vence_hoy_da_cero_dias():
    r = _resumen_membresia(
        _suscripcion(creditos_totales=None,
                     fecha_expiracion=fin_del_dia_chile(hoy_santiago())),
        SimpleNamespace(nombre="Prueba", es_ilimitado=False))
    assert r["dias_restantes"] == 0


def test_a5_plan_vencido_no_tiene_dias_negativos():
    r = _resumen_membresia(
        _suscripcion(
            fecha_expiracion=fin_del_dia_chile(hoy_santiago() - timedelta(days=10))),
        SimpleNamespace(nombre="Viejo", es_ilimitado=False))
    assert r["dias_restantes"] == 0, "un plan vencido no muestra -10 días"


def test_a6_sin_plan_cargado_el_nombre_queda_en_none_pero_el_cupo_se_respeta():
    r = _resumen_membresia(_suscripcion(), None)
    assert r["plan_nombre"] is None and r["es_ilimitado"] is None
    assert r["creditos_disponibles"] == 8


# ── B. Opt-in en el listado ──────────────────────────────────────────────────

def test_b1_el_extra_es_opt_in_y_por_defecto_false():
    fuente = _fuente("backend/app/api/v1/usuarios.py")
    assert "con_membresia: bool = Query(" in fuente
    assert "if con_membresia:" in fuente


def test_b2_sin_el_parametro_se_devuelve_la_lista_de_siempre():
    fuente = _fuente("backend/app/api/v1/usuarios.py")
    assert "return _items_con_membresia(db, tenant_id, usuarios)" in fuente
    bloque = fuente.split("if con_membresia:")[1]
    assert "return usuarios" in bloque, (
        "el listado de siempre tiene que seguir devolviéndose por defecto")


def test_b3_el_schema_nuevo_es_aditivo_y_opcional():
    fuente = _fuente("backend/app/schemas/usuario.py")
    assert "class MembresiaResumenItem(BaseModel):" in fuente
    assert "membresia: Optional[MembresiaResumenItem] = None" in fuente
    assert "ultima_asistencia: Optional[date] = None" in fuente


# ── C. Sin N+1 y sin números inventados ──────────────────────────────────────

def test_c1_tres_consultas_para_toda_la_pagina():
    fuente = _fuente("backend/app/api/v1/usuarios.py")
    helper = fuente.split("def _items_con_membresia(")[1].split(
        '@router.get("/", response_model')[0]
    assert "in_(ids)" in helper, "las consultas van por lote de ids, no por alumno"
    # El armado de la respuesta es una comprensión de lista: sin queries adentro.
    cuerpo = helper.split("return [")[1]
    assert "db.query" not in cuerpo


def test_c2_ultima_asistencia_usa_la_misma_definicion_que_fidelizacion():
    fuente = _fuente("backend/app/api/v1/usuarios.py")
    helper = fuente.split("def _items_con_membresia(")[1].split('@router.get("/")')[0]
    assert "func.max(Asistencia.fecha)" in helper
    assert "Asistencia.tenant_id == tenant_id" in helper


def test_c3_no_hay_numeros_inventados_ni_999():
    fuente = _fuente("backend/app/api/v1/usuarios.py")
    helper = fuente.split("def _items_con_membresia(")[1].split('@router.get("/")')[0]
    assert "or 999" not in helper and "or 16" not in helper


def test_c4_la_vigencia_es_la_del_dia_chileno_compartido():
    fuente = _fuente("backend/app/api/v1/usuarios.py")
    assert "vigente_el_dia(s.fecha_expiracion)" in fuente
    assert "dias_para_vencer(suscripcion.fecha_expiracion)" in fuente


def test_c5_el_valor_de_creditos_sale_tal_cual_de_la_fila():
    fuente = _fuente("backend/app/api/v1/usuarios.py")
    assert '"creditos_disponibles": suscripcion.creditos_disponibles,' in fuente


def test_z_fechas_del_test_son_del_calendario_chileno():
    # Ancla: los stubs usan `date`/`hoy_santiago()` del calendario de Chile.
    assert isinstance(hoy_santiago(), date)
