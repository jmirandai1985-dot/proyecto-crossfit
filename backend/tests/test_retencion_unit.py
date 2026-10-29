"""Tests unitarios de la retención de datos (B8) — sin red, sin base y sin correo.

Se corre SIN `conftest.py` (ese conftest habla con la API en :8000 y aborta si el
servidor no es TEST), igual que `test_watchdog_backups.py`:

    py -3.12 -m pytest tests/test_retencion_unit.py -q --noconftest

Qué se cubre
------------
  * las tuplas de ramas TEST/PROD son **idénticas** a las de `app/core/config.py`:
    el contenedor de cron no puede importar `app/`, así que están duplicadas y, si
    alguien cambia una rama en un solo lugar, este test falla;
  * las columnas de `TABLAS_ARCHIVO` son exactamente las del modelo
    `app/models/archivo_retencion.py` (la copia y el md5 usan esa lista);
  * la configuración falla CERRADO (URL de PROD, endpoint retirado, `-pooler`,
    escribir en TEST sin `RETENCION_TEST_OK=1`, pepper corto, números fuera de rango);
  * los umbrales (5 años / 2 años / 12 meses) llegan al SQL;
  * `rut_anonimo` es determinista y no deja rastro del RUT original;
  * los tres trabajos NO escriben con 0 pendientes, en DRY_RUN ni cuando la guarda
    de volumen aborta, y el respaldo se sube ANTES de borrar;
  * `main()` traduce cada error a su exit code y sólo manda correo si hay algo que
    revisar.
"""
import ast
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from maintenance import retencion_cloud as rc  # noqa: E402

USUARIO = rc.USUARIO_ROL
TEST_ID = rc.TEST_BRANCH_IDS[0]
PROD_ID = rc.PROD_BRANCH_IDS[0]
PEPPER = "pepper-de-prueba-1234567890"


def url(branch: str, usuario: str = USUARIO) -> str:
    """URL de Neon con la forma real (host largo, conexión directa)."""
    return (f"postgresql://{usuario}:clave-falsa@{branch}.c-9.us-west-2"
            ".aws.neon.tech/neondb?sslmode=require")


URL_TEST = url(TEST_ID)
URL_PROD = url(PROD_ID)


def env_base(**extra) -> dict:
    """Entorno mínimo COMPLETO; `None` borra la variable (para probar faltantes)."""
    env = {
        "RETENCION_DB_URL": URL_TEST,
        "ENVIRONMENT": "test",
        "DRY_RUN": "1",
        "ANONIMIZACION_PEPPER": PEPPER,
        "R2_ENDPOINT": "https://fake.r2.cloudflarestorage.com",
        "R2_BUCKET": "bucket-falso",
        "R2_ACCESS_KEY_ID": "AKIAFALSA",
        "R2_SECRET_ACCESS_KEY": "secreto-falso",
    }
    for clave, valor in extra.items():
        if valor is None:
            env.pop(clave, None)
        else:
            env[clave] = valor
    return env


def cfg_test(trabajo: str = "archivar", **extra) -> dict:
    return rc.cargar_config(trabajo, env_base(**extra))


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """`main()` lee `os.environ`: el mismo entorno mínimo para todo el módulo."""
    for clave, valor in env_base().items():
        monkeypatch.setenv(clave, valor)
    yield


# ── 1) Paridad con la app (las tuplas están duplicadas a propósito) ─────────
def _asignaciones_de_config() -> dict:
    """Lee `app/core/config.py` con `ast` (importarlo abriría una conexión)."""
    fuente = (BACKEND / "app" / "core" / "config.py").read_text(encoding="utf-8")
    salida = {}
    for nodo in ast.parse(fuente).body:
        if not isinstance(nodo, ast.Assign):
            continue
        try:
            valor = ast.literal_eval(nodo.value)
        except ValueError:      # expresiones que no son literales: no interesan
            continue
        for destino in nodo.targets:
            if isinstance(destino, ast.Name):
                salida[destino.id] = valor
    return salida


