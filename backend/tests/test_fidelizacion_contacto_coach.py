"""El correo de contacto del coach usa el MISMO motor de plantillas que Fidelización admin.

BUG (Parte D): `preview_correo_contacto` y `contactar_alumno_por_email` llamaban directo a
`render_email_fidelizacion` / `enviar_email_fidelizacion` (plantilla fija del tramo "15-30 días")
para CUALQUIER alumno de la lista de Riesgo, aunque nunca hubiera entrenado o tuviera otro caso.
El motor correcto ya existía (`_sugerir_con`, usado en la pantalla de Fidelización del admin).

QUÉ SE FIJA ACÁ (sin BD, igual patrón que `test_riesgo_fuente_real.py`):
  A. Los DOS endpoints (preview y envío) eligen la plantilla con `fidelizacion_plantillas.sugerir`
     (la MISMA función para ambos: no se duplica la heurística) y ya NO usan el render fijo.
  B. Ambos manejan el caso "sin situación" (`plantilla: None`) con un 400 con el motivo, en vez de
     mandar un correo forzado.

Los 3 casos de selección (nunca asistió sin plan -> `inactividad_mas_30`, plan activo sin estrenar
-> `plan_sin_usar`, 20 días con plan vigente -> `inactividad_15_30`) los fija ya
`test_fidelizacion_plantillas.py` sobre `sugerir()`: acá se fija que el endpoint de contacto lo
delegue en esa ÚNICA regla.

Correr (aislado y sin base):
    cd backend && py -3.12 -m pytest tests/test_fidelizacion_contacto_coach.py -q --noconftest
"""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
FIDELIZACION = "backend/app/api/v1/fidelizacion.py"

ENDPOINTS_CONTACTO = (
    "preview_correo_contacto",   # GET  /fidelizacion/coach/{id}/contactar/{alumno}/preview
    "contactar_alumno_por_email",  # POST /fidelizacion/coach/{id}/contactar/{alumno}
)


def _fuente() -> str:
    return (RAIZ / FIDELIZACION).read_text(encoding="utf-8")


def _cuerpos(fuente: str) -> dict:
    return {n.name: ast.get_source_segment(fuente, n)
            for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)}


def test_a_los_dos_endpoints_delegan_en_el_motor_de_sugerencia():
    """preview y envío llaman `fidelizacion_plantillas.sugerir` (NO el render fijo)."""
    fuente = _fuente()
    cuerpos = _cuerpos(fuente)
    for nombre in ENDPOINTS_CONTACTO:
        assert nombre in cuerpos, f"desapareció {nombre}"
        cuerpo = cuerpos[nombre]
        assert "fidelizacion_plantillas.sugerir(db, alumno)" in cuerpo, (
            f"{nombre} no usa el motor de sugerencia (¿volvió a una plantilla fija?)")
        assert "render_email_fidelizacion" not in cuerpo, (
            f"{nombre} sigue usando la plantilla fija de inactividad")
        assert "enviar_email_fidelizacion" not in cuerpo, (
            f"{nombre} sigue usando el envío directo sin plantilla")


def test_b_preview_y_envio_renderizan_lo_mismo_pero_cada_uno_su_paso():
    """preview usa `render` y envío usa `enviar` del MISMO servicio (misma selección)."""
    cuerpos = _cuerpos(_fuente())
    assert "fidelizacion_plantillas.render(db, alumno, plantilla_id)" in \
        cuerpos["preview_correo_contacto"], "el preview no renderiza con el servicio"
    assert "fidelizacion_plantillas.enviar(db, alumno, plantilla_id)" in \
        cuerpos["contactar_alumno_por_email"], "el envío no usa la puerta única del servicio"


def test_c_la_situacion_nula_es_un_400_y_no_un_correo_forzado():
    """Si `sugerir` devuelve `plantilla: None` (sin situación), ambos responden 400 con motivo."""
    cuerpos = _cuerpos(_fuente())
    for nombre in ENDPOINTS_CONTACTO:
        cuerpo = cuerpos[nombre]
        assert "plantilla_id is None" in cuerpo, f"{nombre} no contempla el caso sin situación"
        assert "status.HTTP_400_BAD_REQUEST" in cuerpo, f"{nombre} no responde 400 sin situación"
        assert 'sugerencia["motivo"]' in cuerpo, f"{nombre} no informa el motivo en el 400"
