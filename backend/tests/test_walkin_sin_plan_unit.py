"""
Walk-in "sin reserva": SIN plan activo no se entra (409), y el único caso que queda es el
plan vigente SIN créditos. Test AISLADO (sin base ni red).

POR QUÉ EXISTE (bug 2026-11): el candado que ya había bloqueaba al alumno CON plan y
créditos ("agrégalo como reserva normal, así se le descuenta"), pero el caso contrario
—alumno SIN ningún plan— entraba como presencia SIN CARGO: entrenaba gratis. La decisión es
la Opción A: BLOQUEAR (nunca generar una deuda pendiente ni regalar la clase).

QUÉ SE FIJA ACÁ
  A. Sin plan → 409 con el mensaje que se le muestra al staff, y NADA escrito (ni aforo,
     ni reserva, ni auditoría).
  B. Con plan y créditos → sigue el 409 de siempre (el camino es la reserva normal). No se
     rompió el comportamiento anterior.
  C. Con plan vigente sin créditos → el walk-in sigue funcionando sin cargo (el único caso
     válido): reserva, aforo +1 y auditoría.
  D. El front (el picker de "Agregar alumno sin reserva") no ofrece a quien no tiene plan y
     muestra el `detail` del backend tal cual (guard de fuente, sin navegador).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_walkin_sin_plan_unit.py -q --noconftest
"""
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.v1 import asistencia as api
from app.models.clase import Clase
from app.models.reserva import Reserva
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario
from app.schemas.asistencia import PresenteSinReservaRequest

RAIZ = Path(__file__).resolve().parents[2]
PICKER = "frontend/src/components/ModalAgregarSinReserva.jsx"

HOY = date(2026, 11, 19)
ALUMNO_ID = 42
CLASE_ID = 11
STAFF = {"usuario_id": 7, "tenant_id": 1, "rol": "admin", "nombre": "Admin"}


# ── Doble de la sesión: sólo lo que el endpoint usa ─────────────────────────
class _Consulta:
    def __init__(self, resultado):
        self.resultado = resultado

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.resultado


class _SesionFalsa:
    """Devuelve una fila por modelo y registra TODO lo que se intentó escribir."""

    def __init__(self, por_modelo=None, rowcount=1):
        self.por_modelo = por_modelo or {}
        self.rowcount = rowcount
        self.agregados = []
        self.ejecutados = []
        self.commits = 0

    def query(self, modelo, *args):
        return _Consulta(self.por_modelo.get(modelo))

    def execute(self, sentencia, *args, **kwargs):
        self.ejecutados.append(sentencia)
        return SimpleNamespace(rowcount=self.rowcount)

    def add(self, objeto):
        self.agregados.append(objeto)

    def commit(self):
        self.commits += 1

    def refresh(self, objeto):
        if getattr(objeto, "id", None) is None:
            objeto.id = 999

    def rollback(self):
        pass


def _clase():
    return Clase(
        id=CLASE_ID, tenant_id=1, fecha=HOY, hora_inicio=time(19, 0),
        hora_fin=time(20, 0), disciplina_id=3, coach_id=5, cancelada=False,
        cupo_maximo=20, asistentes_confirmados=4,
    )


def _alumno(nombre="Ana Pérez"):
    return Usuario(
        id=ALUMNO_ID, tenant_id=1, nombre=nombre, rol=RolUsuario.alumno,
        activo=True, estado="activo",
    )


def _plan(creditos):
    """Suscripción que da acceso hoy. `creditos=None` = plan ILIMITADO."""
    return Suscripcion(
        id=1, usuario_id=ALUMNO_ID, tenant_id=1, plan_id=2,
        creditos_disponibles=creditos, estado="activa",
        fecha_expiracion=datetime(2027, 1, 31, 23, 59, 59),
    )



@pytest.fixture
def entorno(monkeypatch):
    """Neutraliza la fecha, la auditoría y el recálculo de churn (no son el objeto del test)."""
    monkeypatch.setattr(api, "hoy_santiago", lambda: HOY)
    monkeypatch.setattr(api, "ahora_santiago", lambda: datetime(2026, 11, 19, 19, 30))
    auditorias = []
    monkeypatch.setattr(api, "registrar_auditoria",
                        lambda *a, **k: auditorias.append(k))
    monkeypatch.setattr(api.churn_service, "programar_recalculo",
                        lambda *a, **k: None)
    return auditorias


