"""Tests del mantenimiento PROD 2× al mes: casos OK y de falla con psql/SMTP mockeados.

Sin Neon, sin red, sin credenciales y sin mandar ningún correo. Verifican lo que importa del
job: que sin `MAINT_DB_URL` no se toque la base, que se rechacen el pooler y cualquier rol
que no sea `maint_rw`, que `ENVIRONMENT` tenga que ser `production`, que un `MAX_CAMBIOS`
inválido no pueda llegar al SQL, que la transacción termine en `ROLLBACK` en DRY-RUN y en
`COMMIT` (con la guarda de volumen adentro) en REAL, que la guarda no aborte en DRY-RUN pero
sí informe con la lista COMPLETA, que un fallo de escritura no se cuente como éxito, que la
verificación posterior sea obligatoria, que la integridad ponga el run rojo **sin** abortar
la escritura, y que ni el log ni el mail puedan filtrar la password del rol.

Se corre con:
    py -3.12 -m pytest tests/test_mantenimiento_cloud.py -q --noconftest
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import subprocess  # noqa: E402

import pytest  # noqa: E402

from maintenance import mantenimiento_cloud as men  # noqa: E402

CLAVE_FALSA = "SECRETO_FAKE_no_real"
URL = ("postgresql://maint_rw:" + CLAVE_FALSA
       + "@ep-prod-1234.us-east-2.aws.neon.tech/neondb?sslmode=require")
GMAIL_USER = "urban.training.box.2026@gmail.com"
APP_FAKE = "app-fake-no-real"          # App Password de mentira (nunca sale a la red)
ALEMBIC = "035_precio_snapshot_solicitudes"


# ── Doble de `correr()`: psql nunca se ejecuta de verdad ──────────────────────
def _filas(*filas) -> str:
    return "".join("|".join(str(c) for c in fila) + "\n" for fila in filas)


def _n_filas(n: int, estado: str = "activo") -> list:
    return [[str(1000 + i), f"Alumno {i}", "Plan Mensual", "2026-09-01", estado]
            for i in range(n)]


def script_out(vencidos=0, susc=0, solic=0, users=0) -> str:
    """Salida realista de la transacción: los tags de comando + el resumen `paso|n`.

    psql imprime los tags (`BEGIN`, `SET`, `CREATE TABLE`, `INSERT 0 n`, `DO`, `ROLLBACK`…)
    aunque se use `-tA`, así que el fake los incluye a propósito: si el parser dependiera de
    que no estuvieran, estos tests fallarían.
    """
    return ("BEGIN\nSET\nCREATE TABLE\nINSERT 0 1\nINSERT 0 0\nINSERT 0 0\nINSERT 0 0\nDO\n"
            f"vencidos|{vencidos}\nhuerfanas_suscripciones|{susc}\n"
            f"huerfanas_solicitudes|{solic}\nhuerfanas_usuarios|{users}\nROLLBACK\n")


def _ctx(**kw) -> dict:
    """Estado de la base simulada. `despues='vacio'` simula que en REAL se aplicó de verdad."""
    ctx = {"vencidos": [], "susc_pendientes": [], "solicitudes": [], "usuarios_pendientes": [],
           "dup_rut": [], "dup_correo": [], "sin_usuario": "0", "sin_plan": "0",
           "fechas_malas": "0", "tamano_mb": 100, "script_out": script_out(),
           "script_rc": 0, "script_err": "", "despues": "igual"}
    ctx.update(kw)
    return ctx


def _respuesta(sql: str, ctx: dict, vistas: dict) -> str:
    """Respuesta de cada SELECT. Si aparece una consulta no contemplada, el test falla: así
    una consulta nueva nunca se cuela sin comportamiento definido."""
    for marcador, clave in (("s.fecha_expiracion < current_date", "vencidos"),
                            ("s.estado = 'pendiente'", "susc_pendientes"),
                            ("FROM solicitudes_planes", "solicitudes"),
                            ("u.estado = 'pendiente_activacion'", "usuarios_pendientes")):
        if marcador in sql:
            vistas[clave] = vistas.get(clave, 0) + 1
            if vistas[clave] > 1 and ctx["despues"] == "vacio":
                return ""                       # verificación posterior: la lista quedó vacía
            return _filas(*ctx[clave])

    if "WHERE u.id IS NULL" in sql:
        return ctx["sin_usuario"] + "\n"
    if "WHERE p.id IS NULL" in sql:
        return ctx["sin_plan"] + "\n"
    if "fecha_expiracion < fecha_inicio" in sql:
        return ctx["fechas_malas"] + "\n"
    if "HAVING count(*) > 1" in sql:
        return _filas(*ctx["dup_rut" if "rut" in sql else "dup_correo"])
    if "FROM alembic_version" in sql:
        return ALEMBIC + "\n"
    if "pg_database_size" in sql:
        return str(int(ctx["tamano_mb"] * 1024 * 1024)) + "\n"
    if "pg_stat_user_tables" in sql:
        return _filas(("usuarios", "120"), ("asistencias", "900"))
    if "rol = 'alumno' AND activo = true" in sql:
        return "87\n"
    if "rol = 'alumno' AND created_at" in sql:
        return "3\n"
    if "rol = 'alumno'" in sql:
        return "150\n"
    if "estado = 'vencido' AND updated_at" in sql:
        return "9\n"
    if "suscripciones WHERE estado = 'activo'" in sql:
        return "60\n"
    if "tipo = 'ingreso'" in sql:
        return "120000\n" if "fecha <" in sql else "150000\n"
    if "SELECT count(*)::text FROM usuarios" in sql:      # sonda de conexión (va al final)
        return "150\n"
    raise AssertionError(f"consulta no contemplada en el doble de psql: {sql[:100]}")


def _psql_falso(monkeypatch, ctx: dict) -> dict:
    """Mockea TODO lo que sale del proceso: `psql` (lecturas y transacción)."""
    rastro = {"scripts": [], "sql": [], "vistas": {}}

    def fake(cmd):
        assert cmd[0] == "psql", f"solo debería correr psql: {cmd[0]}"
        if "-f" in cmd:                                   # la transacción de escritura
            script = Path(cmd[cmd.index("-f") + 1]).read_text(encoding="utf-8")
            rastro["scripts"].append(script)
            rc, err = ctx["script_rc"], ctx["script_err"]
            return subprocess.CompletedProcess(cmd, rc, "" if rc else ctx["script_out"], err)
        sql = cmd[cmd.index("-c") + 1]
        rastro["sql"].append(sql)
        return subprocess.CompletedProcess(cmd, 0, _respuesta(sql, ctx, rastro["vistas"]), "")

    monkeypatch.setattr(men, "correr", fake)
    return rastro


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Entorno válido mínimo (todo por env: el módulo no lee ningún `.env`)."""
    for k, v in (("MAINT_DB_URL", URL),
                 ("ENVIRONMENT", "production"),
                 ("GMAIL_SMTP_USER", GMAIL_USER),
                 ("GMAIL_SMTP_APP_PASSWORD", APP_FAKE),
                 ("ALERT_EMAIL", "alertas@example.com"),
                 ("DRY_RUN", "1")):
        monkeypatch.setenv(k, v)
    for k in ("MAX_CAMBIOS", "DIAS_PENDIENTE", "NEON_LIMITE_MB", "NEON_UMBRAL_PCT"):
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def mails(monkeypatch):
    """Captura los reportes en vez de mandarlos por Gmail SMTP."""
    capturados = []
    monkeypatch.setattr(men, "enviar_email",
                        lambda asunto, html: capturados.append((asunto, html)) or True)
    return capturados


