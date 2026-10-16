"""UNA sola fuente de "asistió" en todo el backend: `reservas.asistio` sobre `clases.fecha`.

CONTEXTO (auditoría 2026-10-15, 2ª tanda — decisión del usuario)
----------------------------------------------------------------
La 1ª tanda migró la "familia del bug" del panel del coach (`test_riesgo_fuente_real.py`). Esta
tanda migra los lectores que quedaban de la tabla histórica `asistencias`, que NO la puebla nadie
(el único `INSERT` de la app es `POST /fidelizacion/registrar`, que ninguna pantalla llama):

  1. `services/churn_service` — el churn del data mart, "plan sin usar" y las ventanas 30/90.
  2. `services/fidelizacion_plantillas` — los días sin entrenar de las plantillas.
  3. `services/alertas_email_service` — el `SELECT MAX(a.fecha) FROM asistencias` del correo de
     inactividad (el que decide a quién se le manda la campaña).
  4. `api/v1/kpis` — el insight servido en vivo, `/bloques-horarios` y `/cohortes` (los dos
     últimos daban 0 para SIEMPRE, porque el join salía de la tabla vacía).
  5. `api/v1/kpis_populate` — el populate del data mart (churn + embudo de la clase de prueba).
  6. `api/v1/usuarios` — la última asistencia del buscador del Admin.
  7. `ml/features` + `ml/entrenar` — los features y el LABEL del churn. No estaban en la lista del
     usuario y se agregaron porque, sin eso, el modelo se entrenaría y puntuaría contra una tabla
     vacía: el data mart volvería a decir "todos sin historial" con el resto ya corregido.

QUÉ SE FIJA ACÁ (sin base de datos)
  A. Ningún archivo de `backend/app` ni `backend/ml` importa el modelo histórico, salvo el
     ESCRITOR (`fidelizacion.py`) y el registro de modelos (`models/__init__.py`).
  B. Los 7 lectores pasan por `services/asistencia_real` (helper ORM o el CTE SQL) y la definición
     de "asistió" vive UNA sola vez (`condicion_asistio`), con su espejo SQL armado con la MISMA
     lista de cancelaciones (`shared.estados.lista_sql`).
  C. La SEMÁNTICA de los números no cambió al cambiar la fuente: las ventanas siguen siendo
     inclusivas y el "nunca asistió" sigue siendo `None`/0 (no una fecha inventada).

Correr (aislado y sin base):
    cd backend && py -3.12 -m pytest tests/test_asistencia_fuente_unica.py -q --noconftest
"""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
SERVICIO = "backend/app/services/asistencia_real.py"

# Lectores migrados: archivo → marcadores de que pasan por `asistencia_real`.
LECTORES = {
    "backend/app/services/churn_service.py": (
        "from app.services.asistencia_real import",
        "ultima_asistencia_por_alumno(",
        "asistencias_entre_por_alumno(",
    ),
    "backend/app/services/fidelizacion_plantillas.py": (
        "from app.services.asistencia_real import ultima_asistencia_por_alumno",
        "ultima_asistencia_por_alumno(",
    ),
    "backend/app/services/alertas_email_service.py": ("sql_cte_asistencias()",),
    "backend/app/api/v1/kpis.py": (
        "sql_cte_asistencias()",
        "ultima_asistencia_por_alumno(",
        "asistencias_entre_por_alumno(",
    ),
    "backend/app/api/v1/kpis_populate.py": (
        "ultima_asistencia_por_alumno(",
        "asistencias_entre_por_alumno(",
    ),
    "backend/app/api/v1/usuarios.py": ("ultima_asistencia_por_alumno(",),
    "backend/ml/features.py": (
        "ultima_asistencia_por_alumno(",
        "asistencias_entre_por_alumno(",
    ),
    "backend/ml/entrenar.py": ("asistencias_entre_por_alumno(",),
}

# Cada consulta CRUDA que habla de `asistencias` tiene que pegar el CTE (si no, leería la tabla
# histórica vacía). El número es la red que lo detecta: una consulta nueva cambia el conteo.
CTE_POR_ARCHIVO = {
    "backend/app/api/v1/kpis.py": 3,                     # bloques (2 consultas) + cohortes
    "backend/app/services/alertas_email_service.py": 1,   # el correo de inactividad
}


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def _funciones(fuente: str) -> dict:
    """{nombre de función: su código fuente} — para mirar cada lector por separado."""
    return {n.name: ast.get_source_segment(fuente, n)
            for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)}


# ── A. La tabla histórica ya no tiene lectores ────────────────────────────────
def test_a1_solo_el_escritor_y_el_registro_importan_el_modelo_historico():
    importadores = []
    for base in ("backend/app", "backend/ml"):
        for archivo in sorted((RAIZ / base).rglob("*.py")):
            if "from app.models.asistencia import" in archivo.read_text(encoding="utf-8"):
                importadores.append(archivo.relative_to(RAIZ).as_posix())
    assert importadores == ["backend/app/api/v1/fidelizacion.py",      # el ESCRITOR
                            "backend/app/models/__init__.py"], importadores


def test_a2_el_escritor_sigue_intacto():
    """No se tocó el flujo de guardado: sigue el chequeo de "ya registró hoy" y el alta."""
    fuente = _fuente("backend/app/api/v1/fidelizacion.py")
    assert "db.query(Asistencia)" in fuente
    assert "nueva = Asistencia(" in fuente
    assert "db.add(nueva)" in fuente


