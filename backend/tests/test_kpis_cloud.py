"""Tests del Cron Job de KPIs y ML (`maintenance/kpis_cloud.py`): sin red y sin correos.

El job reemplaza 4 workflows de n8n [PROD] y lo que importa fijar es:
  · el CALENDARIO (función pura `plan_del_dia`): día cualquiera, día 1, día 15, último
    del mes (incluido febrero) y el orden de las llamadas (entrenar ANTES de predecir);
  · la config: sin URL ni clave no se llama a nada (exit 2); http contra un host
    remoto se rechaza (la clave de PROD no viaja en claro); los enteros tienen rango;
  · los reintentos: 5xx/timeout se reintentan con espera acotada, CUALQUIER 4xx no;
  · el correo: sale SÓLO si hay algo que revisar (fallo o reentrenamiento `parcial`),
    con asunto `[ALERTA]`, y ni el log ni el correo filtran la clave;
  · `DRY_RUN=1` (default de la imagen): imprime el plan y NO llama a nada.

`_http` (el único lugar que abre una conexión) y `DORMIR` (la espera entre reintentos)
están doblados: ningún test toca la red ni duerme. `enviar_email` está doblado: no sale
ningún correo real.

Se corre con:
    py -3.12 -m pytest tests/test_kpis_cloud.py -q --noconftest
"""
import ast
import io
import sys
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from maintenance import kpis_cloud as kp  # noqa: E402

CLAVE_FALSA = "SECRETO_FAKE_no_real_de_n8n"
API = "https://box-crossfit.onrender.com"
GMAIL_USER = "urban.training.box.2026@gmail.com"
APP_FAKE = "app-fake-no-real"
OK_DIARIO = '{"status": "ok", "accion": "daily_kpis upsert", "fecha": "2026-09-04"}'
OK_MENSUAL = '{"status": "ok", "year": 2026, "month": 9, "meses_calculados": 1}'
OK_ML = '{"status": "ok", "churn": {"status": "ok"}, "forecast": {"status": "ok"}}'
PARCIAL_ML = '{"status": "parcial", "churn": {"status": "ok"}, "forecast": {"status": "error"}}'


def _http_error(code: int, cuerpo: str = '{"detail": "boom"}') -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/api/v1/y", code, "boom", {}, io.BytesIO(
        cuerpo.encode("utf-8")))