def test_tuplas_de_ramas_iguales_a_app_core_config():
    app = _asignaciones_de_config()
    assert tuple(app["TEST_BRANCH_IDS"]) == rc.TEST_BRANCH_IDS
    assert tuple(app["PROD_BRANCH_IDS"]) == rc.PROD_BRANCH_IDS
    assert tuple(app["ENDPOINTS_RETIRADOS"]) == rc.ENDPOINTS_RETIRADOS
    assert app["PROD_BRANCH_ID"] == rc.PROD_BRANCH_IDS[0]
    # Y ninguna tupla puede solaparse: un endpoint no es TEST y PROD a la vez.
    assert not set(rc.TEST_BRANCH_IDS) & set(rc.PROD_BRANCH_IDS)
    assert not set(rc.TEST_BRANCH_IDS) & set(rc.ENDPOINTS_RETIRADOS)


def test_columnas_del_job_iguales_al_modelo_de_archivo():
    modelos = pytest.importorskip("app.models.archivo_retencion")
    for tabla, modelo in (("asistencias", modelos.AsistenciaArchivo),
                          ("reservas", modelos.ReservaArchivo)):
        columnas = [c for c in modelo.__table__.columns.keys()
                    if c != "archivado_en"]
        meta = rc.TABLAS_ARCHIVO[tabla]
        assert meta["archivo"] == modelo.__tablename__
        assert list(meta["columnas"]) == columnas, tabla


# ── 2) Configuración: umbrales y guardas ───────────────────────────────────
def test_config_por_defecto_respeta_los_plazos():
    cfg = cfg_test("archivar")
    assert cfg["anios_archivo"] == 5
    assert cfg["anios_auditoria"] == 2
    assert cfg["meses_anonimizar"] == 12
    assert cfg["lote"] == 5000
    assert cfg["lock_horas"] == 12
    assert cfg["dry_run"] is True            # fail-safe: sin DRY_RUN no se escribe
    assert cfg["entorno"] == "test"
    assert cfg["clase_url"] == "test"
    assert cfg["prefijo"] == "retencion/"
    assert cfg["respaldo_local"] == ""
    assert cfg["trabajo"] == "archivar"


def test_umbrales_son_configurables():
    cfg = cfg_test("archivar", ANIOS_RETENCION_ARCHIVO="7",
                   ANIOS_RETENCION_AUDITORIA="3", MESES_RETENCION_ANONIMIZAR="18",
                   TAM_LOTE="750", MAX_ARCHIVAR="900")
    assert (cfg["anios_archivo"], cfg["anios_auditoria"],
            cfg["meses_anonimizar"]) == (7, 3, 18)
    assert (cfg["lote"], cfg["max_archivar"]) == (750, 900)


def test_escribir_en_test_exige_retencion_test_ok():
    with pytest.raises(rc.ConfigError) as e:
        cfg_test("archivar", DRY_RUN="0")
    assert "RETENCION_TEST_OK" in str(e.value)
    assert cfg_test("archivar", DRY_RUN="0",
                    RETENCION_TEST_OK="1")["dry_run"] is False


@pytest.mark.parametrize("caso, extra, aguja", [
    ("url de PROD con ENVIRONMENT=test", {"RETENCION_DB_URL": URL_PROD},
     "rama TEST"),
    ("endpoint retirado", {"RETENCION_DB_URL": url(rc.ENDPOINTS_RETIRADOS[0])},
     "RETIRADO"),
    ("endpoint desconocido", {"RETENCION_DB_URL": url("ep-rama-inventada")},
     "rama TEST"),
    ("con -pooler", {"RETENCION_DB_URL": URL_TEST.replace(".c-9", "-pooler.c-9")},
     "-pooler"),
    ("otro motor", {"RETENCION_DB_URL": "mysql://a:b@host/db"}, "postgresql://"),
    ("dos arrobas", {"RETENCION_DB_URL": URL_TEST.replace("clave-falsa", "a@b")},
     "'@'"),
    ("vacía", {"RETENCION_DB_URL": ""}, "RETENCION_DB_URL"),
])
def test_config_rechaza_urls(caso, extra, aguja):
    with pytest.raises(rc.ConfigError) as e:
        rc.cargar_config("archivar", env_base(**extra))
    assert aguja in str(e.value), caso


