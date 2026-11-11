"""Las 3 rutas de correo de inactividad usan la plantilla REAL según la situación.

BUG: `enviar_manual` (POST /notificaciones/enviar-manual), el reenvío
(POST /notificaciones/{id}/reenviar) y la campaña (POST /fidelizacion/campana-email/{id})
mandaban SIEMPRE la plantilla fija de "15-30 días" (`enviar_email_fidelizacion`) para
cualquier alumno. El motor correcto ya existía (`fidelizacion_plantillas.sugerir`/`enviar`).

QUÉ SE FIJA ACÁ:
  A. (sin BD, inspección de fuente) Las TRES rutas delegan en
     `fidelizacion_plantillas.sugerir` + `fidelizacion_plantillas.enviar` y ya NO
     llaman a `enviar_email_fidelizacion(`.
  B. (contra TEST) Un alumno cuya situación real es "plan por vencer" (vence en 2 días)
     NO cae en "15-30 días": `sugerir` devuelve `vencimiento` y `render` sale con esa
     plantilla/tipo.

Correr (aislado):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_notificaciones_plantilla_real.py -q
"""
import ast
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

RAIZ = Path(__file__).resolve().parents[2]
NOTIF = "backend/app/api/v1/notificaciones_enviadas.py"
FIDEL = "backend/app/api/v1/fidelizacion.py"


def _cuerpos(ruta):
    fuente = (RAIZ / ruta).read_text(encoding="utf-8")
    return {n.name: ast.get_source_segment(fuente, n)
            for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)}


def test_a_las_tres_rutas_delegan_en_el_motor_de_plantillas():
    cuerpos = _cuerpos(NOTIF)
    for nombre in ("enviar_manual", "_reenviar_por_tipo"):
        cuerpo = cuerpos[nombre]
        assert "fidelizacion_plantillas.sugerir(db, alumno)" in cuerpo, nombre
        assert ('fidelizacion_plantillas.enviar(db, alumno, '
                'sugerencia["plantilla"])') in cuerpo, nombre
        assert "enviar_email_fidelizacion(" not in cuerpo, nombre

    campana = _cuerpos(FIDEL)["enviar_campana_email"]
    assert "fidelizacion_plantillas.sugerir(db, alumno_obj)" in campana
    assert ('fidelizacion_plantillas.enviar(db, alumno_obj, '
            'sugerencia["plantilla"])') in campana
    assert "enviar_email_fidelizacion(" not in campana


@pytest.fixture(scope="module")
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


def test_b_plan_por_vencer_sugiere_vencimiento_no_15_30(db):
    from app.services import fidelizacion_plantillas as svc
    from app.utils.santiago import SANTIAGO, fin_del_dia_chile, hoy_santiago

    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    hoy = hoy_santiago()
    creado = datetime.combine(hoy - timedelta(days=60), datetime.min.time(),
                              tzinfo=SANTIAGO)
    vence = fin_del_dia_chile(hoy + timedelta(days=2))   # plan POR VENCER (≤ 5 días)
    correo = f"notifplantilla.{sufijo}@test.local"

    tenant = None
    try:
        tenant = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
            {"n": f"Box Notif Plantilla {sufijo}", "s": f"box-notif-{sufijo}",
             "pub": str(uuid.uuid4())}).scalar()
        alumno_id = db.execute(text("""
            INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                                  activo, estado, created_at)
            VALUES (:t, :r, 'Alumno Plantilla TEST', :c, 'x', 'alumno', true,
                    'activo', :alta) RETURNING id"""),
            {"t": tenant, "r": uuid.uuid4().hex[:10], "c": correo,
             "alta": creado}).scalar()
        plan_id = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 20, false, 40000, 30, true, true) RETURNING id"""),
            {"t": tenant, "n": f"Plan Notif Plantilla {sufijo}"}).scalar()
        db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, 'activo', 20, 20, now(), :e)"""),
            {"t": tenant, "u": alumno_id, "p": plan_id, "e": vence})
        db.commit()

        from app.models.usuario import Usuario
        alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()

        sugerencia = svc.sugerir(db, alumno)
        assert sugerencia["plantilla"] == svc.P_VENCIMIENTO, (
            f"esperaba vencimiento, salió {sugerencia['plantilla']} ({sugerencia['motivo']})")

        mensaje = svc.render(db, alumno, sugerencia["plantilla"])
        assert mensaje["plantilla"] == svc.P_VENCIMIENTO
        assert mensaje["tipo_envio"] == svc.TIPO_VENCIMIENTO
        assert mensaje["asunto"], "el correo renderizado debe traer asunto"
    finally:
        db.rollback()
        if tenant:
            try:
                for tabla in ("suscripciones", "usuarios", "planes"):
                    db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"),
                               {"t": tenant})
                db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
                db.commit()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                print(f"\n[WARN] no se pudo limpiar el escenario plantilla: {e}")
