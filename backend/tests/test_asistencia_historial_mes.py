"""`GET /asistencia/historial` -> el MES completo de asistencia (coach + admin, SÓLO LECTURA).

QUÉ ES: la pantalla "Historial de Asistencia" (pestaña nueva del panel del coach y bloque de
la página Asistencia del admin) pide UN mes y con esa respuesta dibuja tres cosas sin volver a
pegarle a la API: el anillo de cada día de la semana, la grilla del calendario y el detalle por
bloque horario de un día. El endpoint se agregó junto con la pantalla, así que este test fija
las decisiones que la hacen segura y barata:

  A. es un GET PURO (`/historial` no tiene POST/PUT/PATCH/DELETE): una pantalla que se abre
     para MIRAR no puede escribir. El cuerpo no commitea, no audita y no encola background
     tasks (el `POST /clases/{id}/confirmar` sigue siendo el único que marca);
  B. los contadores salen del MISMO helper que `/clases-hoy` (`_contadores_de_clases`,
     definido UNA sola vez): si se duplicara, el día y el mes podrían decir cosas distintas
     del mismo dato;
  C. el alcance por rol es el de siempre (coach = sus clases con `condicion_mis_clases`, la
     misma definición de `GET /clases/?coach_id=`; admin = el box completo) y las clases
     CANCELADAS quedan fuera del mes (una clase que no ocurrió no baja el % de su día);
  D. la respuesta lleva HECHOS (cupos, reservas, marcados, asistencia cerrada y la lista de
     alumnos con su `asistio`) y NINGÚN porcentaje: el % lo calcula el front UNA sola vez en
     `utils/historialAsistencia.js` (con test propio, `test-historial-asistencia.mjs`).

Correr (aislado y sin base):
    cd backend && py -3.12 -m pytest tests/test_asistencia_historial_mes.py -q --noconftest
"""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
API = "backend/app/api/v1/asistencia.py"

# Lo que NO puede aparecer en un endpoint de lectura (escrituras y efectos).
ESCRITURAS = ("db.commit(", "db.flush(", "db.add(", "db.delete(", "db.execute(",
              "update(", "registrar_auditoria(")


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def _funciones(fuente: str) -> dict:
    """{nombre de función: su código fuente} — para mirar cada una por separado."""
    return {n.name: ast.get_source_segment(fuente, n)
            for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)}


# ── A. Un GET puro ────────────────────────────────────────────────────────────
def test_a1_el_historial_del_mes_es_un_get_y_no_otra_cosa():
    src = _fuente(API)
    assert '@router.get("/historial")\ndef historial_mes(' in src, (
        "el endpoint del mes tiene que seguir siendo GET /historial")
    for metodo in ("post", "put", "patch", "delete"):
        assert f'@router.{metodo}("/historial")' not in src, (
            f"/historial nació de sólo lectura: no puede tener @router.{metodo}")


def test_a2_el_cuerpo_del_endpoint_no_escribe_nada():
    cuerpo = _funciones(_fuente(API))["historial_mes"]


# ── B. Una sola definición de los contadores (mes y día) ──────────────────────
def test_b1_el_mes_y_el_dia_cuentan_con_el_mismo_helper():
    src = _fuente(API)
    assert src.count("def _contadores_de_clases(") == 1, (
        "los contadores tienen que estar definidos UNA sola vez")
    assert src.count("_contadores_de_clases(db, ids)") == 2, (
        "lo llaman /clases-hoy (el día) y /historial (el mes); un tercero cambia este número")
    funciones = _funciones(src)
    for nombre in ("clases_hoy", "historial_mes"):
        assert "_contadores_de_clases(db, ids)" in funciones[nombre], (
            f"{nombre} dejó de compartir los contadores (el día y el mes podrían decir " 
            "cosas distintas del mismo dato)")


def test_b2_el_helper_cuenta_reservas_vigentes_presentes_y_clases_cerradas():
    src = _fuente(API)
    helper = src[src.index("def _contadores_de_clases("):src.index("def clases_hoy(")]
    assert "no_cancelada(Reserva.estado)" in helper, (
        "una reserva cancelada no es un cupo ocupado (misma lista de cancelaciones que el resto)")
    assert "Reserva.asistio.is_(True)" in helper, "`marcados_count` = reservas con asistio real"
    assert "Reserva.asistencia_marcada_at.is_(None)" in helper, (
        "una clase con reservas sin marcar NO es \"marcada\": es la que el coach tiene pendiente")
    assert "ESTADOS_VIGENTES" in helper, (
        "las reservas vigentes salen de `shared.estados`, no de una lista escrita a mano")
    assert '"faltan"' not in helper, (
        "al backend no le toca calcular \"faltan\": es aritmética de presentación (front)")