def test_production_con_url_test_o_usuario_ajeno_se_rechaza():
    with pytest.raises(rc.ConfigError) as e:
        rc.cargar_config("archivar", env_base(ENVIRONMENT="production"))
    assert "rama TEST" in str(e.value)
    with pytest.raises(rc.ConfigError) as e:
        rc.cargar_config("archivar", env_base(
            ENVIRONMENT="production", RETENCION_DB_URL=url(PROD_ID, "postgres")))
    assert rc.USUARIO_ROL in str(e.value)


def test_production_con_url_y_usuario_correctos_es_valida():
    cfg = rc.cargar_config("archivar", env_base(
        ENVIRONMENT="production", RETENCION_DB_URL=URL_PROD))
    assert (cfg["entorno"], cfg["clase_url"]) == ("production", "prod")


@pytest.mark.parametrize("trabajo, extra, aguja", [
    ("archivar", {"R2_BUCKET": None}, "R2_BUCKET"),
    ("archivar", {"RETENCION_DB_URL": None}, "RETENCION_DB_URL"),
    ("anonimizar", {"ANONIMIZACION_PEPPER": None}, "ANONIMIZACION_PEPPER"),
    ("anonimizar", {"ANONIMIZACION_PEPPER": "corto"}, "16"),
])
def test_config_exige_variables(trabajo, extra, aguja):
    with pytest.raises(rc.ConfigError) as e:
        rc.cargar_config(trabajo, env_base(**extra))
    assert aguja in str(e.value), trabajo


def test_archivar_sin_r2_alcanza_con_respaldo_local(tmp_path):
    cfg = rc.cargar_config("archivar", env_base(
        R2_ENDPOINT=None, R2_BUCKET=None, R2_ACCESS_KEY_ID=None,
        R2_SECRET_ACCESS_KEY=None, RETENCION_RESPALDO_LOCAL=str(tmp_path)))
    assert cfg["respaldo_local"] == str(tmp_path)


def test_trabajo_desconocido_no_se_ejecuta():
    with pytest.raises(rc.ConfigError) as e:
        rc.cargar_config("borrar-todo", env_base())
    assert "desconocido" in str(e.value)


@pytest.mark.parametrize("extra", [
    {"ENVIRONMENT": "staging"},
    {"DRY_RUN": "quizás"},
    {"TAM_LOTE": "0"},
    {"TAM_LOTE": "muchas"},
    {"ANIOS_RETENCION_ARCHIVO": "200"},
    {"RETENCION_LOCK_HORAS": "500"},
])
def test_config_rechaza_valores_invalidos(extra):
    with pytest.raises(rc.ConfigError):
        rc.cargar_config("archivar", env_base(**extra))


# ── 3) SQL: umbrales, topes y blindaje de ids ──────────────────────────────
def test_corte_usa_la_columna_y_los_anios():
    assert rc.corte("fecha", "date", 5) == "(CURRENT_DATE - INTERVAL '5 years')"
    assert rc.corte("fecha_reserva", "timestamp", 5) == \
        "(now() - INTERVAL '5 years')"