def _texto(mail) -> str:
    return mail[0] + "\n" + mail[1]


# ── Config: nada se toca si la config no está completa y correcta ─────────────
def test_a_sin_maint_db_url_exit_2_sin_tocar_la_base(monkeypatch, mails):
    monkeypatch.delenv("MAINT_DB_URL", raising=False)
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_CONFIG
    assert rastro["sql"] == [] and rastro["scripts"] == []
    assert len(mails) == 1                      # avisa igual: un job que no corre no es silencioso
    assert "faltan variables de entorno: MAINT_DB_URL" in mails[0][0]


@pytest.mark.parametrize("url,motivo", [
    (URL.replace("ep-prod-1234", "ep-prod-1234-pooler"), "'-pooler'"),
    (URL.replace("maint_rw", "backup_ro"), "el usuario no es maint_rw"),
    (URL.replace("maint_rw", "neondb_owner"), "el usuario no es maint_rw"),
    (URL.replace("postgresql://", "mysql://"), "no empieza con postgresql://"),
])
def test_b_url_invalida_exit_2(url, motivo, monkeypatch, mails):
    monkeypatch.setenv("MAINT_DB_URL", url)
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_CONFIG
    assert rastro["sql"] == []
    assert motivo in _texto(mails[0])
    assert CLAVE_FALSA not in _texto(mails[0])   # el motivo describe la regla, no el valor


