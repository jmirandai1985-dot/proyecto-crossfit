from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from app.db.database import get_db
from app.models.suscripcion import EstadoSuscripcion, Suscripcion
from app.models.transaccion_financiera import TransaccionFinanciera
from app.models.usuario import Usuario
from app.core.dependencies import get_current_admin
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.services import churn_service
from app.services import referidos_service
from app.services.auditoria_service import registrar_auditoria
from app.models.plan import Plan
from app.utils.santiago import hoy_santiago, fin_de_plan_chile, fin_del_dia_chile   # HOY en Chile (la TZ del proceso es UTC)

router = APIRouter()


# ── Idempotencia del alta manual de plan (ACID) ───────────────────────────────
# `POST /suscripciones` es el alta MANUAL del admin (ajuste/venta en el mesón).
# Un doble clic, dos pestañas o un reintento del móvil creaban DOS suscripciones
# y DOS ingresos en `transacciones_financieras`: el box quedaba con el doble de
# plata en caja y el alumno con el doble de créditos. La ventana es corta a
# propósito: un admin SÍ puede necesitar vender el mismo plan dos veces al mismo
# alumno (renovación) — sólo bloquea el duplicado inmediato, el que produce un
# reintento. Mismo plan + mismo alumno + misma ventana = un solo alta.
VENTANA_IDEMPOTENCIA = timedelta(minutes=10)


class SuscripcionCreate(BaseModel):
    tenant_id: int
    usuario_id: int
    plan_id: int
    # Tipado con el ENUM (no `str`): un label inválido da 422 en el borde, en vez
    # de llegar a la BD y explotar con un 500. Los strings válidos ("activo", ...)
    # se coercionan al miembro del enum.
    estado: EstadoSuscripcion = EstadoSuscripcion.activo
    creditos_totales: Optional[int] = None
    creditos_disponibles: Optional[int] = None
    fecha_inicio: Optional[str] = None
    # OPCIONAL desde 2026-10-06: si no viene, se calcula `inicio + plan.duracion_dias`
    # (días de Chile) con la MISMA función que la aprobación de una solicitud
    # (`fin_de_plan_chile`). Antes era obligatoria.
    fecha_expiracion: Optional[str] = None


class SuscripcionUpdate(BaseModel):
    """Edición manual de una suscripción (sólo admin).

    Todos los campos son OPCIONALES: se actualiza únicamente lo que venga en el
    body (`model_dump(exclude_unset=True)` distingue "no vino" de "vino en null").
    `fecha_expiracion` viaja como ISO: si es una fecha sin hora ('YYYY-MM-DD') se
    interpreta como el DÍA chileno de vencimiento y se guarda a las 23:59:59 de
    Chile, la misma regla de `fin_de_plan_chile`.
    """
    plan_id: Optional[int] = None
    fecha_expiracion: Optional[str] = None
    creditos_totales: Optional[int] = None
    creditos_disponibles: Optional[int] = None