def test_los_umbrales_llegan_al_sql():
    cfg = cfg_test("archivar", ANIOS_RETENCION_ARCHIVO="5",
                   ANIOS_RETENCION_AUDITORIA="2", MESES_RETENCION_ANONIMIZAR="12",
                   TAM_LOTE="500")
    assert "INTERVAL '5 years'" in rc.sql_pendientes("asistencias", cfg)
    lote = rc.sql_lote("reservas", cfg, 25)
    assert "fecha_reserva" in lote and "LIMIT 25" in lote and "ORDER BY t.id" in lote
    assert "INTERVAL '2 years'" in rc.sql_pendientes_auditoria(cfg)
    borrar = rc.sql_borrar_auditoria(cfg, 10)
    assert "INTERVAL '2 years'" in borrar and "LIMIT 10" in borrar
    # El conteo vuelve como FILA (psql corre con -q y no imprime los tags).
    assert "RETURNING" in borrar and "SELECT count(*)" in borrar
    assert "INTERVAL '12 months'" in rc.sql_pendientes_anonimizar(cfg)
    lote_anon = rc.sql_lote_anonimizar(cfg)
    assert "anonimizado_en IS NULL" in lote_anon and "LIMIT 500" in lote_anon


def test_prologo_fija_utc_para_que_el_md5_sea_comparable():
    assert "TIME ZONE 'UTC'" in rc.PROLOGO


def test_lista_ids_no_deja_pasar_texto():
    assert rc.lista_ids([3, 5]) == "ARRAY[3,5]::int[]"
    with pytest.raises(ValueError):
        rc.lista_ids(["1; DROP TABLE usuarios"])


def test_filas_a_ids_ignora_lineas_vacias_y_rechaza_basura():
    assert rc.filas_a_ids("5\n\n7\n") == [5, 7]
    with pytest.raises(rc.LecturaError):
        rc.filas_a_ids("5; DROP TABLE usuarios")


def test_rut_anonimo_es_determinista_y_no_deja_rastro():
    unico = rc.rut_anonimo(PEPPER, 7, "12.345.678-9")
    assert unico == rc.rut_anonimo(PEPPER, 7, "12.345.678-9")   # repetible
    assert len(unico) == 12 and unico.startswith("ANON")
    assert "12345678" not in unico and "123456789" not in unico
    assert rc.rut_anonimo(PEPPER, 7, "12.345.678-9") != \
        rc.rut_anonimo(PEPPER, 7, "9.876.543-2")                # cambia el RUT
    assert rc.rut_anonimo(PEPPER, 7, "12.345.678-9") != \
        rc.rut_anonimo(PEPPER, 8, "12.345.678-9")               # cambia el id
    # Sin el pepper, el mismo RUT daría otro valor: la sal es lo que impide
    # reconstruirlo a partir de la tabla.
    assert unico != rc.rut_anonimo("otro-pepper-1234567", 7, "12.345.678-9")


def test_rut_validado_solo_acepta_el_formato_generado():
    assert rc._rut_validado("ANONab12cd34") == "ANONab12cd34"
    with pytest.raises(rc.EscrituraError):
        rc._rut_validado("ANON'; DROP TABLE usuarios; --")


def test_pares_anonimos_devuelve_id_y_rut_anonimo():
    pares = rc.pares_anonimos("3|12345678-9\n4|\n", PEPPER)
    assert [p[0] for p in pares] == [3, 4]
    assert all(len(r) == 12 and r.startswith("ANON") for _, r in pares)
    with pytest.raises(rc.LecturaError):
        rc.pares_anonimos("x|12345678-9", PEPPER)


def test_clave_de_respaldo_ordena_por_fecha_y_dice_las_filas():
    clave = rc.clave_respaldo({"prefijo": "retencion/"}, "asistencias", 1200)
    assert clave.startswith("retencion/asistencias/")
    assert clave.endswith("_1200f.csv.gz")
    sello = clave.split("/")[-1].split("_")[0]
    assert len(sello) == 10 and sello[4] == "-" and sello[7] == "-"


# ── 4) Los tres trabajos: qué escriben y qué NO ────────────────────────────
class Falso:
    """Reemplaza la capa psql. Anota escrituras y devuelve lo que se le pida."""

    def __init__(self, pendientes: int = 0, lote: str = ""):
        self.pendientes = pendientes
        self.lote = lote
        self.escrituras = []

    def consulta_entero(self, url, sql):
        return self.pendientes

    def consulta(self, url, sql):
        return self.lote

    def script_escritura(self, url, texto, que):
        self.escrituras.append(que)
        return "0"


