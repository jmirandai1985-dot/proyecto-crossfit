"""Integración de la retención de datos (B8) contra la base TEST.

Qué cubre (con `psql` REAL y la migración 065 aplicada)
-------------------------------------------------------
* `archivar`: un `asistencia` y un `reserva` con fecha de hace 7 años se copian a
  `*_archivo`, se respaldan en disco (`RETENCION_RESPALDO_LOCAL`, sin R2) y RECIÉN
  ahí se borran del origen. Con `DRY_RUN=1` no se toca nada.
* Si el respaldo falla (se fuerza el error), las filas quedan en el origen: el
  `DELETE` no es la primera escritura.
* `auditoria`: la guarda de volumen aborta sin borrar; con el tope alto purga sólo
  lo vencido (las filas nuevas se quedan).
* `anonimizar`: un alumno de baja hace 18 meses queda con nombre/correo/RUT
  anónimos y `anonimizado_en` sellado; repetir la corrida sobre la misma fila
  aborta (`CANDIDATOS DISTINTOS`), que es la prueba de idempotencia.
* Bloqueo por trabajo: dos tomas simultáneas ⇒ la segunda no hace nada.

Qué ESCRIBE y cómo lo limpia
----------------------------
Sólo filas propias, creadas dentro del test y borradas en el `finally` del fixture
`limpiar` (incluidas las de `*_archivo`). La base TEST puede arrastrar filas vencidas
de otros tenants: el job las archiva igual (es su trabajo) y el test exige que
**todas** las vencidas terminen en `*_archivo` y ninguna en el origen — nunca se
borra nada sin copiarlo antes. Nunca se conecta a PROD: exige `ENVIRONMENT=test` y
una URL de la rama TEST.

Se corre a mano (es opt-in: escribe en TEST):

    $env:ENVIRONMENT='test'; $env:RETENCION_INTEGRACION='1'
    py -3.12 -m pytest tests/test_retencion_integracion.py -q --noconftest
"""
import os
import re
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

if os.getenv("RETENCION_INTEGRACION") != "1":
    pytest.skip("integración de retención: exporta RETENCION_INTEGRACION=1 "
                "(escribe en la base TEST)", allow_module_level=True)
if os.getenv("ENVIRONMENT") != "test":
    pytest.skip("integración de retención: exige ENVIRONMENT=test",
                allow_module_level=True)

from maintenance import retencion_cloud as ret  # noqa: E402

PEPPER = "pepper-de-test-retencion-0123456789abcdef"
ANIO_ARCHIVO = "7 years"
ANIO_AUDITORIA = "3 years"
MESES_BAJA = "18 months"


@pytest.fixture(scope="module")
def url():
    """URL DIRECTA de la rama TEST (nunca PROD: se valida con el espejo del config)."""
    from app.core.config import is_test_db_url, settings

    candidata = settings.DIRECT_URL or settings.DATABASE_URL
    if not is_test_db_url(candidata):
        pytest.fail("la URL configurada no es TEST: aborto (exporta ENVIRONMENT=test)")
    motivo = ret.validar_url(candidata, "test")
    if motivo:
        pytest.fail(f"la URL de TEST no pasa la guarda del job: {motivo}")
    return candidata


@pytest.fixture
def cfg(url, tmp_path, monkeypatch):
    """`cargar_config()` de verdad, con escritura habilitada y respaldo local."""
    for var in ret.VARS_R2:                     # el respaldo del test es el disco
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("RETENCION_PREFIJO", raising=False)

    def _cfg(trabajo: str, **extra) -> dict:
        env = {
            "RETENCION_DB_URL": url,
            "ENVIRONMENT": "test",
            "DRY_RUN": "0",
            "RETENCION_TEST_OK": "1",           # guarda anti-PROD: escribir en TEST
            "RETENCION_RESPALDO_LOCAL": str(tmp_path / "respaldos"),
            "ANONIMIZACION_PEPPER": PEPPER,
            "TAM_LOTE": "100",
            "MAX_ARCHIVAR": "1000",
            "MAX_BORRAR_AUDITORIA": "1000",
            "MAX_ANONIMIZAR": "1000",
        }
        env.update({k: str(v) for k, v in extra.items()})
        return ret.cargar_config(trabajo, env)

    return _cfg


