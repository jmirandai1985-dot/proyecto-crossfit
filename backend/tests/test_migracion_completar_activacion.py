"""Alta desde el link de activación (`POST .../activacion/completar`) — AISLADO.

SIN BD ni red: app mínima con el router REAL de `migracion_boxmagic.py`, una `get_db`
falsa y filas construidas con los modelos reales (mismo patrón que
`test_migracion_validar_token.py`). Cubre el contrato de la Fase 2 del flujo Magic Link:

  * token inexistente, vencido o ya usado -> el MISMO 404 genérico de `validar-token`
    (no se revela cuál condición falló);
  * happy path -> 200, `Usuario` alumno creado con la contraseña hasheada y las
    aceptaciones con fecha+versión, el token consumido y el candidato 'Completado',
    todo en UN solo commit;
  * password corto / contraseñas distintas / consentimientos sin marcar -> 422 y no se
    escribe nada;
  * correo que ya tiene cuenta en el mismo box -> 409;
  * el RUT es opcional (la cuenta se crea igual, con `rut` NULL).

    cd backend && py -3.12 -m pytest tests/test_migracion_completar_activacion.py -q --noconftest
"""
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import migracion_boxmagic  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.core.security import verify_password  # noqa: E402
from app.models.candidato_boxmagic import (  # noqa: E402
    ESTADO_BOXMAGIC_COMPLETADO, CandidatoBoxmagic,
)
from app.models.token_migracion_boxmagic import TokenMigracionBoxmagic  # noqa: E402
from app.models.usuario import RolUsuario, Usuario  # noqa: E402

TENANT = 1
TOKEN = "token-de-activacion-123"
CONTRASENA = "secreto123"
RUTA = "/api/v1/migracion-boxmagic/activacion/completar"

AHORA = datetime.now(timezone.utc)
DETALLE_GENERICO = "El link de activación es inválido o expiró."
MENSAJE_OK = "Cuenta activada. Ya puedes iniciar sesión."


class _Consulta:
    def __init__(self, filas=None):
        self._filas = list(filas or [])

    def filter(self, *criterios):
        return self

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    """Session mínima que además REGISTRA lo que el endpoint intentó escribir.

    `query(Modelo)` devuelve las filas preparadas para cada tabla (el endpoint no usa
    los criterios: el escenario del test ES el resultado de la consulta).
    """

    def __init__(self, tokens=None, candidatos=None, usuarios=None):
        self._tokens = tokens or []
        self._candidatos = candidatos or []
        self._usuarios = usuarios or []
        self.agregados = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def query(self, modelo):
        if modelo is TokenMigracionBoxmagic:
            return _Consulta(self._tokens)
        if modelo is CandidatoBoxmagic:
            return _Consulta(self._candidatos)
        if modelo is Usuario:
            return _Consulta(self._usuarios)
        return _Consulta([])

    def add(self, obj):
        self.agregados.append(obj)

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _cliente(sesion):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(migracion_boxmagic.router,
                       prefix="/api/v1/migracion-boxmagic")
    app.dependency_overrides[get_db] = lambda: sesion
    return TestClient(app)


def _hash(token=TOKEN):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _fila_token(*, usado=None, vence=None):
    return TokenMigracionBoxmagic(
        id=1, candidato_id=101, token_hash=_hash(),
        expires_at=vence or (AHORA + timedelta(days=7)), used_at=usado,
    )


def _candidato(correo="  Ana.Soto@Test.com "):
    """Fila del padrón tal como la deja el importador: correo sin normalizar."""
    return CandidatoBoxmagic(
        id=101, tenant_id=TENANT, nombre=" Ana Soto ",
        correo=correo, estado_boxmagic="Activo", grupo="activacion",
    )


def _payload(**cambios):
    cuerpo = {
        "token": TOKEN,
        "password": CONTRASENA,
        "password_confirm": CONTRASENA,
        "rut": "12.345.678-9",
        "fecha_nacimiento": "1995-05-20",
        "estatura": 170,
        "peso": 68.5,
        "acepta_tyc": True,
        "acepta_salud": True,
    }
    cuerpo.update(cambios)
    return cuerpo


# ── Token inválido: mismo 404 genérico, sin escribir nada ────────────────────
def test_token_inexistente_404_generico():
    sesion = _SesionFalsa(tokens=[], candidatos=[_candidato()])

    r = _cliente(sesion).post(RUTA, json=_payload())

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == DETALLE_GENERICO
    assert sesion.agregados == [] and sesion.commits == 0


def test_token_vencido_404_generico():
    sesion = _SesionFalsa(
        tokens=[_fila_token(vence=AHORA - timedelta(seconds=1))],
        candidatos=[_candidato()])

    r = _cliente(sesion).post(RUTA, json=_payload())

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == DETALLE_GENERICO
    assert sesion.agregados == [] and sesion.commits == 0


def test_token_ya_usado_404_generico():
    token = _fila_token(usado=AHORA - timedelta(minutes=5))
    sesion = _SesionFalsa(tokens=[token], candidatos=[_candidato()])

    r = _cliente(sesion).post(RUTA, json=_payload())

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == DETALLE_GENERICO
    # El `used_at` viejo NO se pisa: el link no se puede reutilizar.
    assert token.used_at == AHORA - timedelta(minutes=5)
    assert sesion.agregados == [] and sesion.commits == 0


def test_los_tres_fallos_son_indistinguibles():
    """No se puede deducir si el token existió: misma respuesta en los 3 casos."""
    respuestas = []
    for tokens in ([], [_fila_token(usado=AHORA)],
                   [_fila_token(vence=AHORA - timedelta(days=1))]):
        r = _cliente(_SesionFalsa(tokens=tokens,
                                  candidatos=[_candidato()])).post(
            RUTA, json=_payload())
        respuestas.append((r.status_code, r.json()["detail"]))

    assert len(set(respuestas)) == 1