@pytest.fixture
def falso(monkeypatch):
    f = Falso()
    monkeypatch.setattr(rc, "consulta_entero", f.consulta_entero)
    monkeypatch.setattr(rc, "consulta", f.consulta)
    monkeypatch.setattr(rc, "script_escritura", f.script_escritura)
    monkeypatch.setattr(rc, "r2_disponible", lambda: False)
    monkeypatch.setattr(rc, "exportar_csv",
                        lambda url, tabla, ids, destino:
                        {"filas": len(ids), "bytes": 1, "sha256": "sha-falso"})
    monkeypatch.setattr(rc, "subir_respaldo",
                        lambda clave, destino, info: None)
    return f


@pytest.mark.parametrize("trabajo", rc.TRABAJOS)
def test_sin_pendientes_no_escribe_ni_respalda(trabajo, falso, monkeypatch):
    subidas = []
    monkeypatch.setattr(rc, "subir_respaldo",
                        lambda clave, destino, info: subidas.append(clave))
    res = rc.TRABAJOS_FUNCIONES[trabajo](cfg_test(trabajo))
    assert rc.movidas(trabajo, res) == 0
    assert falso.escrituras == [] and subidas == []


def test_dry_run_cuenta_pero_no_toca_la_base(falso):
    falso.pendientes = 3
    res = rc.job_archivar(cfg_test("archivar"))
    assert res["tablas"]["asistencias"]["habria_movido"] == 3
    assert res["tablas"]["reservas"]["habria_movido"] == 3
    assert rc.movidas("archivar", res) == 6      # lo que se habría movido
    assert res["movidas"] == 0 and res["respaldos"] == []
    assert falso.escrituras == []

    res = rc.job_auditoria(cfg_test("auditoria"))
    assert res == {"pendientes": 3, "purgadas": 0, "habria_purgado": 3}
    assert falso.escrituras == []

    res = rc.job_anonimizar(cfg_test("anonimizar"))
    assert res == {"pendientes": 3, "anonimizadas": 0, "lotes": 0,
                   "habria_anonimizado": 3}
    assert falso.escrituras == []


@pytest.mark.parametrize("trabajo, variable, tope", [
    ("archivar", "MAX_ARCHIVAR", 20_000),
    ("auditoria", "MAX_BORRAR_AUDITORIA", 100_000),
    ("anonimizar", "MAX_ANONIMIZAR", 1_000),
])
def test_la_guarda_de_volumen_aborta_antes_de_escribir(trabajo, variable, tope,
                                                       falso):
    falso.pendientes = tope + 1
    with pytest.raises(rc.GuardaError) as e:
        rc.TRABAJOS_FUNCIONES[trabajo](cfg_test(trabajo))
    assert variable in str(e.value)
    assert falso.escrituras == []


def test_archivar_respalda_y_verifica_antes_de_borrar(falso, monkeypatch):
    eventos = []
    falso.pendientes = 2
    falso.lote = "7\n8"
    monkeypatch.setattr(rc, "r2_disponible", lambda: True)
    monkeypatch.setattr(rc, "exportar_csv",
                        lambda url, tabla, ids, destino: eventos.append(
                            ("csv", tabla, tuple(ids)))
                        or {"filas": len(ids), "bytes": 10, "sha256": "abc"})
    monkeypatch.setattr(rc, "subir_respaldo",
                        lambda clave, destino, info: eventos.append(
                            ("subir", clave)))
    monkeypatch.setattr(rc, "script_escritura",
                        lambda url, texto, que: eventos.append(("sql", que)) or "0")

    res = rc.job_archivar(cfg_test("archivar", DRY_RUN="0", RETENCION_TEST_OK="1"))

    # Orden por lote, y nunca al revés: copiar → CSV → subir → borrar.
    assert [e[0] for e in eventos[:4]] == ["sql", "csv", "subir", "sql"]
    assert eventos[0][1].startswith("copia de asistencias")
    assert eventos[1][1] == "asistencias" and eventos[1][2] == (7, 8)
    assert eventos[2][1].startswith("retencion/asistencias/")
    assert eventos[3][1].startswith("borrado de asistencias")
    assert res["movidas"] == 4 and len(res["respaldos"]) == 2
    assert res["tablas"]["asistencias"] == {"pendientes": 2, "movidas": 2}