@pytest.fixture
def limpiar(url):
    """Registro de (tabla, ids) a borrar pase lo que pase (siempre al final)."""
    pendientes: list = []
    yield pendientes
    for tabla, ids in reversed(pendientes):
        if ids:
            ret.script(url, f"DELETE FROM {tabla} WHERE id = ANY({ret.lista_ids(ids)});\n")


def _base(url):
    """Un `tenant_id`/`usuario_id`/`clase_id` que existan de verdad (FKs)."""
    fila = ret.consulta(url, (
        "SELECT tenant_id || '|' || alumno_id || '|' || clase_id FROM (\n"
        "  SELECT r.tenant_id, r.alumno_id, r.clase_id FROM reservas r\n"
        "   ORDER BY r.id LIMIT 1) x;\n")).split("|")
    if len(fila) != 3 or not all(f.isdigit() for f in fila):
        pytest.skip("TEST no tiene reservas: no hay ids base para sembrar filas")
    return tuple(int(f) for f in fila)


def _sembrar_asistencias(url, limpiar, tenant, usuario, cuantas=1):
    valores = ", ".join(f"({tenant}, {usuario}, CURRENT_DATE - INTERVAL "
                        f"'{ANIO_ARCHIVO}')" for _ in range(cuantas))
    ids = ret.filas_a_ids(ret.consulta(
        url, "INSERT INTO asistencias (tenant_id, usuario_id, fecha) VALUES "
        f"{valores} RETURNING id;\n"))
    limpiar.append(("asistencias", ids))
    limpiar.append(("asistencias_archivo", ids))
    return ids


def _sembrar_reservas(url, limpiar, tenant, alumno, clase, cuantas=1):
    # `estado='cancelada'` a propósito: el índice único parcial
    # `uq_reservas_clase_alumno_viva` excluye las canceladas, así que sembrar no
    # puede chocar con una reserva viva del mismo par (clase, alumno).
    valores = ", ".join(f"({tenant}, {clase}, {alumno}, now() - INTERVAL "
                        f"'{ANIO_ARCHIVO}', 'cancelada')" for _ in range(cuantas))
    ids = ret.filas_a_ids(ret.consulta(
        url, "INSERT INTO reservas (tenant_id, clase_id, alumno_id, "
        f"fecha_reserva, estado) VALUES {valores} RETURNING id;\n"))
    limpiar.append(("reservas", ids))
    limpiar.append(("reservas_archivo", ids))
    return ids


def _sembrar_auditoria(url, limpiar, tenant, cuantas=1):
    valores = ", ".join(f"({tenant}, 'test_integracion', 'retencion', "
                        f"now() - INTERVAL '{ANIO_AUDITORIA}')"
                        for _ in range(cuantas))
    ids = ret.filas_a_ids(ret.consulta(
        url, "INSERT INTO auditoria (tenant_id, accion, entidad, fecha) VALUES "
        f"{valores} RETURNING id;\n"))
    limpiar.append(("auditoria", ids))
    return ids


def _sembrar_alumno_baja(url, limpiar, tenant, meses=MESES_BAJA):
    sufijo = uuid.uuid4().hex[:8]
    fila = ret.consulta(url, (
        "INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, "
        "rol, telefono, fecha_baja) VALUES "
        f"({tenant}, '99.999.99{sufijo[:1]}-9', 'Retencion Prueba {sufijo}', "
        f"'retencion.{sufijo}@example.invalid', 'no-es-un-hash', 'alumno', "
        f"'+56900000000', now() - INTERVAL '{meses}') RETURNING id || '|' || rut;\n"))
    id_usuario, rut = fila.split("|")
    limpiar.append(("usuarios", [int(id_usuario)]))
    return int(id_usuario), rut


def _contar(url, sql):
    return ret.consulta_entero(url, sql + "\n")


