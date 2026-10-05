"""
Aislamiento de los avisos del PANEL (app/services/notificaciones_panel.py).

Qué se prueba, SIN red y SIN base de datos (sesión FALSA en memoria, igual que el
cliente R2 falso de test_storage_r2.py):

  * `notificar_admins_del_tenant` crea 1 aviso por cada admin que devuelve la
    consulta, con `alumno_id` = id del admin, `tipo`/`mensaje` recibidos y
    `leida=False`; y la consulta filtra por `tenant_id`, `rol='administrador'` y
    `estado='activo'` (la frontera del box de este módulo: `notificaciones` no
    tiene `tenant_id` propio);
  * sin admins -> 0 avisos y sin commit (no se abre transacción al pedo);
  * `commit=False` deja el aviso en la transacción del llamador (no commitea);
  * BEST-EFFORT: si la BD falla, devuelve 0/None y NO levanta (una compra no
    puede caerse porque no se pudo escribir un aviso). El rollback sólo se hace
    cuando la transacción la cerró el módulo (`commit=True`);
  * `notificar_alumno`: id vacío -> None sin tocar la BD;
  * los mensajes de estado del Bazar (`MENSAJES_ESTADO_PEDIDO`) existen para
    validado/entregado y el `tipo` que genera `pedidos.py` entra en la columna
    (`String(20)`);
  * CONTRATO de los flujos que avisan al ADMIN: la solicitud de plan con voucher
    (`plan_solicitado`), el alta de alumno (`alumno_nuevo`) y la cobertura de
    emergencia llaman a `notificar_admins_del_tenant`, y la emergencia NO vuelve a
    construir la fila a mano (el bug era que no filtraba por `estado`).

Los avisos end-to-end (pedido real por API) los cubre la integración
tests/test_pedidos_notificaciones.py; los del voucher de plan y el alta de
alumno, la integración tests/test_notificaciones_admin_flujos.py.
"""
from pathlib import Path
from types import SimpleNamespace

from app.api.v1.pedidos import MENSAJES_ESTADO_PEDIDO
from app.models.notificacion import Notificacion
from app.models.usuario import RolUsuario, Usuario
from app.services import notificaciones_panel

TENANT = 1


class _ConsultaFalsa:
    """`db.query(...).filter(...).all()` con filas fijas y filtros capturados."""

    def __init__(self, filas):
        self.filas = list(filas)
        self.criterios = []

    def filter(self, *criterios):
        self.criterios.extend(criterios)
        return self

    def all(self):
        return list(self.filas)


class _SesionFalsa:
    """Session mínima: registra add/commit/flush/rollback y no toca ninguna BD."""

    def __init__(self, admins=(), fallar_en_add=False):
        self.admins = list(admins)
        self.fallar_en_add = fallar_en_add
        self.agregadas = []
        self.commits = 0
        self.flushes = 0
        self.rollbacks = 0
        self.modelo_consultado = None
        self.consulta = None

    def query(self, modelo):
        self.modelo_consultado = modelo
        self.consulta = _ConsultaFalsa(self.admins)
        return self.consulta

    def add(self, obj):
        if self.fallar_en_add:
            raise RuntimeError("BD caída (fake)")
        self.agregadas.append(obj)

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _admins(*ids):
    return [SimpleNamespace(id=i, nombre=f"Admin {i}") for i in ids]


def _columnas(criterios):
    return [getattr(c.left, "key", None) for c in criterios]


def _valores(criterios):
    return [getattr(c.right, "value", None) for c in criterios]


# ── notificar_admins_del_tenant ────────────────────────────────────────────

def test_notifica_a_cada_admin_del_tenant():
    db = _SesionFalsa(admins=_admins(7, 9))
    creados = notificaciones_panel.notificar_admins_del_tenant(
        db, TENANT, "pedido_nuevo", "Nuevo pedido de Ana: Polera x2")

    assert creados == 2
    assert db.commits == 1
    assert db.modelo_consultado is Usuario
    assert [n.alumno_id for n in db.agregadas] == [7, 9]
    for n in db.agregadas:
        assert isinstance(n, Notificacion)
        assert n.tipo == "pedido_nuevo"
        assert n.mensaje == "Nuevo pedido de Ana: Polera x2"
        assert n.leida is False