@router.post("/suscripciones", status_code=201)
@limiter.limit(LIMIT_CRITICO)
def crear_suscripcion(
    request: Request,
    data: SuscripcionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (el body se ignora).
    data.tenant_id = current_user["tenant_id"]

    # ── Idempotencia (ACID): mismo alumno + mismo plan dentro de la ventana ──
    # El `FOR UPDATE` sobre la fila del ALUMNO serializa dos altas simultáneas
    # del MISMO alumno: el segundo request espera y, al entrar, ve la
    # suscripción que el primero acaba de commitear. Sin el lock, los dos
    # SELECT verían "no hay ninguna" y las dos altas pasarían (doble crédito,
    # doble ingreso en caja).
    db.query(Usuario).filter(
        Usuario.id == data.usuario_id,
        Usuario.tenant_id == data.tenant_id,
    ).with_for_update().first()

    gemela = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == data.tenant_id,
        Suscripcion.usuario_id == data.usuario_id,
        Suscripcion.plan_id == data.plan_id,
        Suscripcion.created_at >= datetime.now(timezone.utc) - VENTANA_IDEMPOTENCIA,
    ).order_by(Suscripcion.id.desc()).first()

    if gemela is not None:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(f"Ya existe una suscripción de este plan para este alumno "
                    f"(#{gemela.id}) creada hace menos de "
                    f"{int(VENTANA_IDEMPOTENCIA.total_seconds() // 60)} minutos. "
                    "Si de verdad necesitas otra alta, espera unos minutos."),
        )

    # ── Inicio: el body puede traerlo; si no, ahora (UTC, como antes). ──
    if data.fecha_inicio:
        try:
            inicio_dt = datetime.fromisoformat(
                data.fecha_inicio.replace('Z', '+00:00'))
        except Exception:
            raise HTTPException(
                status_code=400, detail="Formato de fecha_inicio inválido.")
    else:
        inicio_dt = datetime.now(timezone.utc)

    plan = db.query(Plan).filter(Plan.id == data.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # ── Vencimiento: si viene en el body se respeta; si no, ÚNICA regla
    # `inicio + plan.duracion_dias` (días de Chile), la MISMA que `aprobar_solicitud`. ──
    if data.fecha_expiracion:
        try:
            fecha_exp = datetime.fromisoformat(
                data.fecha_expiracion.replace('Z', '+00:00'))
        except Exception:
            raise HTTPException(
                status_code=400, detail="Formato de fecha_expiracion inválido.")
    else:
        fecha_exp = fin_de_plan_chile(inicio_dt, plan.duracion_dias)

    db_sus = Suscripcion(
        tenant_id=data.tenant_id,
        usuario_id=data.usuario_id,
        plan_id=data.plan_id,
        estado=data.estado,
        creditos_totales=data.creditos_totales,
        creditos_disponibles=data.creditos_disponibles,
        fecha_inicio=inicio_dt,
        fecha_expiracion=fecha_exp,
    )
    db.add(db_sus)

    # ── Fase 3b: la compra queda CONFIRMADA con esta suscripción ──
    # `flush()` asigna el id sin commitear; `confirmar_compra` convierte el
    # referido del invitado / consume el crédito del invitador y devuelve el
    # precio que se debe cobrar. Suscripción, premio e ingreso van en la MISMA
    # transacción: no puede quedar una compra sin su descuento.
    db.flush()
    descuento_referido = referidos_service.confirmar_compra(
        db,
        tenant_id=data.tenant_id,
        usuario_id=data.usuario_id,
        precio_lista_clp=int(plan.precio_clp or 0),
        suscripcion_id=db_sus.id,
    )

    db.commit()
    db.refresh(db_sus)

    # ── FIX P3b (consistencia con aprobar_solicitud): al crear una membresía
    # paga, expirar la suscripción "Prueba" activa del alumno (estado='vencido')
    # para que el gate de modo prueba se desbloquee (es_usuario_prueba → False).
    # Mismo criterio que solicitudes_planes (FIX 3). No aplica si el plan nuevo
    # es "Prueba". Nunca debe impedir la creación si falla.
    try:
        # `Plan` está importado a nivel de módulo. Un import local acá volvía
        # `Plan` una variable local de TODA la función y el primer uso
        # (línea del plan principal) explotaba con UnboundLocalError.
        plan_nuevo = db.query(Plan).filter(Plan.id == data.plan_id).first()
        if plan_nuevo and plan_nuevo.nombre != "Prueba":
            sus_prueba = db.query(Suscripcion).join(
                Plan, Suscripcion.plan_id == Plan.id
            ).filter(
                Suscripcion.usuario_id == data.usuario_id,
                Suscripcion.estado == "activo",
                Plan.nombre == "Prueba",
            ).all()
            for sp in sus_prueba:
                sp.estado = "vencido"
            db.commit()
    except Exception as e:
        import logging
        logging.getLogger("uvicorn").warning(f"No se pudo expirar suscripcion Prueba: {e}")

    # ── Auditoría interna: alta de suscripción (ajuste de tokens) ──
    registrar_auditoria(
        db,
        tenant_id=current_user["tenant_id"],
        usuario_id=current_user["usuario_id"],
        accion="CREATE",
        entidad="suscripcion",
        entidad_id=db_sus.id,
        detalle={
            "usuario_id": data.usuario_id,
            "plan_id": data.plan_id,
            "estado": data.estado,
            "creditos_totales": data.creditos_totales,
            "creditos_disponibles": data.creditos_disponibles,
            # Fase 3b: el descuento que se aplicó a ESTA compra (0 = sin premio).
            "descuento_referido_clp": (descuento_referido["descuento_clp"]
                                       if descuento_referido is not None else 0),
        },
    )

    # Auto-insertar ingreso en transacciones_financieras
    try:
        plan = db.query(Plan).filter(Plan.id == data.plan_id).first()
        if plan and plan.precio_clp > 0:
            # Fase 3b: se registra el precio FINAL (con descuento de referido),
            # no el de lista: el ingreso tiene que ser lo que realmente se cobró.
            monto_facturado = (descuento_referido["precio_final_clp"]
                               if descuento_referido is not None
                               else plan.precio_clp)
            alumno_tx = db.query(Usuario).filter(Usuario.id == data.usuario_id).first()
            nombre_alumno_tx = alumno_tx.nombre if alumno_tx else f"usuario #{data.usuario_id}"
            tx = TransaccionFinanciera(
                tenant_id=data.tenant_id,
                tipo='ingreso',
                categoria='membresia',
                monto=monto_facturado,
                descripcion=f"Suscripcion plan {plan.nombre} ({nombre_alumno_tx})",
                referencia_tipo='suscripcion',
                referencia_id=db_sus.id,
                fecha=hoy_santiago(),
            )
            db.add(tx)
            db.commit()
    except Exception as e:
        # No debe impedir la creacion de la suscripcion si falla la transaccion
        import logging
        logging.getLogger("uvicorn").warning(
            f"No se pudo registrar transaccion financiera: {e}")

    # ── La membresía cambió el plan vigente y/o los créditos del alumno: se ENCOLA su recálculo
    # de churn (segundo plano, sin bloquear): la próxima lectura del panel ya trae el snapshot
    # fresco (motivo/recomendación/renovación de HOY). Mismo enganche que aprobar una solicitud.
    churn_service.programar_recalculo(background_tasks, data.tenant_id, data.usuario_id)

    return db_sus


@router.put("/suscripciones/{suscripcion_id}")
@limiter.limit(LIMIT_CRITICO)
def editar_suscripcion(
    suscripcion_id: int,
    request: Request,
    data: SuscripcionUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Edita una suscripción YA existente: plan, vencimiento y créditos.

    Se actualiza SÓLO lo que viene en el body (todos los campos son opcionales).
    Reglas:

      * la suscripción tiene que ser del box del token (404 si no existe allá);
      * `mp_preapproval_id` no nulo = alta automática de Mercado Pago: 409, porque
        el webhook de MP volvería a escribir esos campos y la desincronizaría;
      * si viene `plan_id`, el plan tiene que existir en el MISMO box (404 si no);
      * el estado final de créditos tiene que ser coherente:
        `creditos_disponibles <= creditos_totales` (salvo plan ilimitado).

    Queda registrado en `auditoria` con los campos que REALMENTE cambiaron
    (antes/después). Mismo shape de respuesta que `listar_suscripciones`.
    """
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (el body no lo trae).
    tenant_id = current_user["tenant_id"]

    # `FOR UPDATE`: dos ediciones simultáneas de la misma suscripción se
    # serializan (la segunda espera y ve los valores ya guardados).
    suscripcion = (
        db.query(Suscripcion)
        .filter(Suscripcion.id == suscripcion_id,
                Suscripcion.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    if suscripcion is None:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")

    if suscripcion.mp_preapproval_id is not None:
        raise HTTPException(
            status_code=409,
            detail=("Esta suscripción está vinculada a un pago automático de "
                    "Mercado Pago y no se puede editar manualmente."),
        )

    cambios = data.model_dump(exclude_unset=True)

    # ── Plan resultante: el nuevo (si viene) o el actual. Siempre del MISMO box. ──
    if "plan_id" in cambios:
        plan = db.query(Plan).filter(
            Plan.id == cambios["plan_id"],
            Plan.tenant_id == tenant_id,
        ).first()
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan no encontrado")
    else:
        plan = db.query(Plan).filter(Plan.id == suscripcion.plan_id).first()

    # ── Vencimiento: fecha sola ('YYYY-MM-DD') = día chileno completo ──
    if "fecha_expiracion" in cambios:
        valor = cambios["fecha_expiracion"]
        if not valor:
            raise HTTPException(status_code=400,
                                detail="Formato de fecha_expiracion inválido.")
        try:
            fecha_exp = datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
        except Exception:
            raise HTTPException(status_code=400,
                                detail="Formato de fecha_expiracion inválido.")
        if fecha_exp.tzinfo is None:
            # Sin zona: es un DÍA de Chile (lo que elige el admin en el date picker).
            # Se guarda a las 23:59:59 de ese día, como `fin_de_plan_chile`.
            fecha_exp = fin_del_dia_chile(fecha_exp.date())
        cambios["fecha_expiracion"] = fecha_exp

    # ── Coherencia de créditos sobre el estado FINAL (no sólo el campo que vino) ──
    totales = cambios.get("creditos_totales", suscripcion.creditos_totales)
    disponibles = cambios.get("creditos_disponibles", suscripcion.creditos_disponibles)
    if (plan is not None and not plan.es_ilimitado
            and totales is not None and disponibles is not None
            and disponibles > totales):
        raise HTTPException(
            status_code=400,
            detail=("Los créditos disponibles no pueden superar los créditos "
                    f"totales ({disponibles} > {totales})."),
        )

    # ── Aplicar SÓLO lo que cambia + auditoría antes/después ──
    cambios_reales = {}
    for campo, nuevo in cambios.items():
        anterior = getattr(suscripcion, campo)
        if anterior == nuevo:
            continue
        cambios_reales[campo] = {
            "antes": anterior.isoformat() if isinstance(anterior, datetime) else anterior,
            "despues": nuevo.isoformat() if isinstance(nuevo, datetime) else nuevo,
        }
        setattr(suscripcion, campo, nuevo)

    if not cambios_reales:
        # Nada cambió: se cierra la transacción (suelta el lock) y se devuelve igual.
        # `refresh` porque el commit expira los atributos y la respuesta los serializa.
        db.commit()
        db.refresh(suscripcion)
        return suscripcion

    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="UPDATE",
        entidad="suscripcion",
        entidad_id=suscripcion.id,
        detalle={
            "usuario_id": suscripcion.usuario_id,
            "cambios": cambios_reales,
        },
    )
    # `registrar_auditoria` commitea: suscripción y auditoría quedan juntas.
    db.refresh(suscripcion)

    # El plan vigente / los créditos / el vencimiento cambiaron: se ENCOLA el
    # recálculo de churn del alumno, igual que el alta (`crear_suscripcion`).
    churn_service.programar_recalculo(background_tasks, tenant_id,
                                      suscripcion.usuario_id)

    return suscripcion


@router.get("/suscripciones")
def listar_suscripciones(
    tenant_id: Optional[int] = Query(None),
    usuario_id: Optional[int] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    query = db.query(Suscripcion).filter(Suscripcion.tenant_id == tenant_id)
    if usuario_id:
        query = query.filter(Suscripcion.usuario_id == usuario_id)
    if estado:
        query = query.filter(Suscripcion.estado == estado)
    return query.order_by(Suscripcion.created_at.desc()).all()
