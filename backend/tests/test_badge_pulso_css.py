"""Badge "En revisión": pulso SOLO cuando hay pendientes (CSS puro).

Guarda de fuente (sin red ni base): la animación vive en `.ub-admin .badge:not(.ok)`
(es decir, cuando SÍ hay pendientes), respeta `prefers-reduced-motion` y no se aplica
al estado vacío `.badge.ok`.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_badge_pulso_css.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CSS = "frontend/src/pages/admin/inicioMobileAdmin.css"


def _css() -> str:
    return (RAIZ / CSS).read_text(encoding="utf-8")


def test_el_pulso_es_solo_del_badge_con_pendientes():
    c = _css()
    assert ".ub-admin .badge:not(.ok) {" in c
    assert "animation: ub-badge-pulso 1.6s ease-in-out infinite;" in c
    # El estado vacío sigue existiendo aparte (gris, sin pulso).
    assert ".ub-admin .badge.ok {" in c


def test_keyframes_y_reduced_motion_apaga_la_animacion():
    c = _css()
    assert "@keyframes ub-badge-pulso {" in c
    assert "50% { transform: scale(1.12); }" in c
    assert "@media (prefers-reduced-motion: reduce) {" in c
    assert "animation: none;" in c
