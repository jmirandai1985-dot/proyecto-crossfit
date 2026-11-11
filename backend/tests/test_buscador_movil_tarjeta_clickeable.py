"""Buscador del Dashboard móvil (admin): tarjeta clickeable y créditos usados/total.

Guarda de fuente (sin red ni base): inspecciona el código del front y del backend.

  A. La tarjeta de resultado del buscador es TODA clickeable (role="button" +
     onClick → setAlumnoSeleccionadoId) y ya NO tiene los botones WhatsApp / "Ver perfil".
  B. El import `enlaceWhatsapp` y la constante `wa` desaparecieron (ya no se arma el link).
  C. El recuadro "Créditos" muestra "usados de total" (total - disponibles) con el
     fallback al rótulo compartido `rotuloCreditos` cuando no hay total.
  D. El tercer recuadro es "Plan" (nombre del plan), repetido a propósito.
  E. `/planes/membresia-activa` expone `clases_totales` (total del cupo) para el cálculo.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_buscador_movil_tarjeta_clickeable.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit
INICIO = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
PLANES = "backend/app/api/v1/planes.py"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_tarjeta_clickeable_y_sin_botones():
    d = _fuente(INICIO)
    # Toda la tarjeta abre la ficha (sin pasar por un botón).
    assert 'role="button"' in d
    assert "onClick={() => setAlumnoSeleccionadoId(a.id)}" in d
    # Ya no hay botón de "Ver perfil" ni enlace de WhatsApp.
    assert "Ver perfil" not in d
    assert "enlaceWhatsapp" not in d
    assert "wa wa-link" not in d
    assert "st-actions" not in d


def test_creditos_muestran_usados_de_total():
    d = _fuente(INICIO)
    assert "m.creditos_totales - m.creditos_disponibles" in d
    assert "de ${m.creditos_totales}" in d
    # Fallback al rótulo compartido cuando no hay total (o es ilimitado).
    assert "rotuloCreditos(m?.es_ilimitado, m?.creditos_disponibles)" in d


def test_tercer_recuadro_es_plan():
    d = _fuente(INICIO)
    assert "<small>Plan</small>" in d
    assert "m?.plan_nombre || '—'" in d


def test_backend_expone_clases_totales():
    p = _fuente(PLANES)
    # Caso sin suscripción y caso con suscripción.
    assert '"clases_totales": None' in p
    assert '"clases_totales": suscripcion.creditos_totales' in p
