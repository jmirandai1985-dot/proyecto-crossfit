"""Tests del drill de restore: casos OK y de falla con Neon/R2/psql/smtplib mockeados.

Sin Neon real, sin R2, sin red, sin credenciales y sin mandar correos. Verifican lo que
importa del drill: que la rama temporal se borre SIEMPRE, que no se cree nada si el cupo
de ramas está lleno, que la prueba negativa de PROD sea obligatoria y que el log/email
nunca filtren la password del rol. Y desde el fix del 423: que el drill espere las
`operations` de Neon tras crear la rama y la base, que corte si alguna queda en `failed`
o nunca termina (timeout) y que reintente 423 con backoff sin morir.

Se corre con:
    py -3.12 -m pytest tests/test_restore_drill.py -q --noconftest
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import gzip  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

from maintenance import backup_cloud as bc  # noqa: E402
from maintenance import restore_drill as rd  # noqa: E402

CLAVE_FALSA = "SECRETO_FAKE_no_real"
GMAIL_USER = "urban.training.box.2026@gmail.com"
APP_FAKE = "app-fake-no-real"          # App Password de mentira (nunca sale a la red)
ALEMBIC = "035_precio_snapshot_solicitudes"
# Dump mínimo que SÍ pasa verificar_dump (con MIN_BYTES/MIN_TABLAS bajados en el fixture).
DUMP = (
    "CREATE TABLE public.usuarios (id int);\n"
    "CREATE TABLE public.pagos (id int);\n"
    "COPY public.alembic_version (version_num) FROM stdin;\n"
    f"{ALEMBIC}\n"
    "\\.\n"
    "-- PostgreSQL database dump complete\n"
)
URI_RAMA = ("postgresql://neondb_owner:" + CLAVE_FALSA
            + "@ep-drill-1234.us-east-2.aws.neon.tech/neondb?sslmode=require")
RAMA = "br-drill-999"
OP_RAMA = "op-rama-1"       # operaciones que devuelve Neon en el POST de la rama (asíncrono)
OP_BASE = "op-base-1"       # idem al crear la base drill_restore


class _Paginator:
    def __init__(self, objetos):
        self.objetos = objetos

    def paginate(self, **_):
        yield {"Contents": self.objetos}


class FakeS3:
    """Solo lo que usa bajar_ultimo(): paginador + download_file (escribe un .gz real)."""

    def __init__(self, objetos, texto: str = DUMP):
        self.objetos = objetos
        self.texto = texto

    def get_paginator(self, nombre):
        assert nombre == "list_objects_v2"
        return _Paginator(self.objetos)

    def download_file(self, bucket, key, destino):
        assert bucket == "fake-bucket" and key.endswith(".sql.gz")
        with open(destino, "wb") as f:
            f.write(gzip.compress(self.texto.encode("utf-8")))


def _objeto(kb: float = 200.0, nombre: str = "2026-09-01_0300_neon_backup.sql.gz"):
    return {"Key": f"daily/{nombre}", "Size": int(kb * 1024),
            "LastModified": datetime.now(timezone.utc)}


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    for k, v in (("R2_ENDPOINT", "https://fake.r2.cloudflarestorage.com"),
                 ("R2_BUCKET", "fake-bucket"),
                 ("R2_ACCESS_KEY_ID", "AKIAFAKE"),
                 ("R2_SECRET_ACCESS_KEY", CLAVE_FALSA),
                 ("GMAIL_SMTP_USER", GMAIL_USER),
                 ("GMAIL_SMTP_APP_PASSWORD", APP_FAKE),
                 ("ALERT_EMAIL", "alertas@example.com"),
                 ("NEON_API_KEY", "napi_FAKE_no_real"),
                 ("NEON_PROJECT_ID", "proyecto-fake"),
                 ("PROD_DB_DIRECT_URL", "postgresql://backup_ro:" + CLAVE_FALSA
                                        + "@ep-prod.us-east-2.aws.neon.tech/neondb")):
        monkeypatch.setenv(k, v)
    # El dump de prueba es minúsculo: se bajan los umbrales que usa verificar_dump().
    monkeypatch.setattr(bc, "MIN_BYTES", 10)
    monkeypatch.setattr(bc, "MIN_TABLAS", 1)
    yield


@pytest.fixture
def reportes(monkeypatch):
    """Captura los reportes del drill en vez de mandarlos por Gmail SMTP."""
    capturados = []
    monkeypatch.setattr(rd, "enviar_email",
                        lambda asunto, html: capturados.append((asunto, html)) or True)
    return capturados


def _secuencia(valores):
    it = iter(valores)
    return lambda *_: next(it)


def _mocks(monkeypatch, tablas=(0, 2), restore_rc=0, prod_rc=1,
           prod_err="ERROR:  permission denied for database neondb", con_operaciones=False):
    """Mockea todo lo que sale del proceso: R2, API de Neon, psql y el DELETE de la rama.

    `tablas` es la secuencia que devuelve contar_tablas: primero la comprobación de que
    la base destino está VACÍA y después la verificación del restore.
    """
    rastro = {"creadas": [], "borrados": [], "restores": []}
    monkeypatch.setattr(rd, "cliente_s3", lambda: FakeS3([_objeto()]))
    monkeypatch.setattr(rd, "contar_ramas", lambda: 3)
    monkeypatch.setattr(rd, "branch_default", lambda: "br-padre-123")

    def fake_crear_rama(nombre, parent):
        rastro["creadas"].append((nombre, parent))
        data = {
            "branch": {"id": RAMA, "name": nombre},
            "roles": [{"name": "neondb_owner", "authentication_method": "password"}],
            "connection_uris": [{"connection_uri": URI_RAMA}],
        }
        if con_operaciones:      # Neon es asíncrono: el drill ESPERA estas `operations`
            data["operations"] = [{"id": OP_RAMA, "status": "running"}]
        return data

    monkeypatch.setattr(rd, "crear_rama", fake_crear_rama)

    def fake_crear_base(bid, nombre, owner):
        data = {"database": {"name": nombre}}
        if con_operaciones:
            data["operations"] = [{"id": OP_BASE, "status": "running"}]
        return data

    monkeypatch.setattr(rd, "crear_base", fake_crear_base)
    monkeypatch.setattr(rd, "contar_tablas", _secuencia(tablas))
    monkeypatch.setattr(rd, "borrar_rama",
                        lambda bid: rastro["borrados"].append(bid) or True)

    def fake_restore(url, sql_path):
        rastro["restores"].append((url, Path(sql_path).name))
        err = "" if restore_rc == 0 else f"psql: error: could not connect to {url}"
        return subprocess.CompletedProcess(["psql"], restore_rc, "", err)

    monkeypatch.setattr(rd, "psql_restore", fake_restore)

    def fake_psql(url, sql):
        if rd.TABLA_SONDA in sql:                     # prueba negativa contra PROD
            return subprocess.CompletedProcess(["psql"], prod_rc, "", prod_err)
        if "FROM usuarios" in sql:
            return subprocess.CompletedProcess(["psql"], 0, "7\n", "")
        if "alembic_version" in sql:
            return subprocess.CompletedProcess(["psql"], 0, ALEMBIC + "\n", "")
        return subprocess.CompletedProcess(["psql"], 0, "0\n", "")

    monkeypatch.setattr(rd, "psql_sql", fake_psql)
    # Red de seguridad: sin esto, un descuido del mock llamaría de verdad a console.neon.tech.
    monkeypatch.setattr(rd, "http_json", lambda *a, **k: pytest.fail(
        "estos tests no tocan la red: http_json tiene que estar mockeado (ver _fake_operaciones)"))
    return rastro


def _repetido(valores):
    """Generador que repite el último valor para siempre (para simular un 'running' eterno)."""
    ultimo = valores[-1]
    for v in valores:
        yield v
    while True:
        yield ultimo


def _sin_dormir(monkeypatch):
    """Sin sleeps reales (ni polling ni backoff): se registran para poder verificarlos."""
    dormidas = []
    monkeypatch.setattr(rd.time, "sleep", lambda s: dormidas.append(s))
    return dormidas


def _fake_operaciones(monkeypatch, estados, fallos_423=0):
    """`http_json` falso para el polling de `GET /projects/{id}/operations/{op_id}`.

    `estados`: estados que devuelve la operación (el último se repite indefinidamente).
    `fallos_423`: cuántos intentos iniciales responden HTTP 423 (Neon con operaciones vivas).
    """
    llamadas = []
    estados_it = _repetido(estados)

    def fake(method, url, body=None, headers=None):
        llamadas.append((method, url))
        if len(llamadas) <= fallos_423:
            return 423, {"error": "project already has running conflicting operations, "
                                  "scheduling of new ones is prohibited"}
        return 200, {"operation": {"id": "op-fake", "status": next(estados_it)}}

    monkeypatch.setattr(rd, "http_json", fake)
    return llamadas


def test_a_drill_ok_borra_la_rama_y_avisa(monkeypatch, reportes, capsys):
    rastro = _mocks(monkeypatch, tablas=(0, 2))
    assert rd.main() == rd.EXIT_OK
    assert rastro["creadas"] and rastro["creadas"][0][1] == "br-padre-123"
    assert rastro["borrados"] == [RAMA]            # la rama temporal se borra SIEMPRE
    assert rastro["restores"] and "drill_restore" in rastro["restores"][0][0]
    assert len(reportes) == 1 and "OK" in reportes[0][0]
    cap = capsys.readouterr()
    assert CLAVE_FALSA not in (cap.out + cap.err)  # ni la password del rol en el log


def test_b_prueba_negativa_no_falla_es_critico(monkeypatch, reportes):
    """Si el rol de backup PUDO escribir en PROD (rc=0) ⇒ exit 11 y alerta crítica."""
    rastro = _mocks(monkeypatch, tablas=(0, 2), prod_rc=0, prod_err="")
    assert rd.main() == rd.EXIT_PERMISOS
    assert rastro["borrados"] == [RAMA]
    assert "FALLA" in reportes[0][0]
    assert "CRÍTICO" in reportes[0][1]
    assert "PUDO CREAR UNA TABLA EN PROD" in reportes[0][1]


def test_c_restore_falla_exit_10_y_salida_saneada(monkeypatch, reportes, capsys):
    rastro = _mocks(monkeypatch, tablas=(0,), restore_rc=1)
    assert rd.main() == rd.EXIT_RESTORE
    assert rastro["borrados"] == [RAMA]
    assert "FALLA" in reportes[0][0]
    cap = capsys.readouterr()
    salida = cap.out + cap.err
    assert "://***@" in salida                 # la URI con password sale SANEADA
    assert CLAVE_FALSA not in salida           # y la password nunca aparece
    assert CLAVE_FALSA not in "".join(a + h for a, h in reportes)


def test_d_base_destino_no_vacia_aborta_sin_restaurar(monkeypatch, reportes):
    rastro = _mocks(monkeypatch, tablas=(1,))          # la base destino ya tiene 1 tabla
    assert rd.main() == rd.EXIT_RESTORE
    assert rastro["restores"] == []        # no se restauró NADA: no hay DROP ni pisada
    assert rastro["borrados"] == [RAMA]    # y la rama temporal se borra igual
    assert "FALLA" in reportes[0][0] and "NO está vacía" in reportes[0][1]


def test_e_cupo_de_ramas_agotado_no_crea_nada(monkeypatch, reportes):
    """Free permite 10 ramas: si el proyecto ya está en el tope, exit 2 sin crear rama."""
    rastro = _mocks(monkeypatch, tablas=(0, 2))
    monkeypatch.setattr(rd, "contar_ramas", lambda: rd.MAX_RAMAS)
    assert rd.main() == rd.EXIT_CONFIG
    assert rastro["creadas"] == [] and rastro["borrados"] == []
    assert "ramas" in reportes[0][1]


def test_f_dump_ilegible_no_crea_rama(monkeypatch, reportes):
    rastro = _mocks(monkeypatch, tablas=(0, 2))
    monkeypatch.setattr(rd, "cliente_s3", lambda: FakeS3([_objeto()], texto="CREATE TABLE x;"))
    assert rd.main() == rd.EXIT_DESCARGA
    assert rastro["creadas"] == [] and rastro["borrados"] == []   # no se llegó a crear nada
    assert "FALLA" in reportes[0][0]


def test_g_sin_neon_api_key_exit_2(monkeypatch, reportes):
    """Sin credenciales de Neon no se toca la API: exit 2 y no hay rama que borrar."""
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    rastro = _mocks(monkeypatch, tablas=(0, 2))
    assert rd.main() == rd.EXIT_CONFIG
    assert rastro["creadas"] == [] and rastro["borrados"] == []
    assert reportes == []     # sin config no se puede avisar por email


def test_h_423_dos_veces_reintenta_con_backoff_y_termina_ok(monkeypatch, reportes):
    """Neon contesta 423 (operaciones en curso) 2 veces: el drill reintenta y termina OK."""
    rastro = _mocks(monkeypatch, tablas=(0, 2), con_operaciones=True)
    dormidas = _sin_dormir(monkeypatch)
    llamadas = _fake_operaciones(monkeypatch, ["finished"], fallos_423=2)

    assert rd.main() == rd.EXIT_OK
    assert rastro["borrados"] == [RAMA]
    assert len(llamadas) == 4          # 2 rechazos 423 + 1 ok (rama) + 1 ok (base)
    assert dormidas == [2.0, 4.0]      # backoff 2 s y 4 s: el 423 no es un error nuestro
    assert "OK" in reportes[0][0]


def test_i_operacion_failed_exit_9_y_borra_la_rama(monkeypatch, reportes):
    """Si una operación de Neon queda en 'failed', el drill FALLA (exit 9) y borra la rama."""
    rastro = _mocks(monkeypatch, tablas=(0, 2), con_operaciones=True)
    _sin_dormir(monkeypatch)
    _fake_operaciones(monkeypatch, ["failed"])

    assert rd.main() == rd.EXIT_API
    assert rastro["borrados"] == [RAMA]     # la rama temporal se borra igual
    assert rastro["restores"] == []         # y NO se restauró nada
    assert "FALLA" in reportes[0][0]
    assert "no pude esperar la creación de la rama" in reportes[0][1]
    assert "failed" in reportes[0][1]


def test_j_timeout_de_operaciones_falla_y_borra_la_rama(monkeypatch, reportes):
    """Si la operación nunca queda en 'finished', el drill FALLA por timeout y borra la rama."""
    rastro = _mocks(monkeypatch, tablas=(0, 2), con_operaciones=True)
    _sin_dormir(monkeypatch)
    monkeypatch.setattr(rd, "TIMEOUT_OPS", 0.0)        # sin esperar 120 s de verdad
    monkeypatch.setattr(rd, "TIMEOUT_BORRADO", 0.0)    # ni 60 s en el finally
    llamadas = _fake_operaciones(monkeypatch, ["running"])

    assert rd.main() == rd.EXIT_API
    assert rastro["borrados"] == [RAMA]
    assert llamadas, "el drill tiene que consultar la operación"
    assert "timeout" in reportes[0][1] and OP_RAMA in reportes[0][1]