def test_si_falla_el_respaldo_el_lote_queda_en_el_origen(falso, monkeypatch):
    escrituras = []
    falso.pendientes = 2
    falso.lote = "7\n8"
    monkeypatch.setattr(rc, "r2_disponible", lambda: True)
    monkeypatch.setattr(rc, "script_escritura",
                        lambda url, texto, que: escrituras.append(que) or "0")

    def rompe(clave, destino, info):
        raise rc.S3Error("R2 caído")

    monkeypatch.setattr(rc, "subir_respaldo", rompe)
    with pytest.raises(rc.S3Error):
        rc.job_archivar(cfg_test("archivar", DRY_RUN="0", RETENCION_TEST_OK="1"))
    assert escrituras and all(q.startswith("copia de") for q in escrituras)
    assert not any(q.startswith("borrado de") for q in escrituras)


def test_auditoria_purga_en_una_sola_vuelta_lo_que_falta(falso, monkeypatch):
    falso.pendientes = 2
    limites = []

    def escribir(url, texto, que):
        return "2\n" if len(limites) == 1 else "0\n"

    monkeypatch.setattr(rc, "script_escritura", escribir)
    monkeypatch.setattr(rc, "sql_borrar_auditoria",
                        lambda cfg, limite: limites.append(limite) or f"limite={limite}")
    res = rc.job_auditoria(cfg_test("auditoria", DRY_RUN="0",
                                    RETENCION_TEST_OK="1"))
    assert res == {"pendientes": 2, "purgadas": 2}
    assert limites == [2]        # min(lote, pendientes)


def test_anonimizar_manda_rut_anonimos_y_nunca_el_real(falso, monkeypatch):
    falso.pendientes = 2
    falso.lote = "11|12345678-9\n12|9876543-2\n"
    enviados = []
    monkeypatch.setattr(rc, "script_escritura",
                        lambda url, texto, que: enviados.append(texto) or "0")
    res = rc.job_anonimizar(cfg_test("anonimizar", DRY_RUN="0",
                                     RETENCION_TEST_OK="1"))
    assert res["anonimizadas"] == 2 and res["lotes"] == 1
    assert "ANON" in enviados[0]
    assert "12345678" not in enviados[0] and "9876543" not in enviados[0]


def test_anonimizar_aborta_si_el_conteo_no_avanza(falso, monkeypatch):
    falso.pendientes = 2
    falso.lote = "11|12345678-9\n"
    monkeypatch.setattr(rc, "script_escritura", lambda url, texto, que: "0")
    with pytest.raises(rc.VerificacionError):
        rc.job_anonimizar(cfg_test("anonimizar", DRY_RUN="0",
                                   RETENCION_TEST_OK="1"))


# ── 5) Reporte y main: exit codes y política de correo ─────────────────────
@pytest.fixture
def correos(monkeypatch):
    """Captura los envíos y define las 3 variables que habilitan el aviso."""
    capturados = []
    monkeypatch.setattr(rc, "enviar_email",
                        lambda asunto, html, logger=None:
                        capturados.append((asunto, html)) or True)
    for clave, valor in (("GMAIL_SMTP_USER", "box@example.com"),
                         ("GMAIL_SMTP_APP_PASSWORD", "app-falsa"),
                         ("ALERT_EMAIL", "alertas@example.com")):
        monkeypatch.setenv(clave, valor)
    return capturados


