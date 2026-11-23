"""Guard de destinatarios de alertas automáticas (sin BD).

Todas las consultas de candidatos deben excluir cuentas de prueba y estados
sin MRR. El dedupe por alumno/tipo/día ya vive en `_ya_enviado` y
`_reclamar_envio`; este test fija que no se pierda.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_alertas_excluyen_cuentas_prueba_y_estados_sin_mrr():
    texto = (RAIZ / "app/services/alertas_email_service.py").read_text(encoding="utf-8")
    for funcion in (
        "def enviar_alertas_renovacion",
        "def enviar_alertas_inactividad",
        "def enviar_alertas_urgencia",
        "def enviar_alertas_ultimo_credito",
        "def enviar_alertas_sin_creditos",
    ):
        bloque = texto.split(funcion, 1)[1].split("\ndef ", 1)[0]
        assert 'AND {sql_usuario_real("u")}' in bloque, funcion
        assert "ESTADOS_USUARIO_SIN_MRR" in bloque, funcion


def test_alertas_mantienen_dedupe_por_alumno_tipo_y_dia():
    texto = (RAIZ / "app/services/alertas_email_service.py").read_text(encoding="utf-8")
    assert "def _ya_enviado" in texto
    assert "def _reclamar_envio" in texto
    assert "notificaciones_enviadas" in texto
    assert "estado = 'enviado'" in texto