def test_la_consulta_filtra_por_box_rol_y_estado():
    """La frontera de tenant vive en el filtro: si desaparece, el test falla."""
    db = _SesionFalsa(admins=_admins(7))
    notificaciones_panel.notificar_admins_del_tenant(
        db, TENANT, "pedido_nuevo", "m")

    assert _columnas(db.consulta.criterios) == ["tenant_id", "rol", "estado"]
    valores = _valores(db.consulta.criterios)
    assert TENANT in valores
    assert RolUsuario.administrador in valores
    assert "activo" in valores


def test_box_sin_admins_no_crea_ni_commitea():
    db = _SesionFalsa(admins=[])
    creados = notificaciones_panel.notificar_admins_del_tenant(
        db, TENANT, "pedido_nuevo", "m")

    assert creados == 0
    assert db.agregadas == []
    assert db.commits == 0
    assert db.flushes == 0


def test_tenant_id_vacio_no_toca_la_bd():
    db = _SesionFalsa(admins=_admins(7))
    assert notificaciones_panel.notificar_admins_del_tenant(
        db, 0, "pedido_nuevo", "m") == 0
    assert db.consulta is None
    assert db.agregadas == []
    assert db.commits == 0


def test_commit_false_deja_la_transaccion_al_llamador():
    db = _SesionFalsa(admins=_admins(7))
    creados = notificaciones_panel.notificar_admins_del_tenant(
        db, TENANT, "pedido_nuevo", "m", commit=False)

    assert creados == 1
    assert len(db.agregadas) == 1
    assert db.commits == 0
    assert db.flushes == 1


def test_fallo_de_bd_no_rompe_el_flujo():
    db = _SesionFalsa(admins=_admins(7), fallar_en_add=True)
    creados = notificaciones_panel.notificar_admins_del_tenant(
        db, TENANT, "pedido_nuevo", "m")

    assert creados == 0
    assert db.rollbacks == 1
    assert db.commits == 0


def test_commit_false_no_hace_rollback_de_lo_ajeno():
    db = _SesionFalsa(admins=_admins(7), fallar_en_add=True)
    creados = notificaciones_panel.notificar_admins_del_tenant(
        db, TENANT, "pedido_nuevo", "m", commit=False)

    assert creados == 0
    assert db.rollbacks == 0


# ── notificar_alumno ───────────────────────────────────────────────────────

def test_notificar_alumno_crea_el_aviso():
    db = _SesionFalsa()
    aviso = notificaciones_panel.notificar_alumno(
        db, 42, "pedido_validado", "Tu pedido fue validado")

    assert isinstance(aviso, Notificacion)
    assert aviso.alumno_id == 42
    assert aviso.tipo == "pedido_validado"
    assert aviso.mensaje == "Tu pedido fue validado"
    assert aviso.leida is False
    assert db.agregadas == [aviso]
    assert db.commits == 1


def test_notificar_alumno_commit_false_no_commitea():
    db = _SesionFalsa()
    aviso = notificaciones_panel.notificar_alumno(
        db, 42, "pedido_entregado", "m", commit=False)

    assert aviso is not None
    assert db.commits == 0
    assert db.flushes == 1


def test_notificar_alumno_sin_id_no_toca_la_bd():
    db = _SesionFalsa()
    assert notificaciones_panel.notificar_alumno(db, None, "t", "m") is None
    assert notificaciones_panel.notificar_alumno(db, 0, "t", "m") is None
    assert db.agregadas == []
    assert db.commits == 0


def test_notificar_alumno_es_best_effort():
    db = _SesionFalsa(fallar_en_add=True)
    assert notificaciones_panel.notificar_alumno(db, 42, "t", "m") is None
    assert db.rollbacks == 1


# ── notificar_usuario (B3: el destinatario puede ser coach/admin) ──────────

def test_notificar_usuario_crea_el_aviso_del_destinatario():
    db = _SesionFalsa()
    aviso = notificaciones_panel.notificar_usuario(
        db, 7, "clase_asignada", "🟦 El admin te asignó la clase de CrossFit")

    assert isinstance(aviso, Notificacion)
    assert aviso.alumno_id == 7              # 7 = id de usuario, no de alumno
    assert aviso.tipo == "clase_asignada"
    assert aviso.leida is False
    assert db.commits == 1