@pytest.fixture
def bloqueo(monkeypatch):
    """main() sin red: esquema y bloqueo simulados (devuelve los tokens liberados)."""
    monkeypatch.setattr(rc, "verificar_esquema", lambda url: None)
    monkeypatch.setattr(rc, "tomar_bloqueo", lambda cfg: "token-1")
    liberados = []
    monkeypatch.setattr(rc, "liberar_bloqueo",
                        lambda cfg, token: liberados.append(token))
    return liberados


def test_res_inicial_no_comparte_estructuras():
    uno, otro = rc.res_inicial("archivar"), rc.res_inicial("archivar")
    uno["tablas"]["asistencias"] = {"pendientes": 9}
    uno["respaldos"].append("x")
    assert otro == {"tablas": {}, "respaldos": [], "movidas": 0}
    assert rc.res_inicial("auditoria") == {"pendientes": 0, "purgadas": 0}
    assert rc.res_inicial("anonimizar") == {"pendientes": 0, "anonimizadas": 0,
                                            "lotes": 0}


def test_movidas_suma_lo_hecho_y_lo_que_se_habria_hecho():
    res = {"tablas": {"asistencias": {"movidas": 2, "habria_movido": 3},
                      "reservas": {"movidas": 1}}, "movidas": 3}
    assert rc.movidas("archivar", res) == 6
    assert rc.movidas("archivar", rc.res_inicial("archivar")) == 0
    assert rc.movidas("auditoria", {"purgadas": 4, "habria_purgado": 5}) == 9
    assert rc.movidas("anonimizar", {"anonimizadas": 1}) == 1


def test_lineas_resumen_dicen_que_paso_en_cada_tabla():
    res = {"tablas": {"asistencias": {"pendientes": 4, "movidas": 4}},
           "respaldos": ["retencion/asistencias/x.csv.gz"], "movidas": 4}
    texto = " | ".join(rc.lineas_resumen("archivar", res))
    assert "asistencias: 4 pendiente(s), 4 movida(s)" in texto
    assert "respaldos verificados: 1" in texto
    texto = " | ".join(rc.lineas_resumen("anonimizar",
                                         {"pendientes": 2, "anonimizadas": 2,
                                          "lotes": 1}))
    assert "2 anonimizada(s) en 1 lote(s)" in texto


def test_asunto_dice_entorno_conteo_y_dry_run():
    cfg = cfg_test("auditoria")
    res = {"pendientes": 2, "purgadas": 0, "habria_purgado": 2}
    asunto = rc.asunto_email("auditoria", cfg, res, rc.EXIT_OK)
    assert asunto.startswith("[retención] TEST auditoria") and "DRY_RUN" in asunto
    assert "2 fila(s) purgadas" in asunto
    real = cfg_test("auditoria", DRY_RUN="0", RETENCION_TEST_OK="1")
    assert "DRY_RUN" not in rc.asunto_email("auditoria", real, {"pendientes": 2,
                                                               "purgadas": 2},
                                            rc.EXIT_OK)
    alerta = rc.asunto_email("auditoria", real, {"pendientes": 2, "purgadas": 2},
                             rc.EXIT_GUARDA)
    assert alerta.startswith("[ALERTA]") and "guarda" in alerta.lower()


def test_main_sin_argumentos_o_con_trabajo_invalido_no_hace_nada(bloqueo, correos):
    assert rc.main([]) == rc.EXIT_CONFIG
    assert rc.main(["todo"]) == rc.EXIT_CONFIG
    assert rc.main(["archivar", "auditoria"]) == rc.EXIT_CONFIG
    assert bloqueo == [] and correos == []