# ── B. UNA sola definición, y todos pasan por ella ───────────────────────────
def test_b1_los_lectores_pasan_por_el_modulo_de_la_asistencia_real():
    for rel, marcadores in LECTORES.items():
        fuente = _fuente(rel)
        for marcador in marcadores:
            assert marcador in fuente, f"{rel} dejó de usar `{marcador}`"


def test_b2_la_definicion_de_asistio_es_una_sola():
    svc = _fuente(SERVICIO)
    assert svc.count("reserva.asistio.is_(True)") == 1, (
        "el predicado de 'asistió' se duplicó: tiene que vivir sólo en `condicion_asistio()`")
    assert svc.count("no_cancelada(reserva.estado)") == 1
    assert "def condicion_asistio(reserva)" in svc
    assert svc.count("condicion_asistio(Reserva)") == 2       # última asistencia + conteo


def test_b3_cada_lector_delega_en_el_helper():
    """Los envoltorios por alumno NO reimplementan la consulta: delegan."""
    casos = (
        ("backend/app/services/churn_service.py", "_ultima_asistencia"),
        ("backend/app/services/churn_service.py", "_conteos"),
        ("backend/app/services/churn_service.py", "plan_sin_usar_lote"),
        ("backend/app/services/fidelizacion_plantillas.py", "_referencia_actividad"),
        ("backend/app/services/fidelizacion_plantillas.py", "_datos_sugerencia"),
        ("backend/app/api/v1/kpis.py", "_dias_inactividad_por_alumno"),
        ("backend/app/api/v1/kpis.py", "_asistencias_ventana_por_alumno"),
        ("backend/app/api/v1/kpis_populate.py", "_ultima_asistencia"),
        ("backend/app/api/v1/kpis_populate.py", "_conteos_asistencias"),
        ("backend/app/api/v1/usuarios.py", "_items_con_membresia"),
        ("backend/ml/features.py", "_ultima_asistencia"),
        ("backend/ml/features.py", "_asistencias_en_ventana"),
    )
    for rel, nombre in casos:
        cuerpos = _funciones(_fuente(rel))
        assert nombre in cuerpos, f"desapareció {rel}::{nombre}"
        assert ("ultima_asistencia_por_alumno(" in cuerpos[nombre]
                or "asistencias_entre_por_alumno(" in cuerpos[nombre]), (
            f"{rel}::{nombre} dejó de delegar en `asistencia_real`")


def test_b4_el_cte_sql_es_espejo_del_predicado_y_lo_pegan_todas_las_crudas():
    from shared.estados import ESTADOS_CANCELADA, lista_sql

    svc = _fuente(SERVICIO)
    assert "from shared.estados import lista_sql" in svc, (
        "la lista de cancelaciones tiene que salir de `shared.estados`, no escribirse a mano")
    assert lista_sql() == ", ".join(f"'{e}'" for e in ESTADOS_CANCELADA)
    # El CTE tiene que leer la columna que EXISTE en `reservas` (`alumno_id`) aunque exponga
    # el nombre histórico (`usuario_id`) que ya usaban las consultas crudas. `reservas.usuario_id`
    # NO existe: con ese nombre, `/bloques-horarios`, `/cohortes` y la campaña de inactividad
    # devolvían 500 (`UndefinedColumn: column r.usuario_id does not exist`) — pasó porque los
    # guards de este archivo miran texto, no ejecutan SQL (bug encontrado al correr contra la BD).
    assert "r.alumno_id AS usuario_id" in svc, (
        "el CTE tiene que leer `reservas.alumno_id` (la columna real) y exponerla como "
        "`usuario_id` (el nombre que usan las consultas crudas)")
    assert "r.usuario_id" not in svc, (
        "`reservas.usuario_id` NO existe: rompe `/bloques-horarios`, `/cohortes` y la "
        "campaña de inactividad")
    for rel, veces in CTE_POR_ARCHIVO.items():
        assert _fuente(rel).count("WITH {sql_cte_asistencias()}") == veces, rel


# ── C. La SEMÁNTICA de los números no cambió con la fuente ───────────────────
def test_c1_las_ventanas_siguen_siendo_inclusivas_y_sobre_la_fecha_de_la_clase():
    svc = _fuente(SERVICIO)
    assert "Clase.fecha >= desde" in svc and "Clase.fecha <= hasta" in svc
    assert "Clase.fecha <= hasta" in svc, "el `hasta=` del as-of del ML tiene que seguir ahí"
    assert "func.count(Reserva.id)" in svc, (
        "el conteo es de RESERVAS, igual que el 'asistentes' del BI (no de clases distintas)")


def test_c2_el_correo_de_inactividad_conserva_su_regla():
    """'Sin historial' sigue sin recibir el correo y el umbral sigue siendo el mismo."""
    cuerpo = _funciones(_fuente("backend/app/services/alertas_email_service.py"))[
        "enviar_alertas_inactividad"]
    assert "if ultima is None:" in cuerpo
    assert "if ultima > limite:" in cuerpo
    assert "limite = hoy_santiago() - timedelta(days=umbral_dias)" in cuerpo
    assert "sql_cte_asistencias()" in cuerpo


def test_c3_el_churn_no_pierde_su_fallback_del_alta():
    """Sin ninguna asistencia, el churn sigue midiendo desde el registro (fix del 999)."""
    cuerpo = _funciones(_fuente("backend/app/services/churn_service.py"))["_dias_inactividad"]
    assert "ultima = _ultima_asistencia(" in cuerpo
    assert "created_at" in cuerpo