# ── C. Alcance por rol y ventana del mes ──────────────────────────────────────
def test_c1_el_coach_ve_sus_clases_y_el_admin_el_box():
    cuerpo = _funciones(_fuente(API))["historial_mes"]
    assert 'if rol == "coach":' in cuerpo, "hay una rama explícita de alcance"
    assert 'query = query.filter(condicion_mis_clases(current_user["usuario_id"]))' in cuerpo, (
        "el coach ve lo suyo con `condicion_mis_clases` (las 3 vías: asignada, horario y disciplina)")
    assert '"alcance": "coach" if rol == "coach" else "box"' in cuerpo, (
        "la pantalla tiene que poder rotular de quién es el mes que muestra")
    assert "Clase.tenant_id == tenant_id" in cuerpo, "el tenant sale del token, como el resto"
    src = _fuente(API)
    importes = src[:src.index("router = APIRouter()")]
    assert "condicion_mis_clases" in importes and "es_mi_clase" in importes, (
        "la definición de \"mis clases\" se importa de `clases_service` (no se reimplementa)")


def test_c2_la_ventana_es_el_mes_de_calendario_y_las_canceladas_quedan_fuera():
    cuerpo = _funciones(_fuente(API))["historial_mes"]
    assert "primer_dia = date(anio, mes, 1)" in cuerpo, "el mes arranca el día 1 (Santiago)"
    assert "date(anio, 12, 31) if mes == 12" in cuerpo, (
        "diciembre tiene que cortar el 31 y no pedir el mes 13")
    assert "date(anio, mes + 1, 1) - timedelta(days=1)" in cuerpo, (
        "el resto de los meses cierra el último día: la ventana es inclusiva de punta a punta")
    assert "Clase.fecha >= primer_dia" in cuerpo and "Clase.fecha <= ultimo_dia" in cuerpo
    assert "Clase.cancelada == False" in cuerpo, (
        "una clase cancelada no ocurrió: no puede bajar el % de su día")


def test_c3_los_parametros_del_mes_estan_acotados_por_fastapi():
    cuerpo = _funciones(_fuente(API))["historial_mes"]
    assert "anio: int = Query(..., ge=2000, le=2100" in cuerpo, (
        "un año absurdo tiene que dar 422 en el borde, no armar una consulta rara")
    assert "mes: int = Query(..., ge=1, le=12" in cuerpo, "el mes va de 1 a 12"


# ── D. Hechos, no porcentajes ─────────────────────────────────────────────────
def test_d1_la_respuesta_trae_los_hechos_que_la_pantalla_necesita():
    cuerpo = _funciones(_fuente(API))["historial_mes"]
    hechos = ('"cupo_maximo":', '"reservas_count":', '"marcados_count":', '"marcada":',
              '"alumnos":', '"estado":', '"disciplina_nombre":')
    for hecho in hechos:
        assert hecho in cuerpo, f"la respuesta del mes tiene que traer {hecho}"
    assert '"asistio": bool(r.asistio)' in cuerpo, (
        "cada alumno viaja con su `asistio` (el ✓/✗ del detalle del día)")


def test_d2_el_backend_no_manda_porcentajes():
    cuerpo = _funciones(_fuente(API))["historial_mes"]
    for prohibido in ('"pct"', '"porcentaje"', "* 100"):
        assert prohibido not in cuerpo, (
            f"{prohibido} no va en la respuesta: el % se calcula UNA vez en "
            "`frontend/src/utils/historialAsistencia.js`")


def test_d3_el_estado_de_cada_clase_sale_del_helper_compartido():
    cuerpo = _funciones(_fuente(API))["historial_mes"]
    assert "estado_clase(" in cuerpo, (
        "realizada/en curso/por venir lo decide `clases_service.estado_clase` (mismo criterio "
        "que la pestaña Asistencia), no una cuenta nueva acá")
    assert "ahora_dt" in cuerpo and cuerpo.count("ahora_santiago()") == 1, (
        "una sola lectura del reloj para todo el mes: dos clases del mismo día no pueden "
        "quedar en estados distintos por milisegundos de diferencia")

    for marca in ESCRITURAS:
        assert marca not in cuerpo, (
            f"`{marca}` no tiene nada que hacer en una pantalla de lectura")
    assert "BackgroundTasks" not in cuerpo, "una pantalla de lectura no encola trabajo de fondo"


def test_a3_lo_sirve_el_guard_del_coach_y_esta_documentado_en_el_router():
    src = _fuente(API)
    cuerpo = _funciones(src)["historial_mes"]
    assert "current_user: dict = Depends(get_current_coach)" in cuerpo, (
        "coach + admin pasan por `get_current_coach`; el alumno NO lee el mes del box")
    assert "GET  /historial" in src, "el router lista sus endpoints en el docstring de arriba"
