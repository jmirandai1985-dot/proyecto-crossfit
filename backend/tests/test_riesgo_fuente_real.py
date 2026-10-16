"""El cálculo de "En riesgo" lee la asistencia REAL (`reservas.asistio`), no `asistencias`.

BUG EN PROD (auditoría 2026-10-15): el panel del coach mostraba "En riesgo" con los 251 alumnos
del padrón. Causa raíz: la familia que responde "¿hace cuánto no entrena este alumno?" leía la
tabla `asistencias`, y esa tabla NO la puebla nadie:
  · el único `INSERT` de la app es `POST /fidelizacion/registrar` y NINGUNA pantalla lo llama
    (no hay `fidelizacion/registrar` en `frontend/` ni en los tests);
  · lo que el coach y el alumno usan es `POST /asistencia/clases/{id}/confirmar`, que escribe
    `reservas.asistio` — la fuente del resto del panel (`/rms`, historial, contadores "ya
    marcaron", validación de la clase de prueba);
  · la tabla sólo la llenaban los seeds/demo.
Con `asistencias` vacía, TODOS los alumnos quedaban `tiene_historial = False`, y el filtro de
alerta incluye justamente a los "sin historial": el conteo devolvía el padrón entero.

QUÉ SE FIJA ACÁ
  A. SIN BD (el candado del fix): los CUATRO puntos que responden "días sin entrenar" —la alerta
     del coach, la del admin (tenant), el análisis de fidelización y los días del correo de
     contacto— llaman al helper `ultima_asistencia_por_alumno`, y no queda NINGUNA lectura de
     `Asistencia.fecha` en `fidelizacion.py`. El flujo de GUARDADO no se toca: el único uso de
     `Asistencia` que sobrevive es el `INSERT` de `POST /registrar`.
  B. SIN BD: la definición del helper es UNA (`reservas.asistio = true` sobre `clases.fecha`, con
     la reserva no cancelada) y no importa el modelo histórico.
  C. TEST (escrito, NO ejecutado): el helper contra la base real, contra un SQL independiente.

Correr (aislado y sin base):
    cd backend && py -3.12 -m pytest tests/test_riesgo_fuente_real.py -q --noconftest
"""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
FIDELIZACION = "backend/app/api/v1/fidelizacion.py"
SERVICIO = "backend/app/services/asistencia_real.py"

# Las cuatro respuestas a "¿hace cuánto no entrena?": el panel del coach y sus hermanas.
FUNCIONES_CON_ASISTENCIA_REAL = (
    "analizar_fidelizacion",        # GET  /fidelizacion/analizar/{tenant_id} (admin)
    "alumnos_coach_en_riesgo",      # GET  /fidelizacion/coach/{id}/en-riesgo (el KPI del bug)
    "alumnos_tenant_en_riesgo",     # GET  /fidelizacion/tenant/{id}/en-riesgo (admin)
    "_dias_inactividad_alumno",     # los días del correo de contacto del coach
)


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def _cuerpos(fuente: str) -> dict:
    """{nombre de función: su código fuente} — para mirar cada endpoint por separado."""
    return {n.name: ast.get_source_segment(fuente, n)
            for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)}


# ── A. El cálculo de riesgo lee la fuente real ────────────────────────────────
def test_a1_las_cuatro_respuestas_usan_el_helper():
    fuente = _fuente(FIDELIZACION)
    assert "from app.services.asistencia_real import ultima_asistencia_por_alumno" in fuente
    cuerpos = _cuerpos(fuente)
    for nombre in FUNCIONES_CON_ASISTENCIA_REAL:
        assert nombre in cuerpos, f"desapareció {nombre}"
        assert "ultima_asistencia_por_alumno(" in cuerpos[nombre], (
            f"{nombre} dejó de leer la asistencia real (¿volvió a `asistencias`?)")


def test_a2_no_queda_ninguna_lectura_de_la_tabla_historica():
    """La familia de riesgo no toca el modelo histórico; el único uso que queda es el escritor."""
    cuerpos = _cuerpos(_fuente(FIDELIZACION))
    for nombre in FUNCIONES_CON_ASISTENCIA_REAL:
        assert "Asistencia." not in cuerpos[nombre], (
            f"{nombre} sigue leyendo la tabla `asistencias`")
    assert "Asistencia." in cuerpos["registrar_asistencia"], (
        "el chequeo de 'ya registró hoy' del escritor debería seguir ahí")


def test_a3_el_flujo_de_guardado_no_se_toco():
    """El `INSERT` de `POST /registrar` sigue como estaba (no se le agregó ni se le quitó nada)."""
    fuente = _fuente(FIDELIZACION)
    assert "db.query(Asistencia)" in fuente          # el chequeo de "ya registró hoy"
    assert "nueva = Asistencia(" in fuente           # el alta
    assert "db.add(nueva)" in fuente


# ── B. UNA sola definición de "asistió" ───────────────────────────────────────
def test_b1_el_helper_lee_reservas_asistio_sobre_la_fecha_de_la_clase():
    svc = _fuente(SERVICIO)
    # El predicado vive UNA sola vez (`condicion_asistio`, 2ª tanda) y el helper lo usa.
    assert "and_(reserva.asistio.is_(True), no_cancelada(reserva.estado))" in svc
    assert "condicion_asistio(Reserva)" in svc
    assert "join(Clase, Reserva.clase_id == Clase.id)" in svc, (
        "la fecha tiene que ser la de la CLASE, no la de la reserva")
    assert "func.max(Clase.fecha)" in svc
    assert ".group_by(Reserva.alumno_id)" in svc     # una consulta para todo el lote
    assert "no_cancelada(reserva.estado)" in svc     # una clase cancelada no es una asistencia


def test_b2_el_helper_no_importa_el_modelo_historico():
    assert "models.asistencia" not in _fuente(SERVICIO)


# ── C. Integración (escrita, NO ejecutada: necesita la base TEST) ─────────────
@pytest.mark.skip(reason="integración: se corre a mano contra el branch TEST")
def test_c1_el_helper_coincide_con_un_sql_independiente():
    from sqlalchemy import text

    from app.db.database import SessionLocal
    from app.services.asistencia_real import ultima_asistencia_por_alumno

    db = SessionLocal()
    try:
        fila = db.execute(text("""
            SELECT r.tenant_id, r.alumno_id, MAX(c.fecha) AS ultima
            FROM reservas r JOIN clases c ON c.id = r.clase_id
            WHERE r.asistio IS TRUE AND r.estado NOT IN ('cancelled', 'cancelada')
            GROUP BY r.tenant_id, r.alumno_id
            ORDER BY MAX(c.fecha) DESC LIMIT 1
        """)).first()
        if fila is None:
            pytest.skip("el box de TEST no tiene ninguna reserva con asistencia marcada")
        tenant_id, alumno_id, ultima = fila
        mapa = ultima_asistencia_por_alumno(db, tenant_id, [alumno_id])
        assert mapa.get(alumno_id) == ultima, (
            "el helper no coincide con la asistencia real de la base")
    finally:
        db.close()