def _llamar(db, plan, alumno=None):
    """Ejecuta el endpoint con `_planes_que_dan_acceso` devolviendo `plan` (o None)."""
    alumno = alumno or _alumno()
    db.por_modelo = {Clase: _clase(), Usuario: alumno, Reserva: None}
    original = api._planes_que_dan_acceso
    api._planes_que_dan_acceso = lambda *_a, **_k: (
        {alumno.id: plan} if plan is not None else {})
    try:
        return api.registrar_presente_sin_reserva(
            clase_id=CLASE_ID,
            body=PresenteSinReservaRequest(alumno_id=alumno.id),
            background_tasks=BackgroundTasks(),
            db=db,
            current_user=dict(STAFF),
            modo_emergencia=False,
        )
    finally:
        api._planes_que_dan_acceso = original


# ── A. SIN plan: bloqueado y sin escribir nada ──────────────────────────────
def test_a_sin_plan_da_409_con_el_mensaje_y_no_escribe_nada(entorno):
    db = _SesionFalsa()
    with pytest.raises(HTTPException) as error:
        _llamar(db, plan=None)
    assert error.value.status_code == 409
    assert error.value.detail == (
        "Ana Pérez no tiene un plan activo. Debe contratar un plan para poder asistir "
        "a clases.")
    assert db.ejecutados == [], "no se toca el aforo"
    assert db.agregados == [], "no se crea la reserva"
    assert db.commits == 0
    assert entorno == [], "tampoco queda auditoría de algo que no pasó"


# ── B. Con plan y créditos: el 409 de siempre (no se rompió) ────────────────
def test_b_con_plan_y_creditos_sigue_pidiendo_la_reserva_normal(entorno):
    db = _SesionFalsa()
    with pytest.raises(HTTPException) as error:
        _llamar(db, plan=_plan(3))
    assert error.value.status_code == 409
    assert "plan vigente con créditos" in error.value.detail
    assert "reserva normal" in error.value.detail
    assert db.ejecutados == [] and db.agregados == [] and db.commits == 0


def test_b2_el_plan_ilimitado_tambien_va_por_la_reserva_normal(entorno):
    """`creditos_disponibles = NULL` = ilimitado: `_puede_reservar` lo deja reservar."""
    db = _SesionFalsa()
    with pytest.raises(HTTPException) as error:
        _llamar(db, plan=_plan(None))
    assert error.value.status_code == 409
    assert "plan vigente con créditos" in error.value.detail


# ── C. Plan vigente SIN créditos: el único walk-in que queda ─────────────────
def test_c_plan_sin_creditos_entra_presente_y_sin_cargo(entorno):
    db = _SesionFalsa()
    datos = _llamar(db, plan=_plan(0))
    assert datos["cargo"] == "sin_cargo"
    assert datos["asistio"] is True
    assert datos["alumno_id"] == ALUMNO_ID
    assert len(db.ejecutados) == 1, "un solo UPDATE: el aforo (+1)"
    assert len(db.agregados) == 1, "se crea la reserva presente"
    reserva = db.agregados[0]
    assert reserva.asistio is True
    assert reserva.tokens_gastados == 0
    assert reserva.asistencia_via == api.VIA_SIN_CARGO
    assert reserva.asistencia_marcada_por == STAFF["usuario_id"]
    assert db.commits == 1
    assert entorno and entorno[0]["detalle"]["origen"] == "sin_reserva", \
        "queda la auditoría (dar por presente sin cobro es sensible)"


def test_c2_la_clase_sin_cupo_sigue_dando_400(entorno):
    """El candado del plan no cambia el del aforo (mismo orden que antes)."""
    db = _SesionFalsa(rowcount=0)
    with pytest.raises(HTTPException) as error:
        _llamar(db, plan=_plan(0))
    assert error.value.status_code == 400
    assert "sin cupos" in error.value.detail
    assert db.agregados == [] and db.commits == 0


# ── D. Front: el picker no ofrece a quien no tiene plan ────────────────────
def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_d_el_picker_no_ofrece_alumnos_sin_plan_y_muestra_el_detail():
    picker = _fuente(PICKER)
    assert "if (!a.plan_vigente) return 'Sin plan · no puede asistir';" in picker
    assert "disabled={ocupado || a.ya_presente || !a.plan_vigente}" in picker, (
        "la fila del alumno sin plan tiene que quedar deshabilitada")
    assert "No tiene un plan activo: debe contratar un plan para poder asistir a clases." in picker
    assert "e.response?.data?.detail || 'No se pudo agregar al alumno'" in picker, (
        "el 409 real del backend se muestra tal cual")
    assert 'data-testid="error-sin-reserva"' in picker, "el error tiene que verse en el modal"
