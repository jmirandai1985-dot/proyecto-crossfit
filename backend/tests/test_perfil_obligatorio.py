"""D2 — perfil obligatorio: peso y género (decisión de negocio 2026-10-28).

QUÉ FIJA ESTE ARCHIVO
---------------------
1. El ALTA (`RegistroAlumnoNuevo`) exige `sexo` (M/F) y `peso` EN EL ENDPOINT, no solo en el
   formulario. En PROD había 404 alumnos sin perfil completo porque el alta los aceptaba en
   NULL; sin esos datos `nivel_service` no puede clasificar fuerza (ratio) ni elegir la tabla
   M/F de gimnasia.
2. El alumno puede COMPLETAR su género UNA vez si está vacío (`PUT /alumnos/me`); si ya tiene
   valor, el endpoint responde 409 y la corrección es del box.
3. El coach puede cargar/corregir ambos datos desde la ficha (`PUT .../alumno/{id}/perfil`),
   que es la vía para cerrar los perfiles viejos. Ambos endpoints auditan el cambio.
4. El front: alta con `required`, banner "Completá tu perfil" en el layout del alumno y el
   formulario de la ficha del coach.

Correr (aislado, sin DB):
    cd backend && py -3.12 -m pytest tests/test_perfil_obligatorio.py -q --noconftest
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
RAIZ = BACKEND.parent

# El import de los routers construye settings: sin entorno explícito el cargador avisa y
# puede fallar. Los tests corren siempre contra TEST.
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


# ── 1. Alta: sexo y peso obligatorios ─────────────────────────────────────────
def _alta(**extra):
    from app.api.v1.alumnos import RegistroAlumnoNuevo

    base = {"nombre": "Ana Pérez", "correo": "ana@example.com",
            "rut": "12345678-5", "sexo": "F", "peso": 62.5}
    base.update(extra)
    return RegistroAlumnoNuevo(**base)


def test_el_alta_acepta_sexo_y_peso_validos():
    datos = _alta()
    assert (datos.sexo, datos.peso) == ("F", 62.5)


def test_el_alta_rechaza_sin_sexo():
    with pytest.raises(ValidationError):
        _alta(sexo=None)


def test_el_alta_rechaza_sin_peso():
    with pytest.raises(ValidationError):
        _alta(peso=None)


def test_el_alta_rechaza_genero_fuera_de_m_f():
    with pytest.raises(ValidationError):
        _alta(sexo="otro")


def test_el_alta_normaliza_minusculas_y_acepta_peso_kg():
    from app.api.v1.alumnos import RegistroAlumnoNuevo

    datos = RegistroAlumnoNuevo(
        nombre="Ana", correo="ana@example.com", rut="12345678-5",
        sexo="f", peso_kg=60)
    assert datos.sexo == "F"
    assert datos.peso == 60.0


# ── 2. El alumno completa su género una sola vez ──────────────────────────────
def test_el_genero_es_autogestionable_pero_ya_no_es_campo_solo_box():
    from app.api.v1.alumnos import ActualizarMiPerfil

    assert "genero" in ActualizarMiPerfil.CAMPOS_AUTOEDITABLES
    assert "genero" not in ActualizarMiPerfil.CAMPOS_SOLO_BOX


def test_el_validador_no_descarta_el_genero_del_put_me():
    from app.api.v1.alumnos import ActualizarMiPerfil

    datos = ActualizarMiPerfil.model_validate(
        {"peso_kg": 70, "genero": "f", "nombre": "No se toca"})
    volcado = datos.model_dump(exclude_unset=True)
    assert volcado.get("genero") == "f"
    assert "nombre" not in volcado


def test_el_endpoint_me_solo_completa_genero_vacio_y_audita():
    """El 409 está en el endpoint (necesita el valor ACTUAL, no lo sabe el schema)."""
    fuente = _fuente("backend/app/api/v1/alumnos.py")
    desde = fuente.index("def actualizar_mi_perfil(")
    cuerpo = fuente[desde:fuente.index('@router.get("/me/es-prueba")', desde)]
    assert "genero_anterior = usuario.genero" in cuerpo
    assert "status_code=409" in cuerpo
    assert "registrar_auditoria(" in cuerpo
    assert "genero_anterior" in cuerpo and "genero_nuevo" in cuerpo


# ── 3. El coach corrige desde la ficha ────────────────────────────────────────
def test_el_perfil_del_coach_valida_peso_y_genero():
    from app.api.v1.fidelizacion import PerfilNivelAlumno

    ok = PerfilNivelAlumno(peso_kg=80, genero="m")
    assert (ok.peso_kg, ok.genero) == (80.0, "M")

    with pytest.raises(ValidationError):
        PerfilNivelAlumno(peso_kg=0, genero="M")
    with pytest.raises(ValidationError):
        PerfilNivelAlumno(peso_kg=80, genero="otro")
    with pytest.raises(ValidationError):
        PerfilNivelAlumno(peso_kg=80, genero="M", otro="no permitido")


def test_la_ficha_del_coach_expone_los_datos_y_el_endpoint_audita():
    fuente = _fuente("backend/app/api/v1/fidelizacion.py")
    assert '@router.put("/coach/{coach_id}/alumno/{alumno_id}/perfil")' in fuente
    assert '"peso_kg": alumno.peso_kg' in fuente
    assert '"perfil_completo"' in fuente
    assert '"origen": "ficha_coach"' in fuente

    # El admin también puede corregir género, pero sólo M/F.
    from app.schemas.usuario import UsuarioUpdate

    assert UsuarioUpdate(genero="f").genero == "F"
    with pytest.raises(ValidationError):
        UsuarioUpdate(genero="otro")


# ── 4. Frontend ───────────────────────────────────────────────────────────────
def test_el_alta_del_front_marca_los_campos_como_obligatorios():
    fuente = _fuente("frontend/src/components/RegistroAlumnoNuevo.jsx")
    assert 'name="sexo"' in fuente and "required" in fuente
    assert 'name="peso"' in fuente
    # Ya no manda null: el backend lo rechaza.
    assert "sexo: form.sexo," in fuente
    assert "peso: parseFloat(form.peso)," in fuente

    landing = _fuente("frontend/src/pages/LandingPage.jsx")
    assert "value={formData.genero}" in landing and "required" in landing
    assert "value={formData.peso_kg}" in landing


def test_el_banner_del_alumno_esta_montado_en_el_layout():
    fuente = _fuente("frontend/src/components/BannerPerfilIncompleto.jsx")
    assert "faltaPeso" in fuente and "faltaGenero" in fuente
    assert "/alumno/ajustes" in fuente

    layout = _fuente("frontend/src/components/Layout.jsx")
    assert "BannerPerfilIncompleto" in layout
    assert "rol === 'alumno' && <BannerPerfilIncompleto />" in layout


def test_la_ficha_del_coach_tiene_el_formulario_de_perfil():
    fuente = _fuente("frontend/src/components/AlumnoFichaCoach.jsx")
    assert "useActualizarPerfilAlumnoCoach" in fuente
    assert 'data-testid="ficha-peso"' in fuente
    assert 'data-testid="ficha-genero"' in fuente

    queries = _fuente("frontend/src/hooks/queries.js")
    assert "/fidelizacion/coach/${coachId}/alumno/${alumnoId}/perfil" in queries


# ── 5. Alta desde el panel del box (POST /usuarios) ───────────────────────────
def test_el_alta_del_box_acepta_peso_y_genero():
    from app.schemas.usuario import UsuarioCreate

    datos = dict(rut="12345678-5", nombre="Ana", correo="ana@example.com",
                 tenant_id=1, password="Secreta123", rol="alumno")
    assert UsuarioCreate(**datos, peso_kg=70, genero="f").genero == "F"
    with pytest.raises(ValidationError):
        UsuarioCreate(**datos, peso_kg=70, genero="otro")
    with pytest.raises(ValidationError):
        UsuarioCreate(**datos, peso_kg=0, genero="F")


def test_el_modal_del_box_pide_peso_y_genero_para_alumnos():
    fuente = _fuente("frontend/src/pages/admin/Alumnos.jsx")
    assert "formData.rol === 'alumno'" in fuente
    assert 'value={formData.peso_kg}' in fuente
    assert 'value={formData.genero}' in fuente
    assert "peso_kg: formData.rol === 'alumno' ? parseFloat(formData.peso_kg) : null" in fuente

