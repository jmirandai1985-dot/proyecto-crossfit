"""Modelo `TokenMigracionBoxmagic` — AISLADO (sin BD ni red).

Verifica el contrato del modelo que usa el envío masivo de activación:

  * tabla y columnas exactas (mismo patrón que `PasswordResetToken`);
  * `candidato_id` cuelga de `candidatos_boxmagic.id` con CASCADE;
  * `token_hash` es UNIQUE y de 64 caracteres (sha256 hex, nunca el token);
  * `expires_at` obligatorio y `used_at` nullable (token de un solo uso);
  * `correo_migracion_enviado_en` existe en el padrón y es nullable.

    cd backend && py -3.12 -m pytest tests/test_token_migracion_boxmagic_modelo.py -q --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.candidato_boxmagic import CandidatoBoxmagic  # noqa: E402
from app.models.password_reset_token import PasswordResetToken  # noqa: E402
from app.models.token_migracion_boxmagic import TokenMigracionBoxmagic  # noqa: E402


def test_tabla_y_columnas():
    tabla = TokenMigracionBoxmagic.__table__

    assert tabla.name == "tokens_migracion_boxmagic"
    assert list(tabla.columns.keys()) == [
        "id", "candidato_id", "token_hash", "expires_at", "used_at", "created_at",
    ]


def test_fk_al_padron_con_cascade():
    tabla = TokenMigracionBoxmagic.__table__
    fk = next(iter(tabla.columns["candidato_id"].foreign_keys))

    assert fk.target_fullname == "candidatos_boxmagic.id"
    assert fk.ondelete == "CASCADE"
    assert tabla.columns["candidato_id"].nullable is False


def test_token_hash_unico_y_del_largo_de_sha256():
    columna = TokenMigracionBoxmagic.__table__.columns["token_hash"]

    assert columna.unique is True
    assert columna.nullable is False
    assert columna.type.length == 64


def test_vigencia_y_uso_unico():
    tabla = TokenMigracionBoxmagic.__table__

    assert tabla.columns["expires_at"].nullable is False
    # NULL = todavía no se usó (token de un solo uso).
    assert tabla.columns["used_at"].nullable is True
    assert tabla.columns["created_at"].nullable is False


def test_mismo_patron_que_password_reset():
    """El modelo nuevo no inventa un patrón: calca el del reset de contraseña."""
    nuevo = TokenMigracionBoxmagic.__table__
    reset = PasswordResetToken.__table__

    assert nuevo.columns["token_hash"].type.length == reset.columns["token_hash"].type.length
    assert nuevo.columns["expires_at"].nullable == reset.columns["expires_at"].nullable
    assert nuevo.columns["used_at"].nullable == reset.columns["used_at"].nullable


def test_columna_de_envio_en_el_padron():
    columna = CandidatoBoxmagic.__table__.columns["correo_migracion_enviado_en"]

    # NULL = todavía no se le mandó (no hay backfill: es el dato real).
    assert columna.nullable is True
