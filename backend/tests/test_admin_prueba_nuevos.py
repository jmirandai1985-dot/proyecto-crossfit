"""Tarjeta "Alumnos nuevos y en prueba" del dashboard admin móvil (<768px).

Tests AISLADOS (sin red, sin base de datos): lo que se puede fijar sin DB es la
REGLA, no la consulta.

  A. `dias_desde_inscripcion` — días de CHILE desde el alta (0 = hoy). Un alta de
     las 21:30 CLT es "hoy" aunque en UTC ya sea mañana; sin fecha -> 0.
  B. `estado_prueba` — 🟡 sin clase / 🔵 ya asistió sin plan / convertido (contrató).
  C. El envío MANUAL no interfiere con las alertas AUTOMÁTICAS: tipos propios
     (`*_manual`), disjuntos de los del scheduler, y la fila la reclama el endpoint
     (`registrar=False` en el envío) para que no haya dos filas por correo.
  D. `Nuevos del mes` reutiliza la MISMA definición del KPI del panel (`_inicio_fin_mes`
     de reportes), no una copia.
  E. La asistencia se mide con `reservas.asistio` dentro de la ventana de la prueba
     (reservar NO es asistir) y el banner "prueba HOY" del escritorio queda intacto.
  F. Las 3 plantillas nuevas salen con los datos REALES (nombre, días, código) y con
     el encabezado de marca.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_admin_prueba_nuevos.py -q --noconftest
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from app.api.v1.admin import (          # noqa: E402
        TIPOS_PRUEBA_MANUAL, dias_desde_inscripcion, estado_prueba,
    )
    from app.services.email_service import (   # noqa: E402
        render_email_aviso_retiro, render_email_clase_prueba,
        render_email_contratar_plan,
    )
    from app.utils.santiago import SANTIAGO, hoy_santiago   # noqa: E402
except Exception as exc:   # pragma: no cover - entorno sin dependencias del backend
    pytest.skip(f"no se pudo importar el router de admin: {exc}",
                allow_module_level=True)

RAIZ = Path(__file__).resolve().parents[2]


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _bloque(fuente: str, desde: str, hasta: str) -> str:
    """El texto entre dos marcas (para mirar UNA función dentro de un archivo).

    Si la marca final no existe (la función es la ÚLTIMA del archivo), devuelve
    hasta el final: el test no depende de que haya otra función después.
    """
    inicio = fuente.index(desde)
    final = fuente.find(hasta, inicio)
    return fuente[inicio:] if final == -1 else fuente[inicio:final]


# ── A. Días desde la inscripción (días de CHILE) ─────────────────────────────

def test_a1_alta_de_hoy_es_cero_dias():
    hoy = hoy_santiago()
    instante = datetime.combine(hoy, datetime.min.time(), tzinfo=SANTIAGO)
    assert dias_desde_inscripcion(instante, hoy) == 0


def test_a2_cuenta_dias_de_calendario_chileno():
    hoy = hoy_santiago()
    ayer = hoy - timedelta(days=1)
    instante = datetime.combine(ayer, datetime.min.time(), tzinfo=SANTIAGO)
    assert dias_desde_inscripcion(instante, hoy) == 1
    hace_cinco = datetime.combine(hoy - timedelta(days=5), datetime.min.time(),
                                  tzinfo=SANTIAGO)
    assert dias_desde_inscripcion(hace_cinco, hoy) == 5


def test_a3_un_alta_de_noche_cuenta_por_el_dia_chileno():
    # 01:00 UTC del 10 = 21:00 CLT del 9: para el box, el alumno se inscribió el 9.
    instante = datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc)
    assert dias_desde_inscripcion(instante, date(2026, 8, 10)) == 1
    assert dias_desde_inscripcion(instante, date(2026, 8, 9)) == 0


def test_a4_sin_fecha_o_fecha_futura_no_inventa_dias():
    assert dias_desde_inscripcion(None) == 0
    futuro = datetime.combine(hoy_santiago() + timedelta(days=3),
                              datetime.min.time(), tzinfo=SANTIAGO)
    assert dias_desde_inscripcion(futuro) == 0


def test_a5_un_instante_sin_zona_se_asume_utc():
    # Lo que devuelve Postgres para una columna tz-aware leída sin zona.
    naive = datetime(2026, 8, 10, 1, 0)
    assert dias_desde_inscripcion(naive, date(2026, 8, 10)) == 1


# ── B. Clasificación del estado ──────────────────────────────────────────────

def test_b1_sin_asistencia_y_sin_plan_es_sin_clase():
    assert estado_prueba(asistio_prueba=False, tiene_plan_vigente=False) == "sin_clase"


def test_b2_asistio_y_sigue_sin_plan_es_sin_plan():
    assert estado_prueba(asistio_prueba=True, tiene_plan_vigente=False) == "sin_plan"


def test_b3_el_plan_vigente_manda_sobre_la_asistencia():
    assert estado_prueba(True, True) == "convertido"
    assert estado_prueba(False, True) == "convertido"

# ── C. El envío MANUAL no toca la dedupe de las alertas automáticas ──────────

def _tipos_reclamados_por_el_scheduler() -> set:
    """Tipos con los que el scheduler RECLAMA su envío diario (literales del servicio)."""
    import re
    fuente = _fuente("backend/app/services/alertas_email_service.py")
    return set(re.findall(r'_(?:reclamar_envio|ya_enviado)\([^)]*?"([a-z_]+)"', fuente))


def _tipos_registrados_en_email_service() -> set:
    """Todos los `tipo="..."` que ya existían en email_service (alertas y transaccionales)."""
    import re
    fuente = _fuente("backend/app/services/email_service.py")
    return set(re.findall(r'tipo="([a-z_]+)"', fuente))


def test_c1_los_tipos_manuales_son_propios_y_no_pisan_ninguna_alerta():
    manuales = set(TIPOS_PRUEBA_MANUAL.values())
    assert len(manuales) == 2
    assert all(t.endswith("_manual") for t in manuales)

    automaticos = _tipos_reclamados_por_el_scheduler()
    # Guardia del propio test: si el regex deja de encontrar los tipos del scheduler,
    # la comparación de abajo sería vacía y no probaría nada.
    assert len(automaticos) >= 4, f"no se leyeron los tipos automáticos: {automaticos}"

    assert not (manuales & automaticos)
    # Y tampoco reusa ningún `tipo` que ya existía en email_service (los `*_manual`
    # que agrega este bloque son los propios).
    preexistentes = {t for t in _tipos_registrados_en_email_service()
                     if not t.endswith("_manual")}
    assert not (manuales & preexistentes)


def test_c2_el_endpoint_reclama_la_fila_y_no_deja_que_email_service_la_escriba():
    fuente = _fuente("backend/app/api/v1/admin.py")
    enviar = _bloque(fuente, "def enviar_invitacion_prueba", "\n@router.")
    # La fila de notificaciones_enviadas la reclama el ENDPOINT (atómico, 1 por día
    # y por alumno+tipo) y el correo va con registrar=False: UNA fila por envío.
    assert "reclamar_envio_manual(db, alumno.id, tipo, tenant_id=tenant_id)" in enviar
    assert enviar.count("registrar=False") == 2
    # Si ya se mandó hoy, se devuelve la hora del envío (no un error).
    assert "ya_enviado" in enviar
    # El estado lo decide el backend: el cliente no elige la plantilla.
    assert "TIPOS_PRUEBA_MANUAL[estado]" in enviar


def test_c4_un_envio_fallido_se_puede_reintentar_el_mismo_dia():
    fuente = _fuente("backend/app/services/alertas_email_service.py")
    helper = _bloque(fuente, "def reclamar_envio_manual", "\n\ndef ")
    # El INSERT atómico primero (1 por día) y, si ya había fila, sólo se reabre la
    # que quedó FALLIDA: una fila `enviado` de hoy NO se reenvía.
    assert "_reclamar_envio(db, alumno_id, tipo, tenant_id=tenant_id)" in helper
    assert "estado = 'fallido'" in helper
    assert "SET estado = 'enviado'" in helper
    assert "WHERE alumno_id = :alumno_id" in helper
    assert "AND dia_chile = :dia" in helper


def test_c3_los_senders_nuevos_usan_su_tipo_manual_y_aceptan_registrar():
    fuente = _fuente("backend/app/services/email_service.py")
    for fn, tipo in (("send_clase_prueba", "prueba_clase_manual"),
                     ("send_contratar_plan", "prueba_plan_manual"),
                     ("send_aviso_retiro", "pedido_recordatorio_manual")):
        cuerpo = _bloque(fuente, f"def {fn}(", "\n\ndef ")
        assert f'tipo="{tipo}"' in cuerpo
        # Sin default: el envío manual SIEMPRE decide quién registra (el endpoint).
        assert "registrar: bool)" in cuerpo
        assert "registrar=registrar" in cuerpo


# ── D. "Nuevos del mes" comparte la definición del KPI del panel ─────────────

def test_d1_el_listado_usa_los_bordes_de_mes_de_reportes():
    fuente = _fuente("backend/app/api/v1/admin.py")
    assert "from app.api.v1.reportes import _inicio_fin_mes" in fuente
    endpoint = _bloque(fuente, "def get_alumnos_nuevos", "\n@router.")
    assert "_inicio_fin_mes()" in endpoint
    # Rol alumno + ventana de created_at entre los dos bordes.
    assert "RolUsuario.alumno" in endpoint
    assert "Usuario.created_at >= inicio" in endpoint
    assert "Usuario.created_at <= fin" in endpoint


def test_d2_el_kpi_del_panel_cuenta_lo_mismo():
    reportes = _fuente("backend/app/api/v1/reportes.py")
    assert "nuevosAlumnosMes" in reportes
    assert "SELECT COUNT(*) FROM usuarios" in reportes
    assert "created_at >= :inicio" in reportes


# ── E. La asistencia de la prueba (y el banner del escritorio intacto) ────────

def test_e1_asistir_es_reservas_asistio_dentro_del_periodo_de_la_prueba():
    fuente = _fuente("backend/app/api/v1/admin.py")
    helper = _bloque(fuente, "def _alumnos_con_asistencia_de_prueba",
                     "\ndef _alumnos_con_plan_vigente")
    assert "Reserva.asistio.is_(True)" in helper     # reservar NO es asistir
    assert "fecha_clase >= inicio" in helper         # dentro de la ventana de la prueba
    # Una sola consulta con IN para toda la página (no N+1).
    assert "Reserva.alumno_id.in_(alumno_ids)" in helper


def test_e2_el_banner_de_prueba_hoy_del_escritorio_no_cambio():
    fuente = _fuente("backend/app/api/v1/admin.py")
    banner = _bloque(fuente, "def get_alumnos_prueba_hoy", "def dias_desde_inscripcion")
    # Sigue siendo "los de HOY" (created_at >= inicio del día chileno) y sin filtros
    # nuevos: la regla de oro es que ≥768px queda igual que hoy.
    assert "Usuario.created_at >= inicio_hoy" in banner
    assert "da_acceso_hoy" not in banner
    assert "plan_comercial" not in banner


# ── F. Las plantillas nuevas salen con los datos REALES ──────────────────────

def test_f1_clase_prueba_lleva_el_nombre_los_dias_y_la_marca():
    asunto, html = render_email_clase_prueba("Camila Soto", 3)
    assert "Camila Soto" in html
    assert "3 d" in html                    # "hace 3 días"
    assert "URBAN TRAINING BOX" in html     # encabezado de marca (_template)
    assert asunto


def test_f2_clase_prueba_el_mismo_dia_no_dice_hace_cero_dias():
    _, html = render_email_clase_prueba("Camila Soto", 0)
    assert "hoy mismo" in html
    assert "hace 0" not in html


def test_f3_contratar_plan_invita_a_elegir_plan():
    asunto, html = render_email_contratar_plan("Camila Soto")
    assert "Camila Soto" in html
    assert "/alumno/solicitar-plan" in html   # CTA al flujo de contratación
    assert asunto


def test_f4_aviso_retiro_lleva_producto_cantidad_y_codigo():
    asunto, html = render_email_aviso_retiro("Camila Soto", "Botella", 2, "UB-7K3M")
    assert "Camila Soto" in html
    assert "Botella" in html
    assert "x2" in html
    assert "UB-7K3M" in html
    assert "UB-7K3M" in asunto or "pedido" in asunto


def test_e3_los_convertidos_no_entran_en_el_listado():
    fuente = _fuente("backend/app/api/v1/admin.py")
    endpoint = _bloque(fuente, "def get_alumnos_en_prueba", "\n@router.")
    assert 'if alumno["estado"] != "convertido"' in endpoint
    assert '"sin_clase": sum(1 for a in listados' in endpoint


# ── G. La pantalla móvil está cableada a los endpoints REALES ────────────────

def test_g1_la_tarjeta_y_la_pantalla_usan_los_endpoints_nuevos():
    fuente = _fuente("frontend/src/pages/admin/InicioMobileAdmin.jsx")
    assert "api.get('/api/v1/admin/alumnos-prueba')" in fuente
    assert "api.get('/api/v1/admin/alumnos-nuevos')" in fuente
    assert "/invitacion/preview`)" in fuente      # vista previa (GET, sin efectos)
    assert "/invitacion`)" in fuente              # envío (POST)
    # Las dos secciones de la pantalla completa.
    assert ">En prueba<" in fuente
    assert ">Nuevos del mes<" in fuente


def test_g2_la_fila_muestra_el_envio_manual_y_lleva_a_la_ficha():
    fuente = _fuente("frontend/src/pages/admin/InicioMobileAdmin.jsx")
    assert "Correo enviado " in fuente and "textoHace(a.ultimo_envio)" in fuente
    # Tocar un nombre abre la FICHA del alumno (misma ruta que el buscador).
    assert "/admin/alumnos/${alumnoId}/historial" in fuente
    # La vista previa se muestra en un iframe sandbox (no editable, sin scripts).
    assert 'sandbox="" srcDoc={correo.preview.html}' in fuente


def test_g3_la_tarjeta_suma_la_quinta_kpi_sin_tocar_las_cuatro_de_antes():
    fuente = _fuente("frontend/src/pages/admin/InicioMobileAdmin.jsx")
    assert 'testid="kpi-prueba"' in fuente
    # Las cuatro tarjetas originales siguen declaradas tal cual.
    for etiqueta in ('label="Alumnos activos"', 'label="Vencen en 5 días"',
                     'label="Vouchers por aprobar"', 'label="Ingresos de hoy"'):
        assert etiqueta in fuente
    assert 'label="Alumnos nuevos y en prueba"' in fuente