def _vencidas(url, cfg_dict, tabla, limite=1000):
    """Ids que el run va a mover: los sembrados por el test y los que ya hubiera."""
    return ret.filas_a_ids(ret.consulta(url, ret.sql_lote(tabla, cfg_dict, limite)))


# ── archivar ───────────────────────────────────────────────────────────────
def test_archivar_dry_run_no_toca_nada(url, cfg, limpiar):
    tenant, alumno, clase = _base(url)
    asis = _sembrar_asistencias(url, limpiar, tenant, alumno)
    resv = _sembrar_reservas(url, limpiar, tenant, alumno, clase)
    c = cfg("archivar", DRY_RUN="1")

    resultado = ret.job_archivar(c)

    assert resultado["movidas"] == 0
    det = resultado["tablas"]["asistencias"]
    # TEST puede tener filas vencidas de otros tenants: se compara contra el
    # total pendiente del run, no contra las filas sembradas.
    assert det["habria_movido"] == det["pendientes"] >= len(asis)
    assert resultado["tablas"]["reservas"]["habria_movido"] >= len(resv)
    assert _contar(url, "SELECT count(*) FROM asistencias WHERE id = ANY("
                        f"{ret.lista_ids(asis)})") == len(asis)
    assert _contar(url, "SELECT count(*) FROM asistencias_archivo WHERE id = ANY("
                        f"{ret.lista_ids(asis)})") == 0
    assert _contar(url, "SELECT count(*) FROM reservas WHERE id = ANY("
                        f"{ret.lista_ids(resv)})") == len(resv)
    assert not list(Path(c["respaldo_local"]).glob("*.csv.gz")), \
        "DRY_RUN no puede dejar respaldos"


def test_archivar_mueve_respalda_y_borra_del_origen(url, cfg, limpiar):
    tenant, alumno, clase = _base(url)
    asis = _sembrar_asistencias(url, limpiar, tenant, alumno)
    resv = _sembrar_reservas(url, limpiar, tenant, alumno, clase)
    c = cfg("archivar")
    # Todas las filas vencidas (las del test y las que TEST ya tuviera): después
    # del run tienen que estar TODAS en el archivo y ninguna en el origen. No se
    # usa `origen + archivo` porque TEST puede tener ids ya archivados de antes
    # y el `ON CONFLICT DO NOTHING` de la copia no los duplica.
    pend = {t: _vencidas(url, c, t) for t in ("asistencias", "reservas")}
    assert set(asis) <= set(pend["asistencias"])
    assert set(resv) <= set(pend["reservas"])

    resultado = ret.job_archivar(c)

    assert resultado["tablas"]["asistencias"]["movidas"] >= len(asis)
    assert resultado["tablas"]["reservas"]["movidas"] >= len(resv)
    assert resultado["movidas"] == (resultado["tablas"]["asistencias"]["movidas"]
                                    + resultado["tablas"]["reservas"]["movidas"])
    for tabla in ("asistencias", "reservas"):
        archivo = ret.TABLAS_ARCHIVO[tabla]["archivo"]
        ids = ret.lista_ids(pend[tabla])
        assert _contar(url, f"SELECT count(*) FROM {tabla} WHERE id = ANY({ids})") == 0, \
            f"{tabla}: el origen tiene que quedar vacío"
        assert _contar(url, f"SELECT count(*) FROM {archivo} WHERE id = ANY({ids})") \
            == len(pend[tabla]), f"{tabla}: ninguna fila vencida puede perderse"
    # Además, fila por fila lo que sembró el test: origen vacío, archivo con
    # `archivado_en` sellado.
    for tabla, ids in (("asistencias", asis), ("reservas", resv)):
        archivo = ret.TABLAS_ARCHIVO[tabla]["archivo"]
        assert _contar(url, f"SELECT count(*) FROM {tabla} WHERE id = ANY("
                            f"{ret.lista_ids(ids)})") == 0
        assert _contar(url, f"SELECT count(*) FROM {archivo} WHERE id = ANY("
                            f"{ret.lista_ids(ids)})") == len(ids)
        # `archivado_en` se sella al copiar
        assert _contar(url, f"SELECT count(*) FROM {archivo} WHERE archivado_en "
                            f"IS NOT NULL AND id = ANY({ret.lista_ids(ids)})") == len(ids)
    # 3) el respaldo existió ANTES del borrado: un .csv.gz por tabla
    respaldos = sorted(Path(c["respaldo_local"]).glob("*.csv.gz"))
    nombres = " ".join(p.name for p in respaldos)
    assert "asistencias" in nombres and "reservas" in nombres
    assert len(resultado["respaldos"]) == 2