# ── Happy path ──────────────────────────────────────────────────────────────
def test_happy_path_crea_la_cuenta_consume_el_token_y_cierra_el_padron():
    token = _fila_token()
    candidato = _candidato()
    sesion = _SesionFalsa(tokens=[token], candidatos=[candidato])

    r = _cliente(sesion).post(RUTA, json=_payload())

    assert r.status_code == 200, r.text
    assert r.json() == {"mensaje": MENSAJE_OK}

    # Una sola transacción: un commit, sin rollback.
    assert sesion.commits == 1 and sesion.rollbacks == 0
    assert len(sesion.agregados) == 1

    usuario = sesion.agregados[0]
    assert isinstance(usuario, Usuario)
    assert usuario.tenant_id == TENANT            # el box del padrón, no otro
    assert usuario.rol == RolUsuario.alumno
    assert usuario.correo == "ana.soto@test.com"  # normalizado como el padrón
    assert usuario.nombre == "Ana Soto"           # recortado
    assert usuario.rut == "12.345.678-9"
    assert usuario.fecha_nacimiento == date(1995, 5, 20)
    assert usuario.estatura_cm == 170             # el modelo la guarda como entero
    assert usuario.peso_kg == 68.5
    assert usuario.activo is True
    assert usuario.estado == "activo"
    # Eligió su contraseña ahora: no se le fuerza un cambio en el primer login.
    assert usuario.cambiar_password_al_login is False

    # Contraseña hasheada de verdad (nunca en claro) y verificable por el login.
    assert usuario.password_hash != CONTRASENA
    assert CONTRASENA not in usuario.password_hash
    assert verify_password(CONTRASENA, usuario.password_hash) is True
    assert verify_password("otra-clave", usuario.password_hash) is False

    # Consentimientos con fecha + versión (auditoría del alta).
    assert usuario.acepta_tyc_en is not None
    assert usuario.acepta_tyc_version == "1.0"
    assert usuario.acepta_salud_en is not None
    assert usuario.acepta_salud_version == "1.0"

    # Token de un solo uso y padrón cerrado, en la MISMA transacción.
    assert token.used_at is not None
    assert candidato.estado_boxmagic == ESTADO_BOXMAGIC_COMPLETADO == "Completado"


def test_rut_en_blanco_se_guarda_como_null():
    sesion = _SesionFalsa(tokens=[_fila_token()], candidatos=[_candidato()])

    r = _cliente(sesion).post(RUTA, json=_payload(rut="   "))

    assert r.status_code == 200, r.text
    assert sesion.agregados[0].rut is None


def test_el_tenant_sale_del_padron_no_del_cliente():
    candidato = _candidato()
    candidato.tenant_id = 42
    sesion = _SesionFalsa(tokens=[_fila_token()], candidatos=[candidato])

    r = _cliente(sesion).post(RUTA, json=_payload())

    assert r.status_code == 200, r.text
    assert sesion.agregados[0].tenant_id == 42


# ── Validaciones del body -> 422 y sin efectos ──────────────────────────────
def _assert_422_sin_escribir(sesion, respuesta, fragmento):
    assert respuesta.status_code == 422, respuesta.text
    assert fragmento in respuesta.text
    assert sesion.agregados == [] and sesion.commits == 0


def test_password_corto_422():
    sesion = _SesionFalsa(tokens=[_fila_token()], candidatos=[_candidato()])

    r = _cliente(sesion).post(
        RUTA, json=_payload(password="corta", password_confirm="corta"))

    _assert_422_sin_escribir(sesion, r, "password")


def test_passwords_distintas_422():
    sesion = _SesionFalsa(tokens=[_fila_token()], candidatos=[_candidato()])

    r = _cliente(sesion).post(
        RUTA, json=_payload(password_confirm="otra-clave-distinta"))

    _assert_422_sin_escribir(sesion, r, "Las contraseñas no coinciden.")


def test_sin_aceptar_tyc_422():
    sesion = _SesionFalsa(tokens=[_fila_token()], candidatos=[_candidato()])

    r = _cliente(sesion).post(RUTA, json=_payload(acepta_tyc=False))

    _assert_422_sin_escribir(sesion, r, "Términos y Condiciones")


def test_sin_aceptar_salud_422():
    sesion = _SesionFalsa(tokens=[_fila_token()], candidatos=[_candidato()])

    r = _cliente(sesion).post(RUTA, json=_payload(acepta_salud=False))

    _assert_422_sin_escribir(sesion, r, "declaración de salud")


# ── Correo con cuenta real en el mismo box -> 409 ──────────────────────────
def test_correo_duplicado_409():
    sesion = _SesionFalsa(
        tokens=[_fila_token()], candidatos=[_candidato()],
        # Sólo importa que la consulta por correo devuelva una cuenta existente.
        usuarios=[object()])

    r = _cliente(sesion).post(RUTA, json=_payload())

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Ya existe una cuenta con este correo."
    assert sesion.agregados == [] and sesion.commits == 0


def test_sin_rut_la_cuenta_se_crea_igual():
    """El RUT es opcional (migración 091: la columna admite NULL)."""
    sesion = _SesionFalsa(tokens=[_fila_token()], candidatos=[_candidato()])

    r = _cliente(sesion).post(RUTA, json=_payload(rut=None))

    assert r.status_code == 200, r.text
    assert sesion.agregados[0].rut is None