def test_c_environment_no_production_exit_2(monkeypatch, mails):
    """Guarda dura: el job escribe en PROD, así que sólo corre con ENVIRONMENT=production."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_CONFIG
    assert rastro["sql"] == [] and rastro["scripts"] == []
    assert "ENVIRONMENT='test'" in mails[0][0]


@pytest.mark.parametrize("valor", ["20; DROP TABLE usuarios--", "0", "1001", "abc", "2.5"])
def test_d_max_cambios_invalido_exit_2_nunca_llega_al_sql(valor, monkeypatch, mails):
    monkeypatch.setenv("MAX_CAMBIOS", valor)
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_CONFIG
    assert rastro["scripts"] == []               # no se escribió ni se corrió ningún script
    assert "MAX_CAMBIOS" in mails[0][0]


# ── La transacción: ROLLBACK en DRY-RUN, COMMIT + guarda en REAL ──────────────
def test_e_dry_run_usa_rollback_sin_guarda_y_borra_el_temporal(monkeypatch, mails):
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_OK
    script = rastro["scripts"][0]
    assert script.rstrip().endswith("ROLLBACK;")
    assert "COMMIT;" not in script
    assert men.MARCA_GUARDA not in script        # en DRY-RUN la guarda la decide Python
    assert "SET LOCAL TIME ZONE 'America/Santiago'" in script
    assert "activo = false" in script            # el par del CHECK de la 034 va junto
    temporal = Path(tempfile.gettempdir()) / f"maint_cambios_{os.getpid()}.sql"
    assert not temporal.exists()                 # el script temporal se borra siempre
    assert mails[0][0].startswith("[Mantenimiento PROD] OK (DRY-RUN: 0 cambio(s))")


def test_f_real_usa_commit_con_la_guarda_de_volumen(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("MAX_CAMBIOS", "5")
    rastro = _psql_falso(monkeypatch, _ctx(despues="vacio"))

    assert men.main() == men.EXIT_OK
    script = rastro["scripts"][0]
    assert script.rstrip().endswith("COMMIT;")
    assert "ROLLBACK;" not in script
    assert men.MARCA_GUARDA in script and "MAX_CAMBIOS=5" in script and "n > 5" in script
    assert "APLICADO (0 cambio(s))" in mails[0][0]


# ── Guarda de volumen ────────────────────────────────────────────────────────
def test_g_dry_run_excede_max_cambios_informa_con_la_lista_completa(monkeypatch, mails):
    """En DRY-RUN la guarda NO aborta: run rojo (exit 6) con la lista COMPLETA en el mail."""
    filas = _n_filas(25)
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=25)))

    assert men.main() == men.EXIT_GUARDA
    assert rastro["scripts"][0].rstrip().endswith("ROLLBACK;")
    asunto, html = mails[0]
    assert "EXCEDE MAX_CAMBIOS (25 > 20): no se aplicaría" in asunto
    assert html.count("<tr>") == 25               # las 25 filas, sin truncar
    assert "Alumno 24" in html and "Alumno 0" in html


def test_h_real_la_guarda_aborta_la_transaccion_exit_6(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    filas = _n_filas(30)
    error = ("psql:/tmp/maint_cambios_1.sql:52: ERROR:  GUARDA DE VOLUMEN: 30 cambios > "
             "MAX_CAMBIOS=20 (no se aplica nada)\n"
             "CONTEXT:  PL/pgSQL function inline_code_block line 8 at RAISE\n")
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_rc=3, script_err=error))

    assert men.main() == men.EXIT_GUARDA
    assert rastro["scripts"][0].rstrip().endswith("COMMIT;")   # el script pedía COMMIT…
    assert rastro["vistas"]["vencidos"] == 1                   # …y NO se llegó a verificar
    assert "guarda de volumen: 30 > MAX_CAMBIOS=20" in mails[0][0]
    assert "GUARDA DE VOLUMEN" in mails[0][1]


# ── Fallas de escritura y de verificación ────────────────────────────────────
def test_i_escritura_falla_exit_7_y_nada_se_cuenta_como_ok(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    error = ("ERROR:  permission denied for table usuarios\n"
             f"psql: error: connection to server failed: {URL}\n")
    rastro = _psql_falso(monkeypatch, _ctx(script_rc=1, script_err=error))

    assert men.main() == men.EXIT_ESCRITURA
    assert "escritura rc=1" in mails[0][0]
    assert "permission denied" in mails[0][1]
    assert rastro["vistas"]["vencidos"] == 1       # sin verificación: no se aplicó nada


def test_j_verificacion_no_cuadra_exit_8(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    filas = _n_filas(2)
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=2)))

    assert men.main() == men.EXIT_VERIFICACION
    assert rastro["vistas"]["vencidos"] == 2       # lectura previa + verificación
    assert "la base no quedó como debía" in mails[0][0]
    assert "esperado 0" in mails[0][1]


# ── Integridad: run rojo, pero NO aborta el mantenimiento ────────────────────
def test_k_integridad_pone_el_run_rojo_sin_abortar_la_escritura(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    rastro = _psql_falso(monkeypatch, _ctx(dup_rut=[["12345678-9", "2"]],
                                           sin_plan="1", despues="vacio"))

    assert men.main() == men.EXIT_INTEGRIDAD
    assert rastro["scripts"][0].rstrip().endswith("COMMIT;")   # la escritura SÍ corrió
    assert "integridad: 2 problema(s)" in mails[0][0]
    assert "RUT duplicados (1): 12345678-9 x2" in mails[0][1]
    assert "Suscripciones con plan inexistente: 1" in mails[0][1]


# ── Seguridad: ni el log ni el mail pueden filtrar la password ───────────────
def test_l_salida_saneada(monkeypatch, mails, capsys):
    monkeypatch.setenv("DRY_RUN", "0")
    _psql_falso(monkeypatch, _ctx(script_rc=1, script_err=f"psql: error: could not connect: {URL}"))

    assert men.main() == men.EXIT_ESCRITURA
    cap = capsys.readouterr()
    salida = cap.out + cap.err
    assert "://***@" in salida                       # la URI sale saneada
    assert CLAVE_FALSA not in salida                 # y la password nunca aparece
    assert CLAVE_FALSA not in _texto(mails[0])


def test_m_nombres_de_la_base_van_escapados_en_el_html(monkeypatch, mails):
    filas = [["7", "<script>alert(1)</script>", "Plan <b>X</b>", "2026-09-01", "activo"]]
    _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=1)))

    assert men.main() == men.EXIT_OK
    html = mails[0][1]
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ── Camino feliz ─────────────────────────────────────────────────────────────
def test_n_dry_run_ok_incluye_reporte_y_alerta_de_neon(monkeypatch, mails):
    filas = _n_filas(2)
    _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=2),
                                  tamano_mb=430))

    assert men.main() == men.EXIT_OK
    asunto, html = mails[0]
    assert asunto.startswith("[Mantenimiento PROD] OK (DRY-RUN: 2 cambio(s))")
    assert "430.0 MB de 512 MB" in html and "ALERTA" in html      # 430 MB > 80 % de 512 MB
    assert "planes_vencidos_mes" in html and "ingresos_mes" in html
    assert "Sin problemas ✅" in html


def test_o_real_ok_aplica_y_verifica_en_cero(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    filas = _n_filas(2)
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=2),
                                           despues="vacio"))

    assert men.main() == men.EXIT_OK
    assert "APLICADO (2 cambio(s))" in mails[0][0]
    assert rastro["vistas"]["vencidos"] == 2        # lectura previa + verificación
    assert "esperado 0" in mails[0][1]


# ── Parseo de la salida de psql (los tags de comando NO son resultados) ──────
def test_p_psql_leer_ignora_los_tags_de_comando(monkeypatch):
    """`-tA` NO saca los tags: `SET` (de la zona horaria) llega antes del valor."""
    monkeypatch.setattr(men, "correr", lambda cmd: subprocess.CompletedProcess(
        cmd, 0, "SET\n149\n", ""))

    assert men.psql_leer(URL, "SELECT count(*)::text FROM usuarios") == [["149"]]
    assert men.psql_escalar(URL, "SELECT count(*)::text FROM usuarios") == "149"
    assert men.psql_entero(URL, "SELECT count(*)::text FROM usuarios") == 149


def test_q_parsear_resumen_ignora_los_tags(monkeypatch):
    salida = "BEGIN\nSET\nCREATE TABLE\nINSERT 0 3\nDO\nvencidos|3\nbasura sin pipe\n\nROLLBACK\n"

    assert men.parsear_resumen(salida) == {"vencidos": 3}
    assert men.parsear_resumen("") == {}