def test_archivar_sin_respaldo_no_borra(url, cfg, limpiar, monkeypatch):
    """Si el respaldo falla DESPUÉS de copiar, el origen queda intacto (exit 4)."""
    tenant, alumno, clase = _base(url)
    asis = _sembrar_asistencias(url, limpiar, tenant, alumno)
    resv = _sembrar_reservas(url, limpiar, tenant, alumno, clase)
    c = cfg("archivar")

    def boom(*_a, **_k):
        raise ret.RespaldoError("falla simulada del respaldo (R2 caído)")

    monkeypatch.setattr(ret, "exportar_csv", boom)
    with pytest.raises(ret.RespaldoError):
        ret.job_archivar(c)

    assert _contar(url, "SELECT count(*) FROM asistencias WHERE id = ANY("
                        f"{ret.lista_ids(asis)})") == len(asis)
    assert _contar(url, "SELECT count(*) FROM reservas WHERE id = ANY("
                        f"{ret.lista_ids(resv)})") == len(resv)


# ── auditoria ──────────────────────────────────────────────────────────────
def test_auditoria_guarda_de_volumen_no_borra(url, cfg, limpiar):
    tenant, _alumno, _clase = _base(url)
    ids = _sembrar_auditoria(url, limpiar, tenant, cuantas=2)
    c = cfg("auditoria", MAX_BORRAR_AUDITORIA="1")

    with pytest.raises(ret.GuardaError):
        ret.job_auditoria(c)

    assert _contar(url, "SELECT count(*) FROM auditoria WHERE id = ANY("
                        f"{ret.lista_ids(ids)})") == len(ids)


def test_auditoria_purga_solo_lo_vencido(url, cfg, limpiar):
    tenant, _alumno, _clase = _base(url)
    viejas = _sembrar_auditoria(url, limpiar, tenant, cuantas=2)
    nueva = ret.filas_a_ids(ret.consulta(
        url, "INSERT INTO auditoria (tenant_id, accion, entidad, fecha) VALUES "
             f"({tenant}, 'test_integracion', 'retencion', now()) RETURNING id;\n"))
    limpiar.append(("auditoria", nueva))
    c = cfg("auditoria")

    resultado = ret.job_auditoria(c)

    # La purga arrastra lo de otros tenants (es su cometido); lo que importa es
    # que borre EXACTAMENTE lo vencido y respete lo nuevo.
    assert resultado["purgadas"] == resultado["pendientes"]
    assert _contar(url, "SELECT count(*) FROM auditoria WHERE id = ANY("
                        f"{ret.lista_ids(viejas)})") == 0
    assert _contar(url, "SELECT count(*) FROM auditoria WHERE id = ANY("
                        f"{ret.lista_ids(nueva)})") == 1