def test_notificar_usuario_commit_false_es_la_transaccion_del_llamador():
    db = _SesionFalsa()
    assert notificaciones_panel.notificar_usuario(
        db, 7, "clase_liberada", "m", commit=False) is not None
    assert db.commits == 0
    assert db.flushes == 1


def test_notificar_usuario_sin_id_no_toca_la_bd():
    db = _SesionFalsa()
    assert notificaciones_panel.notificar_usuario(db, None, "t", "m") is None
    assert db.agregadas == []
    assert db.commits == 0


def test_notificar_usuario_es_best_effort():
    db = _SesionFalsa(fallar_en_add=True)
    assert notificaciones_panel.notificar_usuario(db, 7, "t", "m") is None
    assert db.rollbacks == 1


def test_notificar_alumno_es_un_alias_de_notificar_usuario():
    db = _SesionFalsa()
    aviso = notificaciones_panel.notificar_alumno(db, 42, "pedido_validado", "m")
    assert aviso is not None and aviso.alumno_id == 42


# ── mensajes / contrato con pedidos.py ─────────────────────────────────────

def test_mensajes_de_estado_del_bazar():
    assert set(MENSAJES_ESTADO_PEDIDO) == {"validado", "entregado"}
    render = MENSAJES_ESTADO_PEDIDO["validado"].format(
        producto="Polera", cantidad=2)
    assert "Polera x2" in render
    assert render.endswith("fue validado")


def test_los_tipos_entran_en_la_columna():
    """`Notificacion.tipo` es String(20): TODO tipo que se genera tiene que caber.

    Un tipo de 21 caracteres NO rompe el flujo (el aviso es best-effort): revienta
    el INSERT y el aviso se pierde en silencio, así que se revisa acá — es más
    barato que descubrirlo cuando el badge del admin no enciende.
    """
    for estado in MENSAJES_ESTADO_PEDIDO:
        assert len(f"pedido_{estado}") <= 20
    for tipo in ("pedido_nuevo", "plan_solicitado", "alumno_nuevo", "emergencia",
                 "aprobado", "rechazado", "plan_activo", "clase_asignada",
                 "clase_reasignada", "clase_liberada"):
        assert len(tipo) <= 20, tipo


# ── contrato de los flujos que avisan al ADMIN ────────────────────────────────
# Guardas de FUENTE (sin BD): el bug no era del helper, era que los flujos que
# tienen que avisar al admin no lo llamaban (el voucher de una solicitud de plan
# no avisaba a nadie) o que armaban la fila a mano salteándose el filtro de
# destinatarios (emergencia sin `estado='activo'`). Mismo patrón que
# test_estados_compartido.py / test_asignaciones_clases.py, que leen el código.

def _fuente(relativa: str) -> str:
    raiz = Path(__file__).resolve().parents[1]      # .../backend
    return (raiz / relativa).read_text(encoding="utf-8")


def test_la_solicitud_de_plan_avisa_a_los_admins():
    """POST /solicitudes/solicitar deja el aviso en la campana del box."""
    fuente = _fuente("app/api/v1/solicitudes_planes.py")
    assert "from app.services.notificaciones_panel import notificar_admins_del_tenant" in fuente
    assert "notificar_admins_del_tenant(" in fuente
    assert '"plan_solicitado"' in fuente


def test_el_registro_de_alumno_avisa_a_los_admins():
    """POST /alumnos/registro/alumno-nuevo avisa al admin sin depender del correo."""
    fuente = _fuente("app/api/v1/alumnos.py")
    assert "from app.services.notificaciones_panel import notificar_admins_del_tenant" in fuente
    assert "notificar_admins_del_tenant(" in fuente
    assert '"alumno_nuevo"' in fuente


def test_la_emergencia_usa_el_helper_y_filtra_admins_activos():
    """La emergencia avisa por el helper, no armando la fila a mano.

    Dos cosas que se rompieron antes y que esta prueba congela: la fila in-app se
    construía a mano (sin `estado='activo'`, así que un admin dado de baja seguía
    recibiendo la alerta) y el helper no se usaba en este flujo.
    """
    fuente = _fuente("app/core/dependencies.py")
    assert "from app.services.notificaciones_panel import notificar_admins_del_tenant" in fuente
    assert 'notificar_admins_del_tenant(\n            db, tenant_id, "emergencia", mensaje' in fuente
    assert "Notificacion(" not in fuente
    assert 'Usuario.estado == "activo"' in fuente