def test_main_traduce_cada_error_a_su_exit_code(bloqueo, correos, monkeypatch):
    casos = [(rc.ConfigError("cfg"), rc.EXIT_CONFIG),
             (rc.LecturaError("red"), rc.EXIT_LECTURA),
             (rc.S3Error("R2"), rc.EXIT_RESPALDO),
             (rc.RespaldoError("csv"), rc.EXIT_RESPALDO),
             (rc.GuardaError("tope"), rc.EXIT_GUARDA),
             (rc.EscrituraError("tx"), rc.EXIT_ESCRITURA),
             (rc.VerificacionError("md5"), rc.EXIT_VERIFICACION),
             (RuntimeError("inesperado"), rc.EXIT_LECTURA)]
    for excepcion, esperado in casos:
        correos.clear()
        bloqueo.clear()

        def rompe(cfg, res, _e=excepcion):
            raise _e

        monkeypatch.setitem(rc.TRABAJOS_FUNCIONES, "archivar", rompe)
        assert rc.main(["archivar"]) == esperado, type(excepcion).__name__
        assert bloqueo == ["token-1"]          # el bloqueo se libera SIEMPRE
        assert len(correos) == 1 and correos[0][0].startswith("[ALERTA]")


def test_main_run_verde_sin_filas_solo_deja_log(bloqueo, correos, falso):
    assert rc.main(["archivar"]) == rc.EXIT_OK
    assert correos == []          # nada que revisar ⇒ no se manda correo
    assert bloqueo == ["token-1"]


def test_main_avisa_cuando_purga_filas(bloqueo, correos, falso, monkeypatch):
    falso.pendientes = 2
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("RETENCION_TEST_OK", "1")
    monkeypatch.setattr(rc, "script_escritura", lambda url, texto, que: "2")
    assert rc.main(["auditoria"]) == rc.EXIT_OK
    assert len(correos) == 1
    assert "2 fila(s) purgadas" in correos[0][0]
    assert "DRY_RUN" not in correos[0][0]


def test_main_avisa_en_dry_run_dejando_claro_que_no_escribio(bloqueo, correos,
                                                             falso):
    falso.pendientes = 3
    assert rc.main(["anonimizar"]) == rc.EXIT_OK
    assert len(correos) == 1 and "DRY_RUN" in correos[0][0]
    assert "3 fila(s) anonimizadas" in correos[0][0]
    assert "DRY-RUN" in correos[0][1]


def test_main_con_bloqueo_ocupado_sale_en_verde_y_no_avisa(correos, monkeypatch):
    trabajo = []
    liberados = []
    monkeypatch.setattr(rc, "verificar_esquema", lambda url: None)
    monkeypatch.setattr(rc, "tomar_bloqueo", lambda cfg: "")
    monkeypatch.setattr(rc, "liberar_bloqueo",
                        lambda cfg, token: liberados.append(token))
    monkeypatch.setitem(rc.TRABAJOS_FUNCIONES, "archivar",
                        lambda cfg, res: trabajo.append(1))
    assert rc.main(["archivar"]) == rc.EXIT_OK
    # Ni una escritura, ni un correo: otra corrida tiene el bloqueo y ésta se va.
    assert trabajo == [] and correos == []
    assert liberados == [""]      # se llama con "" y `liberar_bloqueo` no hace nada


def test_reportar_sin_variables_de_correo_no_falla(monkeypatch):
    enviados = []
    monkeypatch.setattr(rc, "enviar_email",
                        lambda asunto, html, logger=None: enviados.append(asunto))
    cfg = cfg_test("archivar")
    cfg["alertas"] = False
    res = {"tablas": {"asistencias": {"pendientes": 1, "movidas": 1}},
           "respaldos": [], "movidas": 1}
    code = rc.reportar(rc.EXIT_OK, "archivar", cfg, res,
                       datetime.now(timezone.utc), "1 fila archivada")
    assert code == rc.EXIT_OK and enviados == []


def test_el_fallo_del_correo_no_cambia_el_exit_code(monkeypatch):
    enviados = []
    monkeypatch.setattr(rc, "enviar_email",
                        lambda asunto, html, logger=None: enviados.append(asunto))
    cfg = cfg_test("auditoria")
    cfg["alertas"] = True
    res = {"pendientes": 1, "purgadas": 0, "habria_purgado": 1}
    code = rc.reportar(rc.EXIT_GUARDA, "auditoria", cfg, res,
                       datetime.now(timezone.utc), "tope")
    assert code == rc.EXIT_GUARDA and len(enviados) == 1
