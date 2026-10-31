"""Pagos online: el interruptor de Mercado Pago NO se clava en `render.yaml`
(guard de FUENTE; sin red, sin BD y sin importar `app.main`).

Qué fija este archivo
---------------------
Bug 2026-10-31 (PROD): `GET /api/v1/pagos/disponibilidad` respondía
`{"habilitado": false}` con el access token cargado, así que en
`/alumno/solicitar-plan` no aparecía el botón "Pagar con Mercado Pago". La causa
no era el código: `render.yaml` declaraba

    - key: MERCADOPAGO_HABILITADO
      value: "false"
    - key: MERCADOPAGO_MODO
      value: test

y el Blueprint de Render PISA en cada sync lo que se cargue en el dashboard. O
sea: aunque se pusiera `MERCADOPAGO_HABILITADO=true` en Render, el deploy lo
volvía a `false` (y `production` volvía a `test`: con un token `APP_USR-…` MP
devuelve `sandbox_init_point` y la preferencia falla por falta de `init_point`).

La regla vigente (docs/DISENO_PAGOS_MERCADOPAGO.md §9) es que TODAS las variables
de Mercado Pago usan `sync: false`: el valor se carga a mano en el dashboard y el
YAML no guarda ninguno. Este test congela esa regla; los defaults seguros
(`HABILITADO=false`, `MODO=test`) viven en `app/core/config.py`, no en el YAML.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pagos_render_env.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
RENDER = "render.yaml"
DISENO = "docs/DISENO_PAGOS_MERCADOPAGO.md"

# `- key: X` seguido (sin comentarios de por medio) de `sync: false` o `value: ...`
_DECLARACION = re.compile(
    r"^[ \t]*- key: (?P<clave>[A-Z][A-Z0-9_]*)[ \t]*\n"
    r"(?:[ \t]*#[^\n]*\n)*"
    r"[ \t]*(?P<tipo>sync|value):[ \t]*(?P<valor>[^\n#]*)",
    re.MULTILINE,
)


def _fuente(rel: str) -> str:
    # utf-8-sig: render.yaml y varios .py del repo traen BOM en Windows.
    return (RAIZ / rel).read_text(encoding="utf-8-sig")


def _bloque_web() -> str:
    """Bloque del Web Service `box-crossfit`: desde `- type: web` hasta el próximo servicio."""
    texto = _fuente(RENDER)
    inicio = texto.index("\n  - type: web\n") + 1
    fin = texto.find("\n  - type: ", inicio)
    return texto[inicio:fin if fin != -1 else len(texto)]


def _declaraciones() -> dict[str, str]:
    """{clave: 'sync'|'value'} de las envVars del Web Service (ignora comentarios)."""
    return {m.group("clave"): m.group("tipo").strip()
            for m in _DECLARACION.finditer(_bloque_web())}


def test_ninguna_variable_de_mercadopago_lleva_valor_en_el_yaml():
    declaraciones = _declaraciones()
    mp = {k: tipo for k, tipo in declaraciones.items() if k.startswith("MERCADOPAGO_")}

    assert mp, "render.yaml dejó de declarar las variables de Mercado Pago"
    con_valor = sorted(k for k, tipo in mp.items() if tipo != "sync")
    assert not con_valor, (
        "render.yaml no puede fijar estas variables de Mercado Pago con `value:` "
        f"(el Blueprint pisa el dashboard en cada sync): {', '.join(con_valor)}. "
        "Usar `sync: false` (docs/DISENO_PAGOS_MERCADOPAGO.md §9)."
    )


def test_el_interruptor_y_el_modo_siguen_declarados_para_el_dashboard():
    """Si desaparecen del Blueprint, el dashboard no tiene dónde cargarlos y el
    botón queda apagado por default sin que nadie lo note."""
    declaraciones = _declaraciones()

    assert declaraciones.get("MERCADOPAGO_HABILITADO") == "sync", \
        "MERCADOPAGO_HABILITADO tiene que existir con `sync: false`"
    assert declaraciones.get("MERCADOPAGO_MODO") == "sync", \
        "MERCADOPAGO_MODO tiene que existir con `sync: false`"


def test_las_credenciales_nunca_se_escriben_en_el_yaml():
    """Los secretos (access token, secreto del webhook) jamás van a git."""
    declaraciones = _declaraciones()
    for clave in ("MERCADOPAGO_ACCESS_TOKEN", "MERCADOPAGO_WEBHOOK_SECRET"):
        assert declaraciones.get(clave) == "sync", f"{clave} debe ser `sync: false`"


def test_el_diseno_sigue_exigiendo_sync_false_para_las_variables():
    """El guard y la doc no pueden contradecirse (fue justo el bug)."""
    diseno = _fuente(DISENO)
    assert "`render.yaml`: `sync: false`" in diseno
    assert "nunca\n  un valor en el YAML" in diseno
