"""Recordatorio MANUAL de retiro del Bazar ("Pedidos listos para entrega", <768px).

Tests AISLADOS (sin red, sin base de datos): la REGLA y los cableados, no la consulta.

  A. Filtro "validado sin retirar" — reusa `codigos_retiro.motivo_no_entregable`
     (la misma regla del mesón): pagado/entregado no se recuerda, pendiente tampoco
     (todavía no se validó) y un validado SIN código no puede prometer un retiro.
  B. El correo manual NO toca la campana automática `pedido_validado`: no llama
     `notificar_alumno`, usa un `tipo` propio (`pedido_recordatorio_manual`) que no
     aparece entre los tipos del scheduler, y la campana sigue diciendo
     `pedido_validado` como siempre.
  C. "Esperando desde" = `updated_at` del pedido: viaja en el listado (aditivo).
  D. La traza del aviso vive en `auditoria` (por PEDIDO: `notificaciones_enviadas`
     dedupea por alumno+tipo+día y no sabe de pedidos).
  E. La pantalla móvil: lista `?estado=validado`, avisa con los endpoints nuevos y
     tocar un pedido lleva a la pantalla de Pedidos (no a la ficha del alumno).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pedidos_aviso_retiro.py -q --noconftest
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from app.api.v1.pedidos import AVISO_RETIRO_TIPO   # noqa: E402
    from app.services import codigos_retiro            # noqa: E402
except Exception as exc:   # pragma: no cover - entorno sin dependencias del backend
    pytest.skip(f"no se pudo importar el router de pedidos: {exc}",
                allow_module_level=True)

RAIZ = Path(__file__).resolve().parents[2]
PEDIDOS = "backend/app/api/v1/pedidos.py"
FRONT = "frontend/src/pages/admin/InicioMobileAdmin.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _bloque(fuente: str, desde: str, hasta: str) -> str:
    """El texto entre dos marcas (hasta el final del archivo si la marca no está)."""
    inicio = fuente.index(desde)
    final = fuente.find(hasta, inicio)
    return fuente[inicio:] if final == -1 else fuente[inicio:final]


def _pedido(**kwargs):
    base = {"estado": "validado", "codigo_retiro": "UB-7K3M", "entregado_en": None,
            "cantidad": 2, "entregado_por": None}
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── A. El filtro: validado sin retirar ───────────────────────────────────────

def test_a1_un_validado_sin_entregar_se_puede_recordar():
    assert codigos_retiro.motivo_no_entregable(_pedido()) is None


def test_a2_un_pendiente_no_tiene_retiro_que_recordar():
    assert (codigos_retiro.motivo_no_entregable(_pedido(estado="pendiente",
                                                       codigo_retiro=None))
            == codigos_retiro.MOTIVO_NO_VALIDADO)


def test_a3_un_entregado_ya_no_espera_nada():
    assert (codigos_retiro.motivo_no_entregable(_pedido(estado="entregado"))
            == codigos_retiro.MOTIVO_YA_ENTREGADO)


def test_a4_sin_codigo_de_retiro_no_se_promete_un_retiro():
    fuente = _fuente(PEDIDOS)
    guardas = _bloque(fuente, "def _pedido_para_avisar", "\ndef ultimo_aviso_manual")
    assert "motivo_no_entregable(pedido)" in guardas          # la regla del mesón
    assert "if not pedido.codigo_retiro:" in guardas          # sin código, no hay correo
    assert "El pedido todavía no tiene código de retiro" in guardas


# ── B. No toca la campana automática `pedido_validado` ───────────────────────

def test_b1_el_aviso_manual_usa_un_tipo_propio():
    assert AVISO_RETIRO_TIPO == "pedido_recordatorio_manual"
    assert AVISO_RETIRO_TIPO != "pedido_validado"
    servicio = _fuente("backend/app/services/alertas_email_service.py")
    automaticos = set(re.findall(r'_(?:reclamar_envio|ya_enviado)\([^)]*?"([a-z_]+)"', servicio))
    assert len(automaticos) >= 4
    assert AVISO_RETIRO_TIPO not in automaticos


def test_b2_el_aviso_manual_no_escribe_en_la_campana():
    fuente = _fuente(PEDIDOS)
    preview = _bloque(fuente, "def preview_aviso_retiro", "\n@router.")
    enviar = _bloque(fuente, "def enviar_aviso_retiro", "\n\ndef _pedido_del_box")
    for cuerpo in (preview, enviar):
        assert "notificar_alumno" not in cuerpo
        assert "notificar_admins_del_tenant" not in cuerpo


def test_b3_la_campana_de_validacion_sigue_igual():
    fuente = _fuente(PEDIDOS)
    validar = _bloque(fuente, "def actualizar_estado_pedido", "\n@router.")
    # El aviso de la campana al validar se arma con el código y viaja como
    # `pedido_<estado>` (pedido_validado): el correo manual es OTRA cosa.
    assert "codigos_retiro.texto_validado(" in validar
    assert 'f"pedido_{nuevo_estado}"' in validar


def test_b4_el_envio_manual_reclama_su_fila_y_no_la_dobla():
    fuente = _fuente(PEDIDOS)
    enviar = _bloque(fuente, "def enviar_aviso_retiro", "\n\ndef _pedido_del_box")
    assert "reclamar_envio_manual(db, alumno.id, AVISO_RETIRO_TIPO" in enviar
    assert "registrar=False" in enviar          # la fila la escribe el endpoint
    assert "ya_enviado" in enviar
    assert "_marcar_fallido" in enviar          # un fallo queda visible, no como éxito


# ── C. "Esperando desde" (updated_at en el listado) ─────────────────────────

def test_c1_el_listado_expone_updated_at():
    esquema = _fuente("backend/app/schemas/pedido.py")
    item = _bloque(esquema, "class PedidoListItem", "\n\n# ")
    assert "updated_at: Optional[datetime]" in item
    fuente = _fuente(PEDIDOS)
    con_nombres = _bloque(fuente, "def _con_nombres", "\n@router.")
    assert '"updated_at": p.updated_at' in con_nombres


# ── D. La traza del aviso (por pedido) ──────────────────────────────────────

def test_d1_la_traza_es_por_pedido_en_auditoria():
    fuente = _fuente(PEDIDOS)
    traza = _bloque(fuente, "def ultimo_aviso_manual", "\n@router.")
    assert 'Auditoria.accion == "EMAIL_MANUAL"' in traza
    assert 'Auditoria.entidad == "pedido"' in traza
    assert "Auditoria.entidad_id.in_(pedido_ids)" in traza
    # Una sola consulta para toda la lista (GROUP BY), no una por fila.
    assert "func.max(Auditoria.fecha)" in traza


def test_d2_el_envio_deja_la_traza_con_el_codigo():
    fuente = _fuente(PEDIDOS)
    enviar = _bloque(fuente, "def enviar_aviso_retiro", "\n\ndef _pedido_del_box")
    assert 'entidad="pedido"' in enviar
    assert "entidad_id=pedido.id" in enviar
    assert '"origen": "panel_admin_movil"' in enviar



# ── E. La pantalla móvil ────────────────────────────────────────────────────

def test_e1_la_pantalla_lista_los_validados_y_avisa_con_los_endpoints():
    fuente = _fuente(FRONT)
    assert "estado: 'validado'" in fuente
    assert "/aviso-retiro/preview`)" in fuente
    assert "/aviso-retiro`)" in fuente
    # El "Informado hace X" sale de la traza de auditoría (una sola llamada).
    assert "'/api/v1/auditoria'" in fuente
    assert "accion: 'EMAIL_MANUAL'" in fuente


def test_e2_tocar_un_pedido_lleva_a_la_pantalla_de_pedidos():
    fuente = _fuente(FRONT)
    assert "navigate('/admin/pedidos')" in fuente
    # Y NO a la ficha del alumno (eso es de la otra pantalla).
    assert "irAPedido" in fuente

