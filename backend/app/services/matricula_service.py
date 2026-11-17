"""Matrícula configurable del box: UN monto por box, cobrado UNA vez al alumno nuevo.

Reglas que este módulo hace cumplir (y que no viven en los endpoints):

* **El monto y el "aplica" los decide el backend.** El front sólo MUESTRA lo que
  devuelve `monto_para_alumno()`; nunca manda plata.
* **"Alumno nuevo" = nunca tuvo una suscripción a un plan PAGADO** (`precio_clp > 0`
  y `es_comercial`). El plan "Prueba" del alta (gratis) y el "Pase de regreso"
  (gratis, no comercial) NO cuentan: casi todos los alumnos pasan por Prueba al
  registrarse y la matrícula se cobra en la PRIMERA membresía realmente pagada.
  Es el MISMO criterio de "membresía pagada" que usa
  `services/aprobacion_planes._plan_vigente_usable` (la regla de la cola).
* **Se congela al crear la solicitud** (`SolicitudPlan.matricula_clp_snapshot`):
  apagar o cambiar el monto después no mueve una compra en curso.
* **El ingreso va en una transacción APARTE** (`categoria='matricula'`) de la de
  membresía: los KPIs que suman todas las transacciones (ingreso mensual, caja,
  Reportes) la incluyen, y el ticket de membresía no se infla.

Ver `tests/test_matricula_cobro_integracion.py` (los 3 sitios de creación) y
`tests/test_matricula_service.py` (las reglas puras contra la BD de TEST).
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.models.tenant import Tenant
from app.models.transaccion_financiera import TransaccionFinanciera
from app.models.usuario import Usuario
from app.utils.santiago import hoy_santiago

CATEGORIA = "matricula"


def config(db: Session, tenant_id: int) -> dict:
    """Configuración cruda del box: `{activa, monto_clp, activada_en}`."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        return {"activa": False, "monto_clp": None, "activada_en": None}
    return {
        "activa": bool(tenant.matricula_activa),
        "monto_clp": tenant.matricula_monto_clp,
        "activada_en": tenant.matricula_activada_en,
    }


def monto_vigente(db: Session, tenant_id: int) -> Optional[int]:
    """Monto a cobrar HOY (o `None` si está apagada o sin monto válido).

    Un monto `<= 0` se trata como "apagada": cobrar $0 no es un cobro y mostrar
    "Matrícula $0" en la pantalla del alumno sería ruido.
    """
    cfg = config(db, tenant_id)
    monto = cfg["monto_clp"]
    if not cfg["activa"] or monto is None or monto <= 0:
        return None
    return int(monto)


def alumno_es_nuevo(db: Session, tenant_id: int, alumno_id: int) -> bool:
    """¿Nunca tuvo una membresía PAGADA en este box?

    Sólo cuentan los planes con `precio_clp > 0` y `es_comercial`: "Prueba"
    (gratis) y "Pase de regreso" (gratis, no comercial) quedan afuera a propósito.
    """
    fila = (
        db.query(Suscripcion.id)
        .join(Plan, Plan.id == Suscripcion.plan_id)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id == alumno_id,
            Plan.precio_clp > 0,
            Plan.es_comercial.is_(True),
        )
        .first()
    )
    return fila is None


def monto_para_alumno(db: Session, tenant_id: int,
                      alumno_id: int) -> Optional[int]:
    """Lo que hay que cobrarle a ESTE alumno en ESTA compra (`None` = sin matrícula).

    Es la ÚNICA función que deben usar los flujos de venta: junta las dos
    condiciones (matrícula vigente + alumno nuevo) en una sola respuesta.
    """
    monto = monto_vigente(db, tenant_id)
    if monto is None:
        return None
    return monto if alumno_es_nuevo(db, tenant_id, alumno_id) else None


def alumnos_cobrados(db: Session, tenant_id: int) -> int:
    """Cuántas matrículas se cobraron (para el contador del panel)."""
    return int(
        db.query(TransaccionFinanciera)
        .filter(
            TransaccionFinanciera.tenant_id == tenant_id,
            TransaccionFinanciera.tipo == "ingreso",
            TransaccionFinanciera.categoria == CATEGORIA,
        )
        .count()
    )


def registrar_ingreso(db: Session, *, tenant_id: int, alumno_id: int, monto: int,
                      referencia_tipo: str, referencia_id: int):
    """Agrega la transacción de la matrícula a la sesión (NO commitea).

    El llamador commitea: así la caja entra (o no) junto con el resto de la
    aprobación. Una transacción APARTE de `categoria='membresia'` es lo que
    permite un KPI propio sin romper el ticket promedio de los planes.
    """
    alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
    nombre = alumno.nombre if alumno else f"usuario #{alumno_id}"
    tx = TransaccionFinanciera(
        tenant_id=tenant_id,
        tipo="ingreso",
        categoria=CATEGORIA,
        monto=monto,
        descripcion=f"Matricula alumno nuevo ({nombre})",
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        fecha=hoy_santiago(),
    )
    db.add(tx)
    return tx