# ── Doble de `_http`: la red NO se toca ───────────────────────────────────────
def doble_http(monkeypatch, respuestas=None, por_defecto=(200, OK_DIARIO)):
    """Doble de `_http(req, timeout)`.

    `respuestas`: lista (una entrada por llamada, en orden) o callable(req). Cada
    entrada es `(status, cuerpo)` o una excepción a levantar (timeout, HTTPError...).
    Devuelve la lista de pedidos vistos (url, método, headers, timeout).
    """
    visto = []

    def falso(req, timeout):
        visto.append({
            "url": req.full_url,
            "metodo": req.get_method(),
            "headers": {k.lower(): v for k, v in req.header_items()},
            "timeout": timeout,
        })
        i = len(visto) - 1
        entrada = respuestas[i] if respuestas and i < len(respuestas) else por_defecto
        if callable(entrada) and not isinstance(entrada, Exception):
            entrada = entrada(req)
        if isinstance(entrada, Exception):
            raise entrada
        return entrada

    monkeypatch.setattr(kp, "_http", falso)
    return visto


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Entorno válido mínimo, todo por env (el módulo no lee ningún `.env`)."""
    for k, v in (("KPIS_API_URL", API),
                 ("N8N_API_KEY", CLAVE_FALSA),
                 ("DRY_RUN", "0"),
                 ("TZ", "America/Santiago"),
                 ("GMAIL_SMTP_USER", GMAIL_USER),
                 ("GMAIL_SMTP_APP_PASSWORD", APP_FAKE),
                 ("ALERT_EMAIL", "alertas@example.com")):
        monkeypatch.setenv(k, v)
    for k in ("TIMEOUT_SEG", "REINTENTOS", "ESPERA_REINTENTO_SEG", "DIA_ML"):
        monkeypatch.delenv(k, raising=False)
    # Sin dormir de verdad y sin mandar correos.
    monkeypatch.setattr(kp, "DORMIR", lambda _s: None)
    yield


@pytest.fixture
def mails(monkeypatch):
    capturados = []
    monkeypatch.setattr(
        kp, "enviar_email",
        lambda asunto, html, *a, **kw: capturados.append((asunto, html)) or True)
    return capturados


@pytest.fixture
def hoy(monkeypatch):
    """Fija el 'hoy' de Chile (el job lo calcula con `hoy_local`)."""
    def _fijar(d: date):
        monkeypatch.setattr(kp, "hoy_local", lambda *a, **k: d)
    return _fijar


def _texto(mail) -> str:
    return mail[0] + "\n" + mail[1]


def _rutas(visto) -> list:
    """Sólo la ruta+query de cada pedido (para chequear orden sin ruido)."""
    return [v["url"].replace(API, "") for v in visto]


# ── Configuración: sin config válida NO se llama a nada ───────────────────────
def test_a_sin_url_exit_2_sin_llamar_y_con_alerta(monkeypatch, mails, hoy):
    monkeypatch.delenv("KPIS_API_URL", raising=False)
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_CONFIG
    assert visto == []                       # ni un pedido
    assert len(mails) == 1                   # un job que no corre no es silencioso
    assert mails[0][0] == "[ALERTA] KPIs y ML PROD: configuración inválida"
    assert "KPIS_API_URL" in _texto(mails[0])
    assert CLAVE_FALSA not in _texto(mails[0])


def test_b_sin_clave_exit_2_sin_llamar(monkeypatch, mails, hoy):
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_CONFIG
    assert visto == []
    assert "N8N_API_KEY" in _texto(mails[0])


def test_c_url_http_a_host_remoto_exit_2(monkeypatch, mails, hoy):
    """La clave de PROD no puede viajar por http sin TLS."""
    monkeypatch.setenv("KPIS_API_URL", "http://box-crossfit.onrender.com")
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_CONFIG
    assert visto == []
    assert "sin cifrar" in _texto(mails[0])


def test_c2_la_url_localhost_por_http_si_se_permite():
    """El stack de TEST corre en la laptop: ahí http es válido (y sólo ahí)."""
    assert kp.validar_url_api("http://localhost:8001/") == "http://localhost:8001"
    assert kp.validar_url_api("https://box-crossfit.onrender.com/") == API


@pytest.mark.parametrize("valor", ["0", "1", "29", "99", "abc"])
def test_d_dia_ml_invalido_exit_2_nunca_llama(monkeypatch, mails, hoy, valor):
    monkeypatch.setenv("DIA_ML", valor)
    hoy(date(2026, 9, 15))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_CONFIG
    assert visto == []
    assert "DIA_ML" in _texto(mails[0])


# ── El plan del día (función pura): el calendario del job ─────────────────────
def test_e_dia_cualquiera_kpis_diarios_y_predicciones(monkeypatch, mails, capsys, hoy):
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_OK
    # Las predicciones se refrescan TODOS los días (alimentan Fidelización), no sólo
    # el día 1: un día corriente son 2 llamadas: daily + predictions.
    assert _rutas(visto) == [
        "/api/v1/kpis/populate/daily?fecha=2026-09-04",
        "/api/v1/kpis/populate/predictions",
    ]
    assert visto[0]["metodo"] == "POST"
    assert visto[0]["headers"]["x-n8n-api-key"] == CLAVE_FALSA
    assert visto[0]["headers"]["accept"] == "application/json"
    assert mails == []                       # run verde: sin correo
    assert "sin correo" in capsys.readouterr().out


def test_f_dia_1_agrega_el_mes_cerrado(monkeypatch, mails, hoy):
    hoy(date(2026, 10, 1))
    visto = doble_http(monkeypatch, por_defecto=(200, OK_MENSUAL))

    assert kp.main() == kp.EXIT_OK
    assert _rutas(visto) == [
        "/api/v1/kpis/populate/daily?fecha=2026-09-30",
        "/api/v1/kpis/populate/monthly?year=2026&month=9",
        "/api/v1/kpis/populate/predictions",
    ]
    assert mails == []


def test_g_dia_15_reentrena_segmenta_y_predice_en_ese_orden(monkeypatch, mails, hoy):
    hoy(date(2026, 9, 15))
    visto = doble_http(monkeypatch, por_defecto=(200, OK_ML))

    assert kp.main() == kp.EXIT_OK
    assert _rutas(visto) == [
        "/api/v1/kpis/populate/daily?fecha=2026-09-14",
        "/api/v1/ml/reentrenar",
        "/api/v1/segmentacion/reentrenar",
        "/api/v1/kpis/populate/predictions",
    ]
    assert mails == []


@pytest.mark.parametrize("dia", [date(2026, 9, 30), date(2026, 12, 31),
                                 date(2026, 2, 28), date(2026, 4, 30)])
def test_h_el_ultimo_dia_del_mes_tambien_reentrena(monkeypatch, mails, hoy, dia):
    hoy(dia)
    visto = doble_http(monkeypatch, por_defecto=(200, OK_ML))

    assert kp.main() == kp.EXIT_OK
    assert _rutas(visto)[1:] == [
        "/api/v1/ml/reentrenar",
        "/api/v1/segmentacion/reentrenar",
        "/api/v1/kpis/populate/predictions",
    ]


def test_h2_el_dia_1_no_reentrena_y_el_15_no_toca_el_mes():
    """El "calendario" es excluyente: ML sólo en 15/último, mensual sólo el día 1."""
    rutas_1 = [p["ruta"] for p in kp.plan_del_dia(date(2026, 10, 1))]
    rutas_15 = [p["ruta"] for p in kp.plan_del_dia(date(2026, 10, 15))]
    rutas_ultimo = [p["ruta"] for p in kp.plan_del_dia(date(2026, 10, 31))]

    assert kp.RUTA_ML not in rutas_1 and kp.RUTA_SEGMENTACION not in rutas_1
    assert kp.RUTA_MONTHLY not in rutas_15 and kp.RUTA_MONTHLY not in rutas_ultimo
    assert kp.RUTA_ML in rutas_15 and kp.RUTA_ML in rutas_ultimo
    assert kp.RUTA_SEGMENTACION in rutas_15


def test_h3_cada_paso_explica_por_que():
    for paso in kp.plan_del_dia(date(2026, 9, 15)):
        assert set(paso) == {"nombre", "metodo", "ruta", "params", "porque"}
        assert paso["porque"] and paso["metodo"] == "POST"
        assert paso["ruta"].startswith("/api/v1/")


def test_h4_hoy_local_usa_el_calendario_de_chile():
    """02:30 UTC del 30/09 en Chile (UTC-3 en septiembre) sigue siendo el 29."""
    assert kp.hoy_local(datetime(2026, 9, 30, 2, 30, tzinfo=timezone.utc)) == date(2026, 9, 29)
    assert kp.hoy_local(datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)) == date(2026, 9, 30)


# ── Reintentos: 5xx sí (y acotados), 4xx no ──────────────────────────────────
def test_i_un_5xx_se_reintenta_hasta_lograr(monkeypatch, mails, capsys, hoy):
    monkeypatch.setenv("REINTENTOS", "2")
    monkeypatch.setenv("ESPERA_REINTENTO_SEG", "5")
    esperas = []
    monkeypatch.setattr(kp, "DORMIR", esperas.append)
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch, [(500, "{}"), _http_error(503), (200, OK_DIARIO)])

    assert kp.main() == kp.EXIT_OK
    assert len(visto) == 4                    # daily: 1 intento + 2 reintentos; predictions: 1
    assert esperas == [5, 10]                 # la espera se duplica y está acotada
    assert mails == []
    assert "intento 1/3" in capsys.readouterr().out


def test_i2_un_5xx_sostenido_sale_3_con_alerta(monkeypatch, mails, hoy):
    monkeypatch.setenv("REINTENTOS", "1")
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch, por_defecto=(502, '{"detail": "bad gateway"}'))

    assert kp.main() == kp.EXIT_LLAMADA
    assert len(visto) == 4                    # cada llamada se acota: no reintenta para siempre
    assert mails[0][0] == "[ALERTA] KPIs y ML PROD: llamadas con error"
    assert "HTTP 502" in _texto(mails[0]) and "KPIs diarios" in _texto(mails[0])


def test_j_un_4xx_no_se_reintenta(monkeypatch, mails, capsys, hoy):
    """401 = clave mal puesta: reintentar no arregla nada, sólo demora la alerta."""
    monkeypatch.setenv("REINTENTOS", "3")
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch, por_defecto=_http_error(401, '{"detail": "no autorizado"}'))

    assert kp.main() == kp.EXIT_LLAMADA
    assert len(visto) == 2                    # daily + predictions: 4xx sin reintento cada una
    assert "4xx: sin reintento" in capsys.readouterr().out
    assert "HTTP 401" in _texto(mails[0])


def test_i3_un_timeout_de_red_se_reintenta(monkeypatch, mails, hoy):
    monkeypatch.setenv("REINTENTOS", "1")
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch, [TimeoutError("timed out"), (200, OK_DIARIO)])

    assert kp.main() == kp.EXIT_OK
    assert len(visto) == 3
    assert mails == []


# ── Un fallo no aborta el resto (y el correo lo cuenta completo) ─────────────
def test_k_un_fallo_no_aborta_las_otras_llamadas(monkeypatch, mails, hoy):
    hoy(date(2026, 10, 1))
    monkeypatch.setenv("REINTENTOS", "0")
    visto = doble_http(monkeypatch, [
        (200, OK_DIARIO),
        _http_error(500, '{"detail": "boom"}'),      # el mensual falla
        (200, '{"status": "ok", "proyecciones": []}'),
    ])

    assert kp.main() == kp.EXIT_LLAMADA
    assert len(visto) == 3                    # las 3 se intentaron igual
    texto = _texto(mails[0])
    assert "KPIs mensuales" in texto and "FALLA" in texto and "HTTP 500" in texto


def test_l_un_reentrenamiento_parcial_deja_el_run_rojo(monkeypatch, mails, hoy):
    """HTTP 200 con `status: parcial` = un modelo sin entrenar: en n8n pasaba verde."""
    hoy(date(2026, 9, 15))
    visto = doble_http(monkeypatch, [
        (200, OK_DIARIO),
        (200, PARCIAL_ML),
        (200, '{"status": "ok"}'),
        (200, '{"status": "ok"}'),
    ])

    assert kp.main() == kp.EXIT_PARCIAL
    assert len(visto) == 4                    # se corre TODO igual
    assert mails[0][0] == "[ALERTA] KPIs y ML PROD: reentrenamiento parcial"
    assert "parcial" in _texto(mails[0])


def test_m_ni_el_log_ni_el_correo_filtran_la_clave(monkeypatch, mails, capsys, hoy):
    """La clave viaja en un header: un error de red que la incluya NO puede salir."""
    hoy(date(2026, 9, 5))
    doble_http(monkeypatch, por_defecto=RuntimeError(
        f"TLS handshake falló con X-N8N-API-Key: {CLAVE_FALSA}"))

    assert kp.main() == kp.EXIT_LLAMADA
    salida = capsys.readouterr().out
    assert CLAVE_FALSA not in salida and "***" in salida
    assert CLAVE_FALSA not in _texto(mails[0])


def test_m2_un_500_que_devuelve_la_clave_en_el_cuerpo_tambien_se_tacha(monkeypatch, mails, hoy):
    hoy(date(2026, 9, 5))
    monkeypatch.setenv("REINTENTOS", "0")
    doble_http(monkeypatch, por_defecto=_http_error(500, f"key={CLAVE_FALSA}"))

    assert kp.main() == kp.EXIT_LLAMADA
    assert CLAVE_FALSA not in _texto(mails[0])


# ── DRY_RUN (default de la imagen) ───────────────────────────────────────────
def test_n_dry_run_no_llama_a_nada_y_muestra_el_plan(monkeypatch, mails, capsys, hoy):
    monkeypatch.delenv("DRY_RUN", raising=False)   # default = 1
    hoy(date(2026, 9, 15))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_OK
    assert visto == []                        # NINGUNA llamada
    assert mails == []
    salida = capsys.readouterr().out
    assert "DRY_RUN=1" in salida and "NO se llamó a ningún endpoint" in salida
    assert "/api/v1/ml/reentrenar" in salida  # el plan del día 15 completo


def test_n2_dry_run_se_apaga_con_cero(monkeypatch, mails, hoy):
    monkeypatch.setenv("DRY_RUN", "0")
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_OK
    assert len(visto) == 2


# ── Guards de config y del contrato con `alertas` ────────────────────────────
def test_o_los_getenv_viven_solo_en_los_lectores_de_config():
    """Todos los `os.getenv` del módulo están en los lectores de `leer_config`."""
    lectores = {"_texto", "dry_run_activo"}
    arbol = ast.parse(Path(kp.__file__).read_text(encoding="utf-8"))
    rangos = [(n.lineno, n.end_lineno) for n in ast.walk(arbol)
              if isinstance(n, ast.FunctionDef) and n.name in lectores]
    assert len(rangos) == len(lectores)       # los 2 lectores siguen existiendo

    sueltos = [n.lineno for n in ast.walk(arbol)
               if isinstance(n, ast.Attribute) and n.attr in ("getenv", "environ")
               and not any(ini <= n.lineno <= fin for ini, fin in rangos)]
    assert sueltos == [], f"hay os.getenv/os.environ fuera de los lectores: {sueltos}"


def test_p_el_modulo_no_importa_la_app():
    """El Cron Job no arrastra FastAPI/SQLAlchemy (Dockerfile.cron no copia `app/`).

    Se mira el AST de los imports (no el texto: la docstring NOMBRA esas librerías
    justamente para explicar que no se usan).
    """
    arbol = ast.parse(Path(kp.__file__).read_text(encoding="utf-8"))
    modulos = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            modulos.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            modulos.add(n.module.split(".")[0])
    assert "app" not in modulos
    assert not {"sqlalchemy", "fastapi", "pydantic", "boto3"} & modulos
    assert {"maintenance.alertas", "maintenance.backup_cloud"} <= {
        n.module for n in ast.walk(arbol)
        if isinstance(n, ast.ImportFrom) and n.module}


def test_q_las_variables_del_correo_son_las_de_alertas():
    """El correo sale por `maintenance/alertas.py`: las 3 variables son las suyas."""
    assert kp.VARS_ALERTA == ("GMAIL_SMTP_USER", "GMAIL_SMTP_APP_PASSWORD", "ALERT_EMAIL")


def test_r_sin_las_variables_de_correo_el_run_avisa_pero_corre(monkeypatch, capsys, hoy):
    for v in kp.VARS_ALERTA:
        monkeypatch.delenv(v, raising=False)
    hoy(date(2026, 9, 5))
    visto = doble_http(monkeypatch)

    assert kp.main() == kp.EXIT_OK
    assert len(visto) == 2
    assert "AVISO (config)" in capsys.readouterr().out