# ── anonimizar ─────────────────────────────────────────────────────────────
def test_anonimizar_baja_de_18_meses(url, cfg, limpiar):
    tenant, _alumno, _clase = _base(url)
    id_usuario, rut = _sembrar_alumno_baja(url, limpiar, tenant)
    c = cfg("anonimizar")
    if _contar(url, ret.sql_pendientes_anonimizar(c)) != 1:
        pytest.skip("TEST ya tenía bajas de más de 12 meses: no se anonimizan las ajenas")

    resultado = ret.job_anonimizar(c)

    assert resultado["anonimizadas"] == 1
    fila = ret.consulta(url, (
        "SELECT nombre || '|' || correo || '|' || coalesce(telefono, '') || '|' "
        "|| rut || '|' || (anonimizado_en IS NOT NULL)::text FROM usuarios "
        f"WHERE id = {id_usuario};\n"))
    nombre, correo, telefono, rut_nuevo, sellado = fila.split("|")
    esperado = ret.rut_anonimo(PEPPER, id_usuario, rut)
    assert nombre == f"Alumno anonimizado {id_usuario}"
    assert correo == f"anonimo+{id_usuario}@anonimizado.invalid"
    assert telefono == ""
    assert rut_nuevo == esperado and re.fullmatch(r"ANON[0-9a-z]{8}", rut_nuevo)
    # El sufijo es un hash: puede repetir un dígito del RUT original por azar
    # (~20 % de las corridas con un RUT como `99.999.99x-9`), así que se compara
    # contra el RUT completo. Exigir "ningún dígito suelto del original" convertía
    # este test en intermitente.
    assert rut_nuevo != rut and rut not in rut_nuevo
    assert not re.fullmatch(r"\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]", rut_nuevo)
    assert sellado == "true"


def test_anonimizar_no_repite_la_misma_fila(url, cfg, limpiar):
    """Repetir el `UPDATE` sobre una fila ya anonimizada aborta (idempotencia)."""
    tenant, _alumno, _clase = _base(url)
    id_usuario, rut = _sembrar_alumno_baja(url, limpiar, tenant)
    c = cfg("anonimizar")
    if _contar(url, ret.sql_pendientes_anonimizar(c)) != 1:
        pytest.skip("TEST ya tenía bajas de más de 12 meses: no se anonimizan las ajenas")

    pares = [(id_usuario, ret.rut_anonimo(PEPPER, id_usuario, rut))]
    ret.script_escritura(url, ret.script_anonimizar(c, pares), "anonimización de prueba")

    with pytest.raises(ret.EscrituraError):
        ret.script_escritura(url, ret.script_anonimizar(c, pares),
                             "segunda anonimización (debe abortar)")


# ── bloqueo por trabajo ────────────────────────────────────────────────────
def test_bloqueo_no_deja_dos_corridas_del_mismo_trabajo(url, cfg):
    c = cfg("archivar")
    primero = ret.tomar_bloqueo(c)
    try:
        assert primero, "la primera toma del bloqueo tiene que devolver token"
        assert ret.tomar_bloqueo(c) == "", "con el bloqueo vigente no se toma otra vez"
        assert _contar(url, "SELECT count(*) FROM retencion_bloqueos WHERE job = "
                            "'archivar'") == 1
    finally:
        ret.liberar_bloqueo(c, primero)
    assert ret.tomar_bloqueo(c) != "", "liberado el bloqueo, se puede volver a tomar"
    ret.liberar_bloqueo(c, "")
    ret.script(url, "DELETE FROM retencion_bloqueos WHERE job = 'archivar';\n")
    assert _contar(url, "SELECT count(*) FROM retencion_bloqueos") == 0


# ── entrypoint ─────────────────────────────────────────────────────────────
def test_main_dry_run_sale_cero(url, tmp_path, monkeypatch, limpiar):
    """El camino completo (`python -m maintenance.retencion_cloud auditoria`)."""
    tenant, _alumno, _clase = _base(url)
    ids = _sembrar_auditoria(url, limpiar, tenant, cuantas=1)
    for var in ret.VARS_R2:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("RETENCION_DB_URL", url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DRY_RUN", "1")          # no escribe
    monkeypatch.setenv("RETENCION_RESPALDO_LOCAL", str(tmp_path / "respaldos"))
    monkeypatch.delenv("RETENCION_TEST_OK", raising=False)
    monkeypatch.delenv("ALERT_EMAIL", raising=False)

    assert ret.main(["auditoria"]) == ret.EXIT_OK
    assert _contar(url, "SELECT count(*) FROM auditoria WHERE id = ANY("
                        f"{ret.lista_ids(ids)})") == 1, "DRY_RUN no puede borrar"

    assert ret.main([]) == ret.EXIT_CONFIG
    assert ret.main(["archivar", "auditoria"]) == ret.EXIT_CONFIG

