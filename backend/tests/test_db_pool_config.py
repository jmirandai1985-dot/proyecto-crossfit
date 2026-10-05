"""
Configuración del pool de SQLAlchemy (app/db/database.py): guardas de la decisión.

Por qué existe: `pool_pre_ping` YA se apagó una vez (por los TimeoutError de
checkout del test de carga de 500 logins contra el pooler de Neon) y volver a
apagarlo en silencio significa servir conexiones muertas al runtime: 500 con
"(psycopg2.OperationalError) SSL SYSCALL error: EOF detected". La decisión y su
razón viven en el comentario del módulo; estas pruebas congelan el valor y que la
razón siga escrita.

AISLADO: no toca la BD ni la red (el engine de SQLAlchemy es lazy). Correr con:

    cd backend && py -3.12 -m pytest tests/test_db_pool_config.py -q --noconftest
"""
from pathlib import Path

from app.db.database import engine


def _fuente() -> str:
    raiz = Path(__file__).resolve().parents[1]      # .../backend
    return (raiz / "app" / "db" / "database.py").read_text(encoding="utf-8")


def test_el_engine_valida_la_conexion_antes_de_entregarla():
    """pre_ping ON: el checkout reusado se valida y, si está muerto, reconecta."""
    assert engine.pool._pre_ping is True


def test_el_reciclado_por_tiempo_sigue_activo():
    """El reciclado (5 min) complementa al ping: recicla antes de que Neon cierre."""
    assert engine.pool._recycle == 300


def test_la_razon_de_la_decision_sigue_escrita():
    """El comentario del módulo es la única memoria de por qué no vuelve a False."""
    fuente = _fuente()
    assert "pool_pre_ping=True" in fuente
    assert "pool_pre_ping=False" not in fuente
    assert "SSL SYSCALL error: EOF detected" in fuente
    assert "TimeoutError" in fuente
