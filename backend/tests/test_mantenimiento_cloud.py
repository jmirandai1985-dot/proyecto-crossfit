"""Tests del mantenimiento PROD 2× al mes: casos OK y de falla con psql/SMTP mockeados.

Sin Neon, sin red, sin credenciales y sin mandar ningún correo. Verifican lo que importa del
job: que sin `MAINT_DB_URL` no se toque la base, que se rechacen el pooler y cualquier rol
que no sea `maint_rw`, que `ENVIRONMENT` tenga que ser `production`, que un `MAX_CAMBIOS`
inválido no pueda llegar al SQL, que la transacción termine en `ROLLBACK` en DRY-RUN y en
`COMMIT` (con la guarda de volumen adentro) en REAL, que la guarda no aborte en DRY-RUN pero
sí informe con la lista COMPLETA, que un fallo de escritura no se cuente como éxito, que la
verificación posterior sea obligatoria, que la integridad ponga el run rojo **sin** abortar
la escritura, y que ni el log ni el mail puedan filtrar la password del rol.

Y la regla del correo (**correo = algo que revisar**): un run verde —incluido "APLICADO n
cambios" y verificado en 0— NO manda nada (sólo log), mientras que cualquier falla (config,
lectura, escritura, verificación, guarda de volumen, integridad) o el free tier de Neon
pasado del umbral SÍ mandan alerta, con el asunto arrancando en `[ALERTA] Mantenimiento PROD:`.

Se corre con:
    py -3.12 -m pytest tests/test_mantenimiento_cloud.py -q --noconftest
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import re  # noqa: E402
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


def script_out_cierre(cierre: int = 0, aforo: int = 0) -> str:
    """Salida de la transacción de consistencia (pasos 8-9): tags + resumen `paso|n`."""
    return ("BEGIN\nSET\nCREATE TABLE\nINSERT 0 1\nINSERT 0 0\nDO\n"
            f"cierre_asistencia|{cierre}\naforo_resync|{aforo}\nROLLBACK\n")


def script_out_purga(tokens: int = 0, notif: int = 0) -> str:
    """Salida de la transacción de purga (paso 10)."""
    return ("BEGIN\nSET\nCREATE TABLE\nINSERT 0 0\nINSERT 0 0\nDO\n"
            f"tokens_reset|{tokens}\nnotificaciones|{notif}\nROLLBACK\n")


def _ctx(**kw) -> dict:
    """Estado de la base simulada. `despues='vacio'` simula que en REAL se aplicó de verdad.

    Las claves de la Fase 7 salen todas vacías/0: una corrida sana (nada que cerrar, nada que
    purgar, ninguna detección, MRR/churn con base de sobra) es el punto de partida de los tests
    viejos, que así siguen probando lo mismo que probaban.
    """
    ctx = {"vencidos": [], "susc_pendientes": [], "solicitudes": [], "usuarios_pendientes": [],
           "dup_rut": [], "dup_correo": [], "sin_usuario": "0", "sin_plan": "0",
           "fechas_malas": "0", "tamano_mb": 100, "script_out": script_out(),
           "script_out_cierre": script_out_cierre(), "script_out_purga": script_out_purga(),
           "script_rc": 0, "script_err": "", "despues": "igual",
           # ── Fase 7: detecciones (A), consistencia (C) y reporte (E) ──
           "a1a": "0", "a1b": [], "a1c": "0", "a2a": [], "a2b": [], "a2c": [],
           "a3_creditos": [], "a4a": "0", "a4b": [], "a5a": [], "a5b": [], "a5c": [],
           "cierre_pendientes": [], "aforo_resync": [], "tokens_reset": [], "notificaciones": [],
           "mrr": "60000", "mrr_ant": "50000", "vigentes": "60", "bajas": "2",
           "ret_base": "40", "ret_siguen": "36",
           "cierre_rc": 0, "cierre_err": "", "purga_rc": 0, "purga_err": ""}
    ctx.update(kw)
    return ctx


def _respuesta(sql: str, ctx: dict, vistas: dict) -> str:
    """Respuesta de cada SELECT. Si aparece una consulta no contemplada, el test falla: así
    una consulta nueva nunca se cuela sin comportamiento definido.

    El orden de los `if` ES significativo: los marcadores de la Fase 7 van primero porque son
    más específicos (varias detecciones comparten fragmentos con las listas de otras fases).
    """
    # ── A.3: se compara en Python, así que devuelve las columnas crudas ──
    if "s.creditos_totales - s.creditos_disponibles" in sql:
        return _filas(*ctx["a3_creditos"])

    # ── Detecciones escalares (A.1a, A.1c demo, A.4a) ──
    if "activo <> (estado = 'activo')" in sql:
        return ctx["a1a"] + "\n"
    if "ESCAPE" in sql:                       # A.1(c): allowlist PROD_PERMITIDOS
        return ctx["a1c"] + "\n"
    if "r.asistencia_marcada_at IS NULL AND EXISTS" in sql:
        return ctx["a4a"] + "\n"

    # ── Reporte E (MRR, retención/churn, bajas): cada consulta lleva su alias ──
    for alias, clave in (("AS mrr_hoy", "mrr"), ("AS mrr_mes_anterior", "mrr_ant"),
                         ("AS alumnos_vigentes", "vigentes"), ("AS bajas_mes", "bajas"),
                         ("AS retencion_base", "ret_base"),
                         ("AS retencion_siguen", "ret_siguen")):
        if alias in sql:
            return ctx[clave] + "\n"

    # ── Listas nuevas (detecciones A y fases 8-10): la 2ª lectura es la verificación ──
    for marcador, clave in (
            ("c.fecha DESC, c.id LIMIT 25", "a2a"),
            ("AS reservas_vivas", "aforo_resync"),
            ("GROUP BY alumno_id, clase_id", "a2b"),
            ("asistentes_confirmados > cupo_maximo", "a2c"),
            ("WHERE estado NOT IN (", "a1b"),
            ("asistio = true AND asistencia_marcada_at IS NULL", "a4b"),
            ("AND NOT EXISTS (SELECT 1 FROM coach_disciplinas", "a5a"),
            ("AND EXISTS (SELECT 1 FROM coach_disciplinas", "a5b"),
            ("FROM clases c JOIN usuarios u ON u.id = c.coach_id", "a5c"),
            ("JOIN clases c ON c.id = r.clase_id", "cierre_pendientes"),
            ("FROM password_reset_tokens", "tokens_reset"),
            ("FROM notificaciones_enviadas", "notificaciones"),
            ("s.fecha_expiracion < current_date", "vencidos"),
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
    """Mockea TODO lo que sale del proceso: `psql` (las 3 transacciones y las lecturas).

    La transacción se reconoce por el nombre de su tabla temporal (`_maint_cambios`,
    `_maint_cierre`, `_maint_purga`), así que cada fase puede tener su propio resumen y su
    propio error sin tocar las otras.
    """
    rastro = {"scripts": [], "sql": [], "vistas": {}}
    fases = {"_maint_cambios": ("script_out", "script_rc", "script_err"),
             "_maint_cierre": ("script_out_cierre", "cierre_rc", "cierre_err"),
             "_maint_purga": ("script_out_purga", "purga_rc", "purga_err")}

    def fake(cmd):
        assert cmd[0] == "psql", f"solo debería correr psql: {cmd[0]}"
        if "-f" in cmd:                                   # una transacción de escritura
            script = Path(cmd[cmd.index("-f") + 1]).read_text(encoding="utf-8")
            rastro["scripts"].append(script)
            k_out, k_rc, k_err = next(v for k, v in fases.items() if k in script)
            rc, err = ctx[k_rc], ctx[k_err]
            return subprocess.CompletedProcess(cmd, rc, "" if rc else ctx[k_out], err)
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
    for k in ("MAX_CAMBIOS", "DIAS_PENDIENTE", "NEON_LIMITE_MB", "NEON_UMBRAL_PCT",
              # Fase 7: topes, retenciones, allowlist y los límites de Neon (env group
              # `neon-api`). Se borran TODOS para que ningún test dependa de la máquina.
              "MAX_CIERRE", "MAX_PURGA", "DIAS_CIERRE_RESERVAS", "DIAS_PURGA_TOKENS",
              "DIAS_PURGA_NOTIF", "CREDITOS_DESCUADRE_TOLERANCIA", "PROD_PERMITIDOS",
              "TENANT_ID", "MIN_BASE_RETENCION", "NEON_CU_HORAS_LIMITE", "NEON_CU_UMBRAL_PCT",
              "NEON_RAMAS_LIMITE", "NEON_API_BASE", "NEON_API_KEY", "NEON_PROJECT_ID"):
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
    assert mails[0][0].startswith("[ALERTA] Mantenimiento PROD: configuración inválida")
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
    assert mails[0][0].startswith("[ALERTA] Mantenimiento PROD: configuración inválida")
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
def test_e_dry_run_usa_rollback_sin_guarda_y_no_manda_correo(monkeypatch, mails, capsys):
    """DRY-RUN sin cambios y sin problemas: ROLLBACK y **sólo log** (regla: correo = algo que
    revisar)."""
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
    assert mails == []                           # ni un correo
    assert "MAIL: no se envía" in capsys.readouterr().out


def test_f_real_usa_commit_con_la_guarda_de_volumen(monkeypatch, mails, capsys):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("MAX_CAMBIOS", "5")
    rastro = _psql_falso(monkeypatch, _ctx(despues="vacio"))

    assert men.main() == men.EXIT_OK
    script = rastro["scripts"][0]
    assert script.rstrip().endswith("COMMIT;")
    assert "ROLLBACK;" not in script
    assert men.MARCA_GUARDA in script and "MAX_CAMBIOS=5" in script and "n > 5" in script
    assert mails == []                           # 0 cambios aplicados y verificados: sin correo
    assert "Transacción aplicada y verificada" in capsys.readouterr().out


# ── Guarda de volumen ────────────────────────────────────────────────────────
def test_g_dry_run_excede_max_cambios_informa_con_la_lista_completa(monkeypatch, mails):
    """En DRY-RUN la guarda NO aborta: run rojo (exit 6) con la lista COMPLETA en la alerta.

    Se pasa de los 40 cambios por defecto: en 15 días 15-25 vencimientos son normales, 41 no.
    """
    filas = _n_filas(41)
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=41)))

    assert men.main() == men.EXIT_GUARDA
    assert rastro["scripts"][0].rstrip().endswith("ROLLBACK;")
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: excede MAX_CAMBIOS (41 > 40)")
    assert html.count("<tr>") == 41               # las 41 filas, sin truncar
    assert "Alumno 40" in html and "Alumno 0" in html


def test_h_real_la_guarda_aborta_la_transaccion_exit_6(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    filas = _n_filas(41)
    error = ("psql:/tmp/maint_cambios_1.sql:52: ERROR:  GUARDA DE VOLUMEN: 41 cambios > "
             "MAX_CAMBIOS=40 (no se aplica nada)\n"
             "CONTEXT:  PL/pgSQL function inline_code_block line 8 at RAISE\n")
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_rc=3, script_err=error))

    assert men.main() == men.EXIT_GUARDA
    assert rastro["scripts"][0].rstrip().endswith("COMMIT;")   # el script pedía COMMIT…
    assert rastro["vistas"]["vencidos"] == 1                   # …y NO se llegó a verificar
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: excede MAX_CAMBIOS (41 > 40)")
    assert "NO se aplicó nada" in asunto
    assert "GUARDA DE VOLUMEN" in html


# ── Fallas de escritura y de verificación ────────────────────────────────────
def test_i_escritura_falla_exit_7_y_nada_se_cuenta_como_ok(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    error = ("ERROR:  permission denied for table usuarios\n"
             f"psql: error: connection to server failed: {URL}\n")
    rastro = _psql_falso(monkeypatch, _ctx(script_rc=1, script_err=error))

    assert men.main() == men.EXIT_ESCRITURA
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: falló la transacción de escritura")
    assert "escritura rc=1" in asunto
    assert "permission denied" in html
    assert rastro["vistas"]["vencidos"] == 1       # sin verificación: no se aplicó nada


def test_j_verificacion_no_cuadra_exit_8(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    filas = _n_filas(2)
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=2)))

    assert men.main() == men.EXIT_VERIFICACION
    assert rastro["vistas"]["vencidos"] == 2       # lectura previa + verificación
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: la verificación posterior no cuadró")
    assert "la base no quedó como debía" in asunto
    assert "esperado 0" in html


# ── Integridad: run rojo, pero NO aborta el mantenimiento ────────────────────
def test_k_integridad_pone_el_run_rojo_sin_abortar_la_escritura(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    rastro = _psql_falso(monkeypatch, _ctx(dup_rut=[["12345678-9", "2"]],
                                           sin_plan="1", despues="vacio"))

    assert men.main() == men.EXIT_INTEGRIDAD
    assert rastro["scripts"][0].rstrip().endswith("COMMIT;")   # la escritura SÍ corrió
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: integridad con 2 problema(s)")
    assert "RUT duplicados (1): 12345678-9 x2" in html
    assert "Suscripciones con plan inexistente: 1" in html


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
    # Con un hallazgo de integridad el run es rojo (exit 4) y por eso SÍ hay alerta: es donde
    # viaja la lista de filas, así que acá se comprueba el escapado.
    _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=1),
                                  dup_rut=[["12345678-9", "2"]]))

    assert men.main() == men.EXIT_INTEGRIDAD
    html = mails[0][1]
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ── Camino feliz ─────────────────────────────────────────────────────────────
def test_n_dry_run_ok_con_neon_alto_manda_la_alerta_de_espacio(monkeypatch, mails):
    """El único caso VERDE que avisa: Neon pasado del umbral (hay algo que revisar)."""
    filas = _n_filas(2)
    _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=2),
                                  tamano_mb=430))

    assert men.main() == men.EXIT_OK
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: Neon al 83.98% del free tier")
    assert "430.0 MB de 512 MB" in html and "ALERTA" in html      # 430 MB > 80 % de 512 MB
    assert "planes_vencidos_mes" in html and "ingresos_mes" in html
    assert "Sin problemas ✅" in html


def test_o_real_ok_aplica_y_verifica_en_cero_sin_correo(monkeypatch, mails, capsys):
    """Aplica los 4 UPDATE y la verificación da 0: run verde y **sin correo** (sólo log)."""
    monkeypatch.setenv("DRY_RUN", "0")
    filas = _n_filas(2)
    rastro = _psql_falso(monkeypatch, _ctx(vencidos=filas, script_out=script_out(vencidos=2),
                                           despues="vacio"))

    assert men.main() == men.EXIT_OK
    assert rastro["vistas"]["vencidos"] == 2        # lectura previa + verificación
    assert mails == []
    salida = capsys.readouterr().out
    assert "Transacción aplicada y verificada: 2 cambio(s)" in salida
    assert "MAIL: no se envía" in salida


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


# ── La regla del correo: "correo = algo que revisar" ─────────────────────────
@pytest.mark.parametrize("code,neon_alto,esperado", [
    (men.EXIT_OK, False, False),         # todo verde ⇒ sólo log (incluso "APLICADO n cambios")
    (men.EXIT_OK, True, True),           # verde pero Neon pasado del umbral ⇒ alerta
    (men.EXIT_CONFIG, False, True),
    (men.EXIT_LECTURA, False, True),
    (men.EXIT_INTEGRIDAD, False, True),
    (men.EXIT_GUARDA, False, True),
    (men.EXIT_ESCRITURA, False, True),
    (men.EXIT_VERIFICACION, False, True),
])
def test_r_hay_que_avisar(code, neon_alto, esperado):
    """`hay_que_avisar()`: exit ≠ 0 (cualquier falla) o el free tier de Neon pasado. Nada más."""
    datos = {"neon": {"alerta": neon_alto, "pct": 81.0, "mb": 415.0, "limite_mb": 512}}

    assert men.hay_que_avisar(code, datos) is esperado


def test_s_el_asunto_va_en_una_linea_y_recortado():
    """El motivo entra en el asunto del correo: una sola línea y sin pasarse de largo."""
    assert men._motivo_corto("a\n\nb   c") == "a b c"
    corto = men._motivo_corto("x" * 500)
    assert len(corto) == 140 and corto.endswith("…")
    assert men._motivo_corto("") == ""


# ══ Fase 7: detecciones A, límites de Neon B, consistencia C y reporte E ══════════════
# Config nueva (mismos criterios que MAX_CAMBIOS: se valida ANTES de tocar la base) ────
@pytest.mark.parametrize("var,valor", [("MAX_CIERRE", "0"), ("MAX_PURGA", "abc"),
                                       ("TENANT_ID", "0"), ("NEON_CU_HORAS_LIMITE", "-5"),
                                       ("CREDITOS_DESCUADRE_TOLERANCIA", "1; DROP TABLE x")])
def test_t_topes_nuevos_invalidos_exit_2(var, valor, monkeypatch, mails):
    """Un tope/umbral nuevo inválido corta ANTES de leer y de escribir (exit 2)."""
    monkeypatch.setenv(var, valor)
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_CONFIG
    assert rastro["sql"] == [] and rastro["scripts"] == []
    assert var in mails[0][0]


@pytest.mark.parametrize("patron", ["demo'; DROP TABLE usuarios--", "demo\\prod", "a", "demo prod"])
def test_u_prod_permitidos_invalido_exit_2(patron, monkeypatch, mails):
    """`PROD_PERMITIDOS` es el ÚNICO texto de env var que llega al SQL: si no es un patrón del
    charset seguro, no se corre nada (y menos se arma una consulta con eso)."""
    monkeypatch.setenv("PROD_PERMITIDOS", patron)
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_CONFIG
    assert rastro["sql"] == [] and rastro["scripts"] == []
    assert "PROD_PERMITIDOS" in mails[0][0]


def test_v_neon_api_base_tiene_que_ser_https(monkeypatch, mails):
    monkeypatch.setenv("NEON_API_BASE", "http://console.neon.tech/api/v2")
    rastro = _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_CONFIG
    assert rastro["scripts"] == []
    assert "NEON_API_BASE" in mails[0][0]


def test_v2_el_patron_like_escapa_el_underscore_y_no_puede_inyectar():
    """`_` es comodín de UN carácter en LIKE: se escapa para que sea literal. El `%` queda como
    comodín a propósito (es lo que hace útil al allowlist)."""
    assert men.patron_like("demo_prod.%@example.com") == "demo\\_prod.%@example.com"
    assert "ESCAPE" in men.sql_demo(("demo.prod.%@example.com",))
    assert men.sql_demo(()) == "false"


def test_v3_a1b_usa_la_lista_de_estados_conocidos_del_modulo():
    """La lista de estados vive en `ESTADOS_USUARIO`: la consulta se arma con ella, así que
    agregar un estado nuevo (o quitarlo) no puede dejar el SQL desactualizado."""
    cfg = {"permitidos": ("demo.prod.%@example.com",), "dias_cierre": 7, "tenant_id": 1}
    chequeo = next(c for c in men.detecciones_sql(cfg) if c["clave"] == "a1b_estados_desconocidos")

    for estado in men.ESTADOS_USUARIO:
        assert f"'{estado}'" in chequeo["sql"]
    assert "NOT IN" in chequeo["sql"]


# ── Las TRES transacciones ────────────────────────────────────────────────────
def test_w_las_tres_transacciones_llevan_su_guarda_y_escriben_solo_lo_suyo(monkeypatch, mails):
    """Orden y alcance: cambios → consistencia → purga, cada una con su tope y su COMMIT."""
    monkeypatch.setenv("DRY_RUN", "0")
    rastro = _psql_falso(monkeypatch, _ctx(despues="vacio", aforo_resync=_n_filas(1)))

    assert men.main() == men.EXIT_OK
    a, b, c = rastro["scripts"]
    assert a.rstrip().endswith("COMMIT;") and "MAX_CAMBIOS=40" in a
    assert "UPDATE suscripciones" in a and "FROM reservas" not in a
    assert b.rstrip().endswith("COMMIT;") and "MAX_CIERRE=500" in b
    assert "UPDATE reservas" in b and "UPDATE clases" in b and "DELETE" not in b
    assert c.rstrip().endswith("COMMIT;") and "MAX_PURGA=5000" in c
    assert c.count("DELETE FROM") == 2 and "UPDATE" not in c
    assert mails == []                     # verde y con los 3 resúmenes en 0: sólo log


def test_x_dry_run_cierra_asistencia_sin_tocar_el_estado(monkeypatch, mails):
    """D-6 (opción A): el cierre escribe `asistencia_marcada_at` + `asistencia_via='cierre'` y
    NO cambia `estado` — un `no_asistio` reescribiría los KPIs de asistencia ya publicados."""
    rastro = _psql_falso(monkeypatch, _ctx(cierre_pendientes=_n_filas(3)))

    assert men.main() == men.EXIT_OK
    script = rastro["scripts"][1]
    assert "asistencia_marcada_at = now()" in script
    assert "asistencia_via = 'cierre'" in script
    assert "no_asistio" not in script and "SET estado" not in script
    assert "cierre_asistencia" in script and "aforo_resync" in script
    assert script.rstrip().endswith("ROLLBACK;")        # DRY-RUN: no se aplicó nada
    assert mails == []


def test_y_max_cierre_excedido_en_dry_run_informa_con_la_lista_completa(monkeypatch, mails):
    """La guarda del paso 8-9 no aborta en DRY-RUN: informa (con la lista completa) y es rojo."""
    _psql_falso(monkeypatch, _ctx(cierre_pendientes=_n_filas(2),
                                  script_out_cierre=script_out_cierre(cierre=501)))

    assert men.main() == men.EXIT_GUARDA
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: excede MAX_CIERRE (501 > 500)")
    assert html.count("<tr>") == 2                       # las 2 filas de la lista, completas
    assert "cierre_asistencia" in html


def test_z_max_purga_excedido_en_dry_run_informa_exit_6(monkeypatch, mails):
    _psql_falso(monkeypatch, _ctx(tokens_reset=_n_filas(2),
                                  script_out_purga=script_out_purga(tokens=9000)))

    assert men.main() == men.EXIT_GUARDA
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: excede MAX_PURGA (9000 > 5000)")
    assert "tokens_reset" in html


def test_ap_la_guarda_del_cierre_aborta_en_real_exit_6(monkeypatch, mails):
    """En REAL la guarda aborta DENTRO del SQL: la clásica ya quedó aplicada y la purga NO corre."""
    monkeypatch.setenv("DRY_RUN", "0")
    error = "ERROR:  GUARDA DE VOLUMEN: 501 cierres > MAX_CIERRE=500 (no se aplica nada)\n"
    rastro = _psql_falso(monkeypatch, _ctx(despues="vacio", cierre_rc=3, cierre_err=error,
                                           cierre_pendientes=_n_filas(501)))

    assert men.main() == men.EXIT_GUARDA
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: excede MAX_CIERRE (501 > 500)")
    assert "NO se aplicó nada" in asunto and "GUARDA DE VOLUMEN" in html
    assert len(rastro["scripts"]) == 2                   # clásica + cierre; la purga NO corrió


def test_aq_la_guarda_de_la_purga_aborta_en_real_exit_6(monkeypatch, mails):
    monkeypatch.setenv("DRY_RUN", "0")
    error = "ERROR:  GUARDA DE VOLUMEN: 9000 filas purgadas > MAX_PURGA=5000\n"
    rastro = _psql_falso(monkeypatch, _ctx(despues="vacio", purga_rc=3, purga_err=error,
                                           tokens_reset=_n_filas(3)))

    assert men.main() == men.EXIT_GUARDA
    assert mails[0][0].startswith("[ALERTA] Mantenimiento PROD: excede MAX_PURGA")
    assert "MAX_PURGA" in mails[0][1]
    assert len(rastro["scripts"]) == 3                   # las 3 corrieron; la última abortó


def test_ao_verificacion_del_cierre_no_cuadra_exit_8(monkeypatch, mails):
    """Si en REAL el paso 8 no dejó su lista en 0, el run es rojo por verificación (exit 8)."""
    monkeypatch.setenv("DRY_RUN", "0")
    rastro = _psql_falso(monkeypatch, _ctx(cierre_pendientes=_n_filas(2)))

    assert men.main() == men.EXIT_VERIFICACION
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: la verificación posterior no cuadró")
    assert "la base no quedó como debía" in asunto
    assert "cierre_asistencia" in html
    assert len(rastro["scripts"]) == 2                   # se cortó en la fase del cierre


# ── Detecciones A.1–A.5 (sólo lectura) ────────────────────────────────────────
def test_aa_detecciones_rojas_exit_9_con_la_lista_completa_en_el_mail(monkeypatch, mails):
    """Un hallazgo rojo pone el run rojo (exit 9) SIN abortar la escritura, y la lista va
    completa. Exactamente el mismo contrato que la integridad (exit 4)."""
    filas = [["7", "alumno@example.com", "activo_x", "true"]]
    rastro = _psql_falso(monkeypatch, _ctx(a1b=filas, a2b=[["5", "97", "2"]]))

    assert men.main() == men.EXIT_DIAGNOSTICO
    asunto, html = mails[0]
    assert asunto.startswith(
        "[ALERTA] Mantenimiento PROD: los chequeos nuevos encontraron 2 problema(s)")
    assert "A.1(b) usuarios con un `estado` desconocido" in html
    assert "activo_x" in html and "alumno@example.com" in html
    assert "A.2(b) reservas vivas duplicadas" in html
    assert "🔴 rojo (exit 9)" in html
    assert len(rastro["scripts"]) == 3                   # las 3 transacciones corrieron igual


def test_ab_a4a_es_informativo_y_no_pone_el_run_rojo(monkeypatch, mails):
    """A.4(a) (reservas de clases pasadas sin marcar) es el INSUMO del paso 8: es normal que
    exista y el propio run lo cierra. Informativo: no cambia el exit code."""
    _psql_falso(monkeypatch, _ctx(a4a="12", cierre_pendientes=_n_filas(12)))

    assert men.main() == men.EXIT_OK
    assert mails == []


def test_ac_a5_sin_coach_posible_rojo_y_asignable_solo_informativo(monkeypatch, mails):
    """D-2: rojo sólo si la clase NO tiene coach Y su disciplina no tiene ningún coach activo;
    si hay coach disponible es un pendiente de asignación (informativo)."""
    _psql_falso(monkeypatch, _ctx(a5a=[["30", "2026-10-02", "19:00:00", "CrossFit"]],
                                  a5b=[["31", "2026-10-02", "20:00:00", "CrossFit"]],
                                  a4a="3"))

    assert men.main() == men.EXIT_DIAGNOSTICO
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: los chequeos nuevos encontraron 1")
    assert "A.5(a)" in html and "A.5(b)" in html
    assert "🔴 rojo (exit 9)" in html and "ℹ️ sólo informativo" in html
    assert "A.4(a)" in html                              # el informe también viaja al mail


def test_ad_a1c_demo_es_informativo_no_rojo(monkeypatch):
    """D-3: los usuarios `demo.prod.*` son intencionales (seed_ml_data_prod.py). Se cuentan en
    el mail, no son un hallazgo."""
    _psql_falso(monkeypatch, _ctx(a1c="104"))

    salida = men.detecciones(URL, men.leer_config())

    assert salida["hallazgos"] == []
    assert any("104" in i and "PROD_PERMITIDOS" in i for i in salida["informes"])


# ── A.3: descuadre de créditos (la regla que cambió con D-8) ──────────────────
def test_ae_a3_descuadre_mas_grande_que_la_tolerancia_es_rojo(monkeypatch, mails):
    """La tolerancia es SIMÉTRICA y tapa |descuadre| <= tolerancia; más allá es rojo. El
    descuadre negativo (se devolvieron más créditos de los que correspondía) puede venir de que
    el staff editó una reserva cancelada y `updated_at` se corrió: por eso se lo cubre igual
    que al positivo, en vez de tratarlo como imposible."""
    monkeypatch.setenv("CREDITOS_DESCUADRE_TOLERANCIA", "3")
    fila = [["9", "a@example.com", "20", "19", "1", "5", "0"]]   # gastó 1, esperado 5 ⇒ −4
    _psql_falso(monkeypatch, _ctx(a3_creditos=fila))

    assert men.main() == men.EXIT_DIAGNOSTICO
    html = mails[0][1]
    assert "A.3 suscripción 9 (a@example.com) gastó MENOS (devolución de más)" in html
    assert "A.3 descuadre de créditos por suscripción vigente" in html
    assert "1 de 20 (esperados 5" in html


def test_af_a3_cancelaciones_tardias_no_dan_falso_positivo(monkeypatch, mails):
    """La regla nueva (D-8): el consumo esperado SUMA las cancelaciones tardías (las que se
    hicieron con menos de 6 h no devolvieron el crédito). Sin esa suma, cada cancelación en
    plazo aparecería como descuadre: era el falso positivo a evitar."""
    # 4 reservas vivas + 2 cancelaciones tardías = 6 gastados ⇒ cuadra exacto
    fila = [["9", "a@example.com", "20", "14", "6", "4", "2"]]
    _psql_falso(monkeypatch, _ctx(a3_creditos=fila))

    assert men.main() == men.EXIT_OK
    assert mails == []


@pytest.mark.parametrize("tolerancia,esperado", [("0", men.EXIT_DIAGNOSTICO), ("1", men.EXIT_OK)])
def test_ag_a3_descuadre_positivo_lo_tapa_la_tolerancia(tolerancia, esperado, monkeypatch,
                                                        mails):
    """Descuadre positivo (se gastó de menos) es configurable: la variable existe para las
    devoluciones de más o las cancelaciones que la app no pudo acreditar por plan vencido."""
    monkeypatch.setenv("CREDITOS_DESCUADRE_TOLERANCIA", tolerancia)
    fila = [["9", "a@example.com", "20", "15", "5", "4", "0"]]   # gastó 5, esperado 4 ⇒ +1
    _psql_falso(monkeypatch, _ctx(a3_creditos=fila))

    assert men.main() == esperado
    if esperado == men.EXIT_DIAGNOSTICO:
        assert "gastó MÁS créditos de los que justifican sus reservas" in mails[0][1]


def test_ah_a3_la_consulta_usa_updated_at_y_la_regla_de_6_horas():
    """La reconstrucción del consumo se apoya en `reservas.updated_at` (el momento de la
    cancelación) y en la MISMA regla de devolución que `reservas.py` (>= 6 h)."""
    sql = men.sql_descuadre_creditos({"tenant_id": 1})

    assert "r.updated_at >" in sql and "interval '6 hours'" in sql
    assert "AT TIME ZONE 'America/Santiago'" in sql
    assert "JOIN LATERAL" in sql and sql.count("JOIN LATERAL") == 2
    assert "tokens_gastados" not in sql                  # no sirve: siempre queda en 1


# ── B.6/B.7: límites del plan Free en la API v2 de Neon (nunca sale a la red) ──
def _neon_falso(monkeypatch, ramas=None, cu_segundos=None, error=None) -> list:
    """Doble de `neon_api_get`: GET /projects/{id} y GET /projects/{id}/branches."""
    llamadas = []

    def fake(ruta, timeout=20):
        llamadas.append(ruta)
        if error:
            return {"ok": False, "status": 403, "datos": {}, "error": error}
        if ruta.endswith("/branches"):
            return {"ok": True, "status": 200, "datos": {"branches": ramas or []}, "error": ""}
        return {"ok": True, "status": 200, "error": "", "datos": {"project": {
            "compute_time_seconds": cu_segundos,
            "owner": {"subscription_type": "free"},
            "data_transfer_bytes": 123456, "written_data_bytes": 654321,
            "data_storage_bytes_hour": 999}}}

    monkeypatch.setattr(men, "neon_api_get", fake)
    return llamadas


def _env_neon(monkeypatch):
    monkeypatch.setenv("NEON_API_KEY", "napi_fake_no_real")
    monkeypatch.setenv("NEON_PROJECT_ID", "ep-prod-1234")


def test_ai_neon_api_sin_configurar_no_chequea_ni_rompe(monkeypatch, mails, capsys):
    """Sin el env group `neon-api` el job corre igual: B.6/B.7 quedan "no configurados"."""
    _psql_falso(monkeypatch, _ctx())
    llamadas = _neon_falso(monkeypatch, cu_segundos=999 * 3600)   # si se llamara, alertaría

    assert men.main() == men.EXIT_OK
    assert mails == [] and llamadas == []                # ni una llamada a la API
    assert "no configurado (faltan NEON_API_KEY, NEON_PROJECT_ID)" in capsys.readouterr().out


def test_aj_neon_api_cu_horas_sobre_el_umbral_avisa_por_mail(monkeypatch, mails):
    """B.6: 85 CU-horas de las 100 del plan Free (85 %) ⇒ correo, exit 0. Igual que la alerta
    de almacenamiento, es un aviso para mirar antes de que Neon corte: no aborta nada."""
    _env_neon(monkeypatch)
    _neon_falso(monkeypatch, cu_segundos=85 * 3600, ramas=[{"name": "main"}])
    _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_OK
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: Neon: CU-horas al 85.0%")
    assert "85.0 CU-horas de 100.0" in html
    assert "compute_time_seconds" in html                # se dice de qué campo salió
    assert "B.7 ramas:" in html and "✅" in html


def test_ak_neon_api_ramas_en_el_tope_avisa(monkeypatch, mails):
    """B.7: en el plan Free el proyecto admite 10 ramas; con 10 el drill no puede crear la suya."""
    _env_neon(monkeypatch)
    _neon_falso(monkeypatch, cu_segundos=3600, ramas=[{"name": f"r{i}"} for i in range(10)])
    _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_OK
    asunto, html = mails[0]
    assert "10 de 10 ramas" in asunto
    assert "el drill" in html and "r9" in html


def test_al_neon_api_caida_con_variables_puestas_es_rojo_exit_9(monkeypatch, mails):
    """Un chequeo CONFIGURADO que no corre tiene que verse: es hallazgo (exit 9), no silencio."""
    _env_neon(monkeypatch)
    _neon_falso(monkeypatch, error="HTTP 403: Forbidden")
    _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_DIAGNOSTICO
    asunto, html = mails[0]
    assert asunto.startswith("[ALERTA] Mantenimiento PROD: los chequeos nuevos encontraron 1")
    assert "no se pudo leer el proyecto en la API de Neon" in html
    assert "HTTP 403" in html


def test_am_neon_api_no_imprime_la_api_key(monkeypatch, mails, capsys):
    """La key viaja en el header: ni el log ni el mail pueden mostrarla."""
    _env_neon(monkeypatch)
    _neon_falso(monkeypatch, error="HTTP 500: boom")
    _psql_falso(monkeypatch, _ctx())

    assert men.main() == men.EXIT_DIAGNOSTICO
    salida = capsys.readouterr().out + _texto(mails[0])
    assert "napi_fake_no_real" not in salida


def test_an_neon_api_proyecto_con_forma_invalida_es_rojo_sin_llamar_a_la_api(monkeypatch, mails):
    """El id del proyecto se valida ANTES de armar la URL: nada de rutas con texto raro."""
    monkeypatch.setenv("NEON_API_KEY", "napi_fake_no_real")
    monkeypatch.setenv("NEON_PROJECT_ID", "EP-PROD!/../otro")
    _psql_falso(monkeypatch, _ctx())
    llamadas = _neon_falso(monkeypatch, cu_segundos=10 * 3600)

    assert men.main() == men.EXIT_DIAGNOSTICO
    assert llamadas == []
    assert "NEON_PROJECT_ID no tiene forma de id de proyecto" in mails[0][1]


# ── E: MRR / variación / churn de la cohorte de 30 días ───────────────────────
def test_ba_reporte_incluye_mrr_variacion_y_churn(monkeypatch, mails):
    """MRR y las demás métricas del bloque E con las MISMAS fórmulas del BI. Como el reponte
    viaja dentro de la alerta, se fuerza un rojo (integridad) para poder leerlo."""
    _psql_falso(monkeypatch, _ctx(mrr="60000", mrr_ant="50000", ret_base="40", ret_siguen="36",
                                  dup_rut=[["12345678-9", "2"]]))

    assert men.main() == men.EXIT_INTEGRIDAD
    html = mails[0][1]
    assert "variacion_mrr_pct" in html and "20.0" in html          # (60000−50000)/50000
    assert "retencion_30d_pct" in html and "churn_30d_pct" in html
    assert "alumnos_vigentes" in html and "bajas_mes" in html
    assert "planes_vencidos_mes" in html and "ingresos_mes" in html  # lo de la Fase 6 sigue


def test_bb_churn_no_se_publica_con_base_chica(monkeypatch, mails):
    """Con base < MIN_BASE_RETENCION se publica "sin dato" en vez de un porcentaje que no
    representa al box (el bug del 7600 % del BI)."""
    _psql_falso(monkeypatch, _ctx(ret_base="2", ret_siguen="1", a1b=[["1", "a@e.cl", "x", "t"]]))

    assert men.main() == men.EXIT_DIAGNOSTICO
    html = mails[0][1]
    assert "churn_nota" in html
    assert "sin dato: base 2" in html and "MIN_BASE_RETENCION 5" in html


def test_bc_el_mrr_usa_el_precio_de_lista_de_los_planes_vigentes():
    """Misma definición que `app/services/metricas_service.py::mrr` (una sola fórmula)."""
    sql = men.SQL_REPORTE["mrr"]

    assert "sum(p.precio_clp)" in sql and "JOIN planes p" in sql
    assert "s.estado = 'activo'" in sql
    assert "s.fecha_inicio::date <= current_date" in sql
    assert "s.fecha_expiracion::date >= current_date" in sql


# ── La regla del correo y el orden de los exit codes nuevos ───────────────────
def test_bd_hay_que_avisar_incluye_los_avisos_de_la_api_de_neon():
    base = {"neon": {"alerta": False}}

    assert men.hay_que_avisar(men.EXIT_OK, base) is False
    assert men.hay_que_avisar(men.EXIT_OK, {**base, "neon_api": {"alerta": True}}) is True
    assert men.hay_que_avisar(men.EXIT_OK, {**base, "neon_api": {}}) is False
    assert men.hay_que_avisar(men.EXIT_DIAGNOSTICO, base) is True
    assert men.hay_que_avisar(men.EXIT_INTEGRIDAD, base) is True


def test_be_la_integridad_gana_el_exit_y_las_detecciones_van_en_el_mail(monkeypatch, mails):
    """Con hallazgos de los dos tipos el exit es 4 (la integridad se evalúa primero) y el mail
    los trae todos: ninguno de los dos aborta la escritura."""
    _psql_falso(monkeypatch, _ctx(dup_rut=[["12345678-9", "2"]],
                                  a2c=[["1", "2026-09-01", "21", "20"]]))

    assert men.main() == men.EXIT_INTEGRIDAD
    html = mails[0][1]
    assert "RUT duplicados (1)" in html
    assert "A.2(c) clases por encima del cupo" in html


def test_bf_los_exit_codes_nuevos_tienen_titulo():
    assert men.TITULOS_EXIT[men.EXIT_DIAGNOSTICO] == "los chequeos nuevos encontraron algo"
    assert men.EXIT_DIAGNOSTICO == 9


# ── D-8 + C.8: "cancelada" no es un único literal y el cierre escribe `updated_at` ────────────
def test_bg_ninguna_consulta_compara_contra_el_literal_cancelled():
    """Guardia de regresión del punto 1: `reservas.estado` es un `character varying(20)` y en los
    datos hay DOS formas de "cancelada" —`'cancelled'`, la que escribe la app, y `'cancelada'`, la
    del enum viejo `estado_reserva`, que `kpis_populate.py` sigue contemplando—. Todo el SQL del
    mantenimiento tiene que usar `sql_viva()`/`sql_cancelada()`: contra el literal, la otra
    variante pasa por "viva" y el paso 8 le reescribiría `updated_at` (el dato de A.3).
    """
    cfg = men.leer_config()
    sqls = [c["sql"] for c in men.consultas_lista(cfg["dias_pendiente"])]
    sqls += [c["sql"] for c in men.consultas_cierre(cfg)]
    sqls += [c["sql"] for c in men.consultas_purga(cfg)]
    sqls += [c["sql"] for c in men.detecciones_sql(cfg)]
    sqls.append(men.sql_descuadre_creditos(cfg))
    sqls += [men.script_cambios(cfg["max_cambios"], cfg["dias_pendiente"], False),
             men.script_cierre(cfg["max_cierre"], cfg["dias_cierre"], False),
             men.script_purga(cfg["max_purga"], cfg["dias_purga_tokens"],
                              cfg["dias_purga_notif"], False)]

    todo = " ".join(sqls)
    assert men.sql_viva() == "r.estado NOT ILIKE '%cancel%'"
    assert men.sql_cancelada() == "r.estado ILIKE '%cancel%'"
    assert "NOT ILIKE '%cancel%'" in todo and "ILIKE '%cancel%'" in todo
    for sql in sqls:
        assert "'cancelled'" not in sql, sql[:140]
        assert "'cancelada'" not in sql, sql[:140]


def test_bh_el_paso_8_excluye_cualquier_cancelacion_y_el_paso_9_usa_lo_mismo():
    """Punto 1(a): el WHERE exacto del cierre. El paso 8 ESCRIBE `updated_at` ⇒ tiene que excluir
    cualquier forma de cancelación; el paso 9 (aforo) tiene que contar igual que el resto."""
    for dry in (True, False):
        cierre = men.script_cierre(500, 30, dry_run=dry)
        paso8, paso9 = cierre.split("-- 8)")[1].split("-- 9)")[0], cierre.split("-- 9)")[1]

        assert "UPDATE reservas AS r SET asistencia_marcada_at = now()" in paso8
        assert "updated_at = now()" in paso8              # escribe updated_at: de ahí el cuidado
        assert "r.estado NOT ILIKE '%cancel%'" in paso8   # ⇒ no toca NINGUNA cancelación
        assert "r.asistencia_marcada_at IS NULL" in paso8
        assert "SET estado" not in paso8                  # D-6: el estado no se toca
        # el conteo real y el `WHERE` del resync usan el MISMO predicado que el paso 8
        assert paso9.count("r.estado NOT ILIKE '%cancel%'") == 2

    # las 2 listas con las que se lee y se verifica el cierre, con el mismo predicado
    for consulta in men.consultas_cierre({"dias_cierre": 30}):
        assert "r.estado NOT ILIKE '%cancel%'" in consulta["sql"]


def test_bi_cancelada_con_anticipacion_no_la_toca_el_cierre_ni_la_cuenta_el_d8(monkeypatch,
                                                                               mails):
    """Punto 1(b): reserva CANCELADA con ≥ 6 h de anticipación.

    * el paso 8 no la toca (su `WHERE` es `sql_viva()`: excluye `'cancelled'` **y** `'cancelada'`),
      así que el `updated_at` de la cancelación —el dato del que A.3 deduce la tardanza— queda
      intacto después del cierre;
    * y no la cuenta como tardía: la regla de A.3 es "cancelada **y** cancelada menos de 6 h antes
      del inicio de la clase", o sea una devolución que la app no pudo acreditar. Con 7,5 h de
      anticipación no entra, así que después del cierre el run sigue verde (consumo = vivas).
    """
    # las 2 reglas, tal como las implementa el SQL (el SQL en sí se verifica en las aserciones)
    def viva(estado):                       # espejo de `sql_viva()`
        return "cancel" not in (estado or "").lower()

    def tardia(horas_antes, h=6):           # espejo de la LATERAL de A.3 (sólo canceladas)
        return horas_antes < h

    escenario = [{"estado": "cancelada", "horas_antes": 7.5},     # la del punto 1(b)
                 {"estado": "cancelled", "horas_antes": 2.0},     # tardía: SÍ cuenta
                 {"estado": "confirmada", "horas_antes": None}]   # viva: cuenta como reserva
    assert [viva(r["estado"]) for r in escenario] == [False, False, True]
    assert [tardia(r["horas_antes"]) for r in escenario[:2]] == [False, True]

    cierre = men.script_cierre(500, 30, dry_run=False)
    assert "r.estado NOT ILIKE '%cancel%'" in cierre               # el cierre no la toca
    sql_a3 = men.sql_descuadre_creditos({"tenant_id": 1})
    assert "r.estado ILIKE '%cancel%'" in sql_a3                  # sólo las canceladas pueden ser tardías
    assert "r.updated_at >" in sql_a3 and "interval '6 hours'" in sql_a3

    # después del cierre (REAL) el run queda verde: 5 vivas + 0 tardías contra 5 gastados
    monkeypatch.setenv("DRY_RUN", "0")
    _psql_falso(monkeypatch, _ctx(despues="vacio",
                                  a3_creditos=[["9", "a@example.com", "20", "15", "5", "5", "0"]]))
    assert men.main() == men.EXIT_OK
    assert mails == []


def test_bj_las_tres_transacciones_son_idempotentes_y_escriben_tablas_disjuntas():
    """Punto 4: re-ejecutar el job no duplica ni revierte lo ya aplicado.

    1. cada transacción filtra lo que ya hizo (por estado, por `asistencia_marcada_at IS NULL` y
       por antigüedad), así que la segunda corrida no encuentra nada que volver a tocar;
    2. los únicos `INSERT` van a la tabla temporal de la propia transacción: en tablas reales no
       hay `INSERT`, así que nada se puede duplicar;
    3. las tablas que escribe cada una son DISJUNTAS: si la 2 o la 3 fallan (abortan y quedan sin
       aplicar), no pueden deshacer ni reescribir lo que la 1 ya confirmó con su `COMMIT`.
    """
    cambios = men.script_cambios(40, 30, False)
    cierre = men.script_cierre(500, 30, False)
    purga = men.script_purga(5000, 90, 180, False)

    # 1) filtros de idempotencia
    assert "s.estado = 'activo' AND s.fecha_expiracion < current_date" in cambios
    assert "s.estado = 'pendiente' AND s.created_at < now() - interval" in cambios
    assert "sp.estado = 'pending' AND sp.created_at < now() - interval" in cambios
    assert "u.estado = 'pendiente_activacion' AND u.created_at < now() - interval" in cambios
    assert "r.asistencia_marcada_at IS NULL" in cierre
    assert "c.asistentes_confirmados <> (SELECT count(*)" in cierre
    assert "expires_at < now() - interval" in purga
    assert "fecha_envio < now() - interval" in purga

    # 2) nada de INSERT en tablas reales (sólo a la temporal)
    for script, pasos in ((cambios, 4), (cierre, 2), (purga, 2)):
        assert script.count("INSERT INTO") == pasos
        assert script.count("INSERT INTO _maint_") == pasos

    # 3) tablas escritas por cada transacción (UPDATE / DELETE): disjuntas entre sí
    def escritas(script: str) -> set:
        return set(re.findall(r"(?:UPDATE|DELETE FROM)\s+([a-z_]+)", script))

    assert escritas(cambios) == {"suscripciones", "solicitudes_planes", "usuarios"}
    assert escritas(cierre) == {"reservas", "clases"}
    assert escritas(purga) == {"password_reset_tokens", "notificaciones_enviadas"}
    assert not (escritas(cambios) & escritas(cierre))
    assert not (escritas(cambios) & escritas(purga))
    assert not (escritas(cierre) & escritas(purga))


def test_bk_doble_corrida_no_duplica_ni_revierte_lo_aplicado(monkeypatch, mails, capsys):
    """Punto 4, de punta a punta: la 2ª corrida (con la base ya como tiene que quedar) genera
    EXACTAMENTE el mismo SQL, no encuentra nada pendiente, aplica 0 filas y vuelve a quedar verde:
    el job no acumula trabajo ni vuelve a tocar lo que ya aplicó la primera vez."""
    monkeypatch.setenv("DRY_RUN", "0")
    rastro1 = _psql_falso(monkeypatch, _ctx(
        despues="vacio", vencidos=_n_filas(1), cierre_pendientes=_n_filas(2),
        aforo_resync=_n_filas(1), tokens_reset=_n_filas(3),
        script_out=script_out(vencidos=1),
        script_out_cierre=script_out_cierre(cierre=2, aforo=1),
        script_out_purga=script_out_purga(tokens=3)))

    assert men.main() == men.EXIT_OK
    out1 = capsys.readouterr().out
    assert "vencidos=1" in out1 and "aforo_resync=1" in out1 and "tokens_reset=3" in out1

    # 2ª corrida: la base ya quedó limpia (listas vacías y las 3 transacciones en 0)
    rastro2 = _psql_falso(monkeypatch, _ctx(despues="vacio"))
    assert men.main() == men.EXIT_OK
    out2 = capsys.readouterr().out

    assert rastro1["scripts"] == rastro2["scripts"]     # mismo SQL: la 2ª no cambia de forma
    assert len(rastro2["scripts"]) == 3
    assert ("  cambios: huerfanas_solicitudes=0, huerfanas_suscripciones=0, "
            "huerfanas_usuarios=0, vencidos=0") in out2
    assert "  consistencia: aforo_resync=0, cierre_asistencia=0" in out2
    assert "  purga: notificaciones=0, tokens_reset=0" in out2
    assert mails == []                                  # las 2 corridas verdes: sólo log


def test_bl_neon_api_sin_credenciales_exit_0_y_un_solo_aviso_por_corrida(monkeypatch, mails,
                                                                        capsys):
    """Punto 2: sin `NEON_API_KEY`/`NEON_PROJECT_ID` el job sale 0 y la nota de "no configurado" es
    UNA por corrida (no una por chequeo, B.6 y B.7), tanto en el log como en el correo."""
    _psql_falso(monkeypatch, _ctx())
    llamadas = _neon_falso(monkeypatch, cu_segundos=999 * 3600, ramas=[{"name": "main"}])

    assert men.main() == men.EXIT_OK
    assert llamadas == [] and mails == []
    assert capsys.readouterr().out.count(
        "no configurado (faltan NEON_API_KEY, NEON_PROJECT_ID)") == 1

    # el mismo caso, pero con un run rojo (para que salga el correo): la nota va UNA vez
    _psql_falso(monkeypatch, _ctx(dup_rut=[["12345678-9", "2"]]))
    assert men.main() == men.EXIT_INTEGRIDAD
    assert len(mails) == 1
    assert mails[0][1].count("no configurado (faltan NEON_API_KEY, NEON_PROJECT_ID)") == 1


def test_bm_el_aforo_va_en_la_guarda_se_verifica_y_el_log_dice_cuantas_clases(monkeypatch,
                                                                             mails, capsys):
    """Punto 3: el resync de `clases.asistentes_confirmados` (paso 9) comparte la guarda
    `MAX_CIERRE` con el paso 8 (los 2 cuentan en `_maint_cierre`), se verifica después igual que el
    resto y el log informa cuántas CLASES cambió, no sólo el total de la transacción."""
    monkeypatch.setenv("DRY_RUN", "0")
    rastro = _psql_falso(monkeypatch, _ctx(despues="vacio", cierre_pendientes=_n_filas(2),
                                           aforo_resync=_n_filas(3),
                                           script_out_cierre=script_out_cierre(cierre=2, aforo=3)))

    assert men.main() == men.EXIT_OK
    cierre = rastro["scripts"][1]
    guarda = cierre.split("-- 9)")[1]
    assert "MAX_CIERRE=500" in guarda and "GUARDA DE VOLUMEN" in guarda
    assert cierre.index("-- 9)") < cierre.index("MAX_CIERRE")     # el aforo va DENTRO de la guarda
    out = capsys.readouterr().out
    assert "  consistencia: aforo_resync=3, cierre_asistencia=2" in out
    assert "Transacción aplicada y verificada: 5 cierre(s) (consistencia)" in out
    assert mails == []

    # y la verificación posterior incluye las 2 listas: si el aforo no quedó en 0, el run es rojo
    _psql_falso(monkeypatch, _ctx(despues="igual", cierre_pendientes=_n_filas(2),
                                  aforo_resync=_n_filas(3),
                                  script_out_cierre=script_out_cierre(cierre=2, aforo=3)))
    assert men.main() == men.EXIT_VERIFICACION
    html = mails[0][1]
    assert "aforo_resync 3 → 3 (esperado 0)" in html
    assert "cierre_asistencia 2 → 2 (esperado 0)" in html

